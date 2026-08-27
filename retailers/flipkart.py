import json

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


class FlipkartScraperError(Exception):
    """Base exception for Flipkart scraping failures."""


class FlipkartBlockedError(FlipkartScraperError):
    """Flipkart blocked or challenged the request."""


class FlipkartProductNotFoundError(FlipkartScraperError):
    """The page loaded, but no product data was found."""


def get_product(url):

    
    with sync_playwright() as p:

        browser = None

        try:
            browser = p.chromium.launch(
                headless=True
            )

            page = browser.new_page()

            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30_000,
            )

            # --------------------------------------------------
            # HTTP STATUS
            # --------------------------------------------------

            if response is not None:

                status = response.status

                if status in (403, 429):

                    raise FlipkartBlockedError(
                        f"Flipkart returned HTTP {status}"
                    )

                if status >= 500:

                    raise FlipkartScraperError(
                        f"Flipkart returned HTTP {status}"
                    )

            # --------------------------------------------------
            # ALLOW DYNAMIC CONTENT TO LOAD
            # --------------------------------------------------

            page.wait_for_timeout(3000)

            # --------------------------------------------------
            # DETECT FLIPKART'S CAPTCHA/BLOCK PAGE
            # --------------------------------------------------

            page_title = page.title().lower()

            page_content = page.locator(
                "body"
            ).inner_text(
                timeout=5_000
            ).lower()

            if (
                "recaptcha" in page_title
                or "recaptcha" in page_content
            ):

                raise FlipkartBlockedError(
                    "Flipkart presented a CAPTCHA/challenge page"
                )

            # --------------------------------------------------
            # FIND PRODUCT JSON-LD
            # --------------------------------------------------

            scripts = page.locator(
                'script[type="application/ld+json"]'
            )

            product_found = False

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

                    # Some sites use a list of types.
                    if isinstance(item_type, list):
                        is_product = "Product" in item_type
                    else:
                        is_product = item_type == "Product"

                    if not is_product:
                        continue

                    product_found = True

                    offers = item.get(
                        "offers",
                        {}
                    )

                    # Some JSON-LD implementations use
                    # multiple offers.
                    if isinstance(offers, list):

                        offers = (
                            offers[0]
                            if offers
                            else {}
                        )

                    price = offers.get("price")
                    currency = offers.get(
                        "priceCurrency"
                    )
                    availability = offers.get(
                        "availability"
                    )

                    if price is None:
                        continue

                    try:
                        price = float(price)

                    except (TypeError, ValueError):

                        raise FlipkartScraperError(
                            f"Invalid product price: {price}"
                        )

                    available = (
                        availability
                        == "https://schema.org/InStock"
                    )

                    return {
                        "name": item.get("name"),
                        "price": price,
                        "currency": currency,
                        "available": available,
                    }

            # --------------------------------------------------
            # PRODUCT JSON-LD WAS NOT FOUND
            # --------------------------------------------------

            if product_found:

                raise FlipkartProductNotFoundError(
                    "Product JSON-LD found, but no valid price was present"
                )

            raise FlipkartProductNotFoundError(
                "No Product JSON-LD found on the page"
            )

        except PlaywrightTimeoutError as error:

            raise FlipkartScraperError(
                "Flipkart page timed out"
            ) from error

        except FlipkartScraperError:
            raise

        except Exception as error:

            raise FlipkartScraperError(
                f"Unexpected Flipkart scraper error: {error}"
            ) from error

        finally:

            if browser is not None:
                browser.close()