import json

import requests


# ==================================================
# EXCEPTIONS
# ==================================================


class MyntraBlockedError(Exception):
    """Myntra blocked or throttled the request."""


class MyntraProductNotFoundError(Exception):
    """Myntra product data could not be found."""


class MyntraScraperError(Exception):
    """An unexpected Myntra scraping error occurred."""


# ==================================================
# CONSTANTS
# ==================================================


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,image/webp,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


REQUEST_TIMEOUT = 20

MYNTRA_DATA_MARKER = "window.__myx"


# ==================================================
# FETCH
# ==================================================


def _fetch_page(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

    except requests.RequestException as error:
        raise MyntraScraperError(
            f"Request failed: {error}"
        ) from error

    if response.status_code in (403, 429):
        raise MyntraBlockedError(
            f"Myntra returned HTTP "
            f"{response.status_code}"
        )

    if response.status_code != 200:
        raise MyntraScraperError(
            f"Myntra returned HTTP "
            f"{response.status_code}"
        )

    return response.text


# ==================================================
# JAVASCRIPT OBJECT EXTRACTION
# ==================================================


def _extract_javascript_object(
    html,
    marker,
):
    marker_position = html.find(marker)

    if marker_position == -1:
        raise MyntraProductNotFoundError(
            f"Could not find '{marker}' "
            f"in Myntra page."
        )

    equals_position = html.find(
        "=",
        marker_position,
    )

    if equals_position == -1:
        raise MyntraProductNotFoundError(
            "Could not locate Myntra "
            "product data assignment."
        )

    start = html.find(
        "{",
        equals_position,
    )

    if start == -1:
        raise MyntraProductNotFoundError(
            "Could not locate the start of "
            "Myntra product data."
        )

    depth = 0
    in_string = False
    escaped = False

    for position in range(
        start,
        len(html),
    ):

        character = html[position]

        # ------------------------------------------
        # Inside JSON string
        # ------------------------------------------

        if in_string:

            if escaped:
                escaped = False

            elif character == "\\":
                escaped = True

            elif character == '"':
                in_string = False

            continue

        # ------------------------------------------
        # Outside JSON string
        # ------------------------------------------

        if character == '"':
            in_string = True

            continue

        if character == "{":
            depth += 1

            continue

        if character == "}":
            depth -= 1

            if depth == 0:
                return html[
                    start:position + 1
                ]

    raise MyntraProductNotFoundError(
        "Could not find the end of "
        "Myntra product data."
    )


# ==================================================
# PDP DATA
# ==================================================


def _extract_pdp_data(html):
    json_text = _extract_javascript_object(
        html,
        MYNTRA_DATA_MARKER,
    )

    try:
        data = json.loads(json_text)

    except json.JSONDecodeError as error:
        raise MyntraScraperError(
            "Myntra product data could "
            "not be parsed."
        ) from error

    pdp_data = data.get("pdpData")

    if not isinstance(
        pdp_data,
        dict,
    ):
        raise MyntraProductNotFoundError(
            "Myntra PDP data is missing."
        )

    return pdp_data


# ==================================================
# PRICE
# ==================================================


def _get_price(pdp_data):
    price_data = pdp_data.get("price")

    if not isinstance(
        price_data,
        dict,
    ):
        raise MyntraProductNotFoundError(
            "Myntra price data was not found."
        )

    price = price_data.get("discounted")

    if price is None:
        raise MyntraProductNotFoundError(
            "Myntra discounted price "
            "was not found."
        )

    try:
        price = float(price)

    except (TypeError, ValueError) as error:
        raise MyntraScraperError(
            f"Invalid Myntra price: {price!r}"
        ) from error

    if price <= 0:
        raise MyntraScraperError(
            f"Invalid Myntra price: {price}"
        )

    return price


# ==================================================
# AVAILABILITY
# ==================================================


def _get_availability(pdp_data):
    sizes = pdp_data.get(
        "sizes",
        [],
    )

    if not isinstance(
        sizes,
        list,
    ):
        return False

    for size in sizes:

        if not isinstance(
            size,
            dict,
        ):
            continue

        # ------------------------------------------
        # Seller-level inventory
        # ------------------------------------------

        sellers = size.get(
            "sizeSellerData",
            [],
        )

        if isinstance(
            sellers,
            list,
        ):

            for seller in sellers:

                if not isinstance(
                    seller,
                    dict,
                ):
                    continue

                sellable_inventory = seller.get(
                    "sellableInventoryCount"
                )

                available_count = seller.get(
                    "availableCount"
                )

                try:

                    if (
                        sellable_inventory is not None
                        and int(
                            sellable_inventory
                        ) > 0
                    ):
                        return True

                    if (
                        available_count is not None
                        and int(
                            available_count
                        ) > 0
                    ):
                        return True

                except (
                    TypeError,
                    ValueError,
                ):
                    continue

        # ------------------------------------------
        # Size-level fallback
        # ------------------------------------------

        if size.get("available") is True:
            return True

    return False


# ==================================================
# PRODUCT
# ==================================================


def get_product(url):
    """
    Scrape a Myntra product page.

    Returns:
        {
            "name": str,
            "price": float,
            "currency": "INR",
            "available": bool,
        }
    """

    html = _fetch_page(url)

    pdp_data = _extract_pdp_data(html)

    # ----------------------------------------------
    # Product name
    # ----------------------------------------------

    product_name = pdp_data.get("name")

    if not product_name:
        raise MyntraProductNotFoundError(
            "Myntra product name was not found."
        )

    # ----------------------------------------------
    # Price
    # ----------------------------------------------

    price = _get_price(
        pdp_data
    )

    # ----------------------------------------------
    # Availability
    # ----------------------------------------------

    available = _get_availability(
        pdp_data
    )

    # ----------------------------------------------
    # Standard retailer contract
    # ----------------------------------------------

    return {
        "name": product_name,
        "price": price,
        "currency": "INR",
        "available": available,
    }