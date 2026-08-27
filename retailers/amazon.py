import json

from playwright.sync_api import sync_playwright


class AmazonBlockedError(Exception):
    """Amazon blocked the request or presented a challenge page."""


class AmazonProductNotFoundError(Exception):
    """Amazon page loaded, but product data could not be found."""


class AmazonScraperError(Exception):
    """Unexpected Amazon scraping failure."""


def _is_blocked_page(page):
    """
    Detect common Amazon bot-check / challenge pages.
    """

    url = page.url.lower()

    title = ""
    try:
        title = page.title().lower()
    except Exception:
        pass

    body_text = ""
    try:
        body_text = page.locator("body").inner_text(
            timeout=5_000
        ).lower()
    except Exception:
        pass

    blocked_indicators = (
        "captcha",
        "robot check",
        "enter the characters you see below",
        "sorry, we just need to make sure you're not a robot",
        "automated access",
    )

    combined = f"{url}\n{title}\n{body_text}"

    return any(
        indicator in combined
        for indicator in blocked_indicators
    )


def _extract_product_from_json_ld(page):
    """
    Try to extract Product data from schema.org JSON-LD.

    Amazon may expose offers as either a single object
    or a list of objects.
    """

    scripts = page.locator(
        'script[type="application/ld+json"]'
    )

    for i in range(scripts.count()):

        text = scripts.nth(i).text_content()

        if not text:
            continue

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue

        items = (
            data
            if isinstance(data, list)
            else [data]
        )

        for item in items:

            if not isinstance(item, dict):
                continue

            item_type = item.get("@type")

            if isinstance(item_type, list):
                is_product = "Product" in item_type
            else:
                is_product = item_type == "Product"

            if not is_product:
                continue

            product_name = item.get("name")

            offers = item.get("offers")

            if isinstance(offers, list):
                offer_list = offers
            elif isinstance(offers, dict):
                offer_list = [offers]
            else:
                offer_list = []

            for offer in offer_list:

                if not isinstance(offer, dict):
                    continue

                price = offer.get("price")

                if price is None:
                    continue

                currency = offer.get(
                    "priceCurrency",
                    "INR",
                )

                availability = offer.get(
                    "availability",
                    "",
                )

                availability = str(
                    availability
                ).lower()

                available = (
                    availability.endswith(
                        "/instock"
                    )
                    or availability == "instock"
                )

                try:
                    price = float(price)
                except (TypeError, ValueError):
                    continue

                return {
                    "name": product_name,
                    "price": price,
                    "currency": currency,
                    "available": available,
                }

    return None


def _extract_product_from_page(page):
    """
    Fallback extraction from Amazon's visible product page.

    JSON-LD is preferred because it gives us machine-readable
    price/availability data. These selectors are fallback only.
    """

    name = None
    price = None

    # Product title
    try:
        title = page.locator(
            "#productTitle"
        ).first

        if title.count():
            name = title.inner_text().strip()

    except Exception:
        pass

    # Current displayed price.
    #
    # Amazon has used several price containers over time,
    # so try a small set rather than relying on one selector.
    price_selectors = (
        "#corePriceDisplay_desktop_feature_div "
        ".a-price .a-offscreen",

        "#corePrice_feature_div "
        ".a-price .a-offscreen",

        "#priceblock_ourprice",

        "#priceblock_dealprice",

        ".a-price.aok-align-center "
        ".a-offscreen",
    )

    for selector in price_selectors:

        try:
            element = page.locator(
                selector
            ).first

            if not element.count():
                continue

            text = element.inner_text().strip()

            if not text:
                continue

            # Remove common Indian currency formatting.
            cleaned = (
                text
                .replace("₹", "")
                .replace(",", "")
                .strip()
            )

            price = float(cleaned)
            break

        except (ValueError, TypeError):
            continue

        except Exception:
            continue

    if name is None or price is None:
        return None

    # Availability fallback.
    available = False

    availability_selectors = (
        "#availability span",
        "#outOfStock",
        "#buybox .a-size-medium",
    )

    for selector in availability_selectors:

        try:
            elements = page.locator(selector)

            for i in range(elements.count()):

                text = (
                    elements.nth(i)
                    .inner_text()
                    .strip()
                    .lower()
                )

                if not text:
                    continue

                if (
                    "in stock" in text
                    or "available" in text
                ):
                    available = True
                    break

                if (
                    "currently unavailable"
                    in text
                    or "out of stock"
                    in text
                ):
                    available = False
                    break

            if available:
                break

        except Exception:
            continue

    return {
        "name": name,
        "price": price,
        "currency": "INR",
        "available": available,
    }


def get_product(url):
    """
    Retrieve the current Amazon.in product information.

    Returns:
        {
            "name": str,
            "price": float,
            "currency": str,
            "available": bool,
        }

    Raises:
        AmazonBlockedError
        AmazonProductNotFoundError
        AmazonScraperError
    """

    if "amazon.in" not in url.lower():
        raise AmazonScraperError(
            "URL is not an Amazon.in product URL"
        )

    with sync_playwright() as p:

        browser = None

        try:

            browser = p.chromium.launch(
                headless=True
            )

            page = browser.new_page(
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            )

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30_000,
            )

            # Allow Amazon's dynamic product information
            # a moment to populate.
            page.wait_for_timeout(3_000)

            if _is_blocked_page(page):
                raise AmazonBlockedError(
                    "Amazon presented a bot-check or CAPTCHA"
                )

            product = _extract_product_from_json_ld(
                page
            )

            if product is None:
                product = _extract_product_from_page(
                    page
                )

            if product is None:
                raise AmazonProductNotFoundError(
                    "Amazon product data was not found"
                )

            return product

        except (
            AmazonBlockedError,
            AmazonProductNotFoundError,
        ):
            raise

        except Exception as error:
            raise AmazonScraperError(
                str(error)
            ) from error

        finally:

            if browser is not None:
                browser.close()