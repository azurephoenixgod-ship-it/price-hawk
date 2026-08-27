import json
from playwright.sync_api import sync_playwright


def get_product(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30_000
            )

            # Give Flipkart's dynamic content a moment to finish.
            page.wait_for_timeout(3000)

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

                items = data if isinstance(data, list) else [data]

                for item in items:
                    if item.get("@type") != "Product":
                        continue

                    offers = item.get("offers", {})

                    price = offers.get("price")
                    currency = offers.get("priceCurrency")
                    availability = offers.get("availability")

                    if price is None:
                        continue

                    return {
                        "name": item.get("name"),
                        "price": float(price),
                        "currency": currency,
                        "available": (
                            availability
                            == "https://schema.org/InStock"
                        ),
                    }

            return None

        finally:
            browser.close()