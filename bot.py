import os

import requests
from dotenv import load_dotenv

from database import (
    initialize_database,
    get_or_create_user,
    create_watch,
    get_watch_for_user,
    get_price_history_for_user,
    get_watches_for_user,
    delete_watch,
)

from retailers import get_retailer

from retry import scrape_with_retry
from logger import get_logger
from checker import check_watch


# ==================================================
# CONFIGURATION
# ==================================================

load_dotenv()

logger = get_logger("bot")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ==================================================
# CONVERSATION STATE
# ==================================================

# Temporary in-memory state for users going through
# the conversational /add flow.
#
# Example:
#
# pending_adds[chat_id] = {
#     "stage": "target",
#     "url": "...",
#     "retailer": retailer,
#     "product": {...},
# }

pending_adds = {}


# ==================================================
# TELEGRAM
# ==================================================


def send_message(chat_id, text):
    response = requests.post(
        f"{BASE_URL}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": text,
        },
        timeout=20,
    )

    response.raise_for_status()

    return response.json()


def get_updates(offset=None):
    response = requests.get(
        f"{BASE_URL}/getUpdates",
        params={
            "offset": offset,
            "timeout": 30,
        },
        timeout=40,
    )

    response.raise_for_status()

    return response.json()


# ==================================================
# HELP
# ==================================================


def send_help(chat_id):
    send_message(
        chat_id,
        "🦅 Price Hawk\n\n"
        "I watch product prices and alert you "
        "when they hit your target.\n\n"
        "Commands:\n\n"
        "/add\n"
        "Start a guided product watch.\n\n"
        "/add <URL> <target price>\n"
        "Add a product directly.\n\n"
        "/watches\n"
        "Show your watches.\n\n"
        "/history <watch ID>\n"
        "Show price history.\n\n"
        "/price <watch ID>\n"
        "Check the latest price right now.\n\n"
        "/remove <watch ID>\n"
        "Remove one of your watches.\n\n"
        "/cancel\n"
        "Cancel the current operation.\n\n"
        "/help\n"
        "Show this help message."
    )


# ==================================================
# RETAILER / PRODUCT SCRAPING
# ==================================================


def get_supported_retailer(url):
    retailer = get_retailer(url)

    if retailer is None:
        raise ValueError(
            "Unsupported retailer"
        )

    return retailer


def scrape_product(url):
    retailer = get_supported_retailer(url)

    return scrape_with_retry(
        retailer.get_product,
        url,
        blocked_error=retailer.blocked_error,
        product_not_found_error=(
            retailer.product_not_found_error
        ),
        scraper_error=retailer.scraper_error,
    )


# ==================================================
# WATCH CREATION
# ==================================================


def create_user_watch(
    user_id,
    retailer_name,
    url,
    target_price,
    product,
):
    return create_watch(
        user_id=user_id,
        retailer=retailer_name,
        url=url,
        target_price=target_price,
        product_name=product["name"],
        current_price=product["price"],
        currency=product["currency"],
        available=product["available"],
    )


def send_watch_created(
    chat_id,
    watch_id,
    product,
    target_price,
):
    product_name = product["name"]
    current_price = product["price"]
    available = product["available"]

    availability_text = (
        "In stock"
        if available
        else "Currently unavailable"
    )

    send_message(
        chat_id,
        f"🦅 Price Hawk is watching!\n\n"
        f"📦 {product_name}\n"
        f"💰 Current price: "
        f"₹{current_price:,.0f}\n"
        f"🎯 Alert below: "
        f"₹{target_price:,.0f}\n"
        f"📦 Availability: "
        f"{availability_text}\n\n"
        f"Watch ID: #{watch_id}"
    )


# ==================================================
# SCRAPE ERROR HANDLING
# ==================================================


def handle_scrape_error(
    chat_id,
    user_id,
    retailer,
    error,
):
    if isinstance(
        error,
        retailer.blocked_error,
    ):
        logger.warning(
            f"User #{user_id}: "
            f"{retailer.name} blocked request: "
            f"{error}"
        )

        send_message(
            chat_id,
            f"⚠️ {retailer.name} blocked the request.\n\n"
            "Try again later."
        )

        return True

    if isinstance(
        error,
        retailer.product_not_found_error,
    ):
        logger.warning(
            f"User #{user_id}: "
            f"{retailer.name} product data not found: "
            f"{error}"
        )

        send_message(
            chat_id,
            "❌ I couldn't find product information "
            "on that page.\n\n"
            "Check the URL and try again."
        )

        return True

    if isinstance(
        error,
        retailer.scraper_error,
    ):
        logger.warning(
            f"User #{user_id}: "
            f"{retailer.name} scraper failure: "
            f"{error}"
        )

        send_message(
            chat_id,
            f"⚠️ I couldn't retrieve that "
            f"{retailer.name} product right now.\n\n"
            "Try again later."
        )

        return True

    return False


# ==================================================
# CHECK AND CREATE WATCH
# ==================================================


def check_and_create_watch(
    chat_id,
    user_id,
    url,
    target_price,
):
    retailer = get_retailer(url)

    if retailer is None:
        send_message(
            chat_id,
            "❌ I don't support that retailer yet."
        )

        return

    send_message(
        chat_id,
        "🔎 Checking the product..."
    )

    try:
        product = scrape_product(url)

    except Exception as error:

        if handle_scrape_error(
            chat_id,
            user_id,
            retailer,
            error,
        ):
            return

        logger.exception(
            f"User #{user_id}: "
            f"unexpected scraping error"
        )

        send_message(
            chat_id,
            "❌ I couldn't retrieve that product page.\n\n"
            "Please check the URL and try again."
        )

        return

    if product is None:
        send_message(
            chat_id,
            "❌ I couldn't find product information "
            "on that page.\n\n"
            "The page may be temporarily unavailable."
        )

        return

    try:
        watch_id = create_user_watch(
            user_id=user_id,
            retailer_name=retailer.name,
            url=url,
            target_price=target_price,
            product=product,
        )

    except Exception:
        logger.exception(
            f"Failed to create watch for "
            f"user #{user_id}"
        )

        send_message(
            chat_id,
            "❌ I couldn't create that watch.\n\n"
            "Nothing was added. Please try again."
        )

        return

    logger.info(
        f"Watch #{watch_id} created for "
        f"user #{user_id} "
        f"using retailer '{retailer.name}'"
    )

    send_watch_created(
        chat_id=chat_id,
        watch_id=watch_id,
        product=product,
        target_price=target_price,
    )


# ==================================================
# DIRECT /ADD AND /WATCH COMMAND
# ==================================================


def handle_direct_watch(
    chat_id,
    user_id,
    text,
):
    parts = text.split(maxsplit=2)

    if len(parts) != 3:
        send_message(
            chat_id,
            "Usage:\n"
            "/add <product URL> <target price>\n\n"
            "Or simply send:\n"
            "/add\n\n"
            "and I'll guide you through it."
        )

        return

    _, url, target_text = parts

    # --------------------------------------------------
    # TARGET PRICE
    # --------------------------------------------------

    try:
        target_price = float(target_text)

    except ValueError:
        send_message(
            chat_id,
            "❌ Target price must be a number.\n\n"
            "Example:\n"
            "/add https://www.flipkart.com/... 5000"
        )

        return

    if target_price <= 0:
        send_message(
            chat_id,
            "❌ Target price must be greater than zero."
        )

        return

    # --------------------------------------------------
    # RETAILER
    # --------------------------------------------------

    retailer = get_retailer(url)

    if retailer is None:
        send_message(
            chat_id,
            "❌ I don't support that retailer yet."
        )

        return

    check_and_create_watch(
        chat_id=chat_id,
        user_id=user_id,
        url=url,
        target_price=target_price,
    )


# ==================================================
# CONVERSATIONAL ADD
# ==================================================


def start_add(chat_id):
    pending_adds[chat_id] = {
        "stage": "url"
    }

    send_message(
        chat_id,
        "🦅 Let's add a product.\n\n"
        "🔗 Send me the product URL."
    )


def handle_add_url(
    chat_id,
    user_id,
    text,
):
    url = text.strip()

    retailer = get_retailer(url)

    if retailer is None:
        send_message(
            chat_id,
            "❌ I don't support that retailer yet.\n\n"
            "Please send a supported product URL."
        )

        return

    send_message(
        chat_id,
        "🔎 Checking the product..."
    )

    try:
        product = scrape_product(url)

    except Exception as error:

        if handle_scrape_error(
            chat_id,
            user_id,
            retailer,
            error,
        ):
            pending_adds.pop(
                chat_id,
                None,
            )

            return

        logger.exception(
            f"User #{user_id}: "
            f"unexpected scraping error"
        )

        send_message(
            chat_id,
            "❌ I couldn't retrieve that product page.\n\n"
            "Please check the URL and try again."
        )

        pending_adds.pop(
            chat_id,
            None,
        )

        return

    if product is None:
        send_message(
            chat_id,
            "❌ I couldn't find product information "
            "on that page.\n\n"
            "The page may be temporarily unavailable."
        )

        pending_adds.pop(
            chat_id,
            None,
        )

        return

    pending_adds[chat_id] = {
        "stage": "target",
        "url": url,
        "retailer": retailer,
        "product": product,
    }

    send_message(
        chat_id,
        f"📦 {product['name']}\n"
        f"💰 Current price: "
        f"₹{product['price']:,.0f}\n\n"
        f"🎯 What price should I alert you at?"
    )


def handle_add_target(
    chat_id,
    user_id,
    text,
):
    target_text = text.strip()

    try:
        target_price = float(target_text)

    except ValueError:
        send_message(
            chat_id,
            "❌ Please enter a number.\n\n"
            "For example:\n"
            "5000"
        )

        return

    if target_price <= 0:
        send_message(
            chat_id,
            "❌ Target price must be greater than zero."
        )

        return

    pending = pending_adds.get(chat_id)

    if not pending:
        send_message(
            chat_id,
            "❌ There's no product waiting for "
            "a target price.\n\n"
            "Use /add to start again."
        )

        return

    url = pending["url"]
    retailer = pending["retailer"]
    product = pending["product"]

    try:
        watch_id = create_user_watch(
            user_id=user_id,
            retailer_name=retailer.name,
            url=url,
            target_price=target_price,
            product=product,
        )

    except Exception:
        logger.exception(
            f"Failed to create watch for "
            f"user #{user_id}"
        )

        send_message(
            chat_id,
            "❌ I couldn't create that watch.\n\n"
            "Nothing was added. Please try again."
        )

        return

    pending_adds.pop(
        chat_id,
        None,
    )

    logger.info(
        f"Watch #{watch_id} created for "
        f"user #{user_id} "
        f"using retailer '{retailer.name}'"
    )

    send_watch_created(
        chat_id=chat_id,
        watch_id=watch_id,
        product=product,
        target_price=target_price,
    )


# ==================================================
# LIST / WATCHES
# ==================================================


def handle_list(
    chat_id,
    user_id,
):
    watches = get_watches_for_user(user_id)

    if not watches:
        send_message(
            chat_id,
            "🦅 You aren't watching anything yet.\n\n"
            "Use /add to start watching a product."
        )

        return

    lines = [
        "🦅 Your Price Hawk watches:\n"
    ]

    for watch in watches:

        (
            watch_id,
            retailer,
            url,
            product_name,
            target_price,
            current_price,
            currency,
            available,
            alert_active,
            last_checked,
        ) = watch

        current_text = (
            f"₹{current_price:,.0f}"
            if current_price is not None
            else "Unknown"
        )

        if available is True or available == 1:
            availability_text = "In stock"

        elif available is False or available == 0:
            availability_text = "Unavailable"

        else:
            availability_text = "Unknown"

        status = (
            "🟢 Watching"
            if alert_active
            else "🔔 Alert triggered"
        )

        lines.append(
            f"#{watch_id} {product_name}\n"
            f"   🏪 Retailer: {retailer}\n"
            f"   💰 Current: {current_text}\n"
            f"   🎯 Target:  ₹{target_price:,.0f}\n"
            f"   📦 Stock:   {availability_text}\n"
            f"   Status:     {status}\n"
        )

    send_message(
        chat_id,
        "\n".join(lines)
    )


# ==================================================
# HISTORY
# ==================================================


def format_duration(
    started_at,
    ended_at,
):
    from datetime import datetime

    start = datetime.fromisoformat(
        started_at.replace(
            "Z",
            "+00:00",
        )
    )

    if ended_at is None:
        return "currently"

    end = datetime.fromisoformat(
        ended_at.replace(
            "Z",
            "+00:00",
        )
    )

    seconds = int(
        (end - start).total_seconds()
    )

    if seconds < 60:
        return f"{seconds}s"

    minutes = seconds // 60

    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60
    remaining_minutes = minutes % 60

    if remaining_minutes == 0:
        return f"{hours}h"

    return (
        f"{hours}h "
        f"{remaining_minutes}m"
    )


def handle_history(
    chat_id,
    user_id,
    text,
):
    parts = text.split(maxsplit=1)

    if len(parts) != 2:
        send_message(
            chat_id,
            "Usage:\n"
            "/history <watch ID>\n\n"
            "Example:\n"
            "/history 2"
        )

        return

    try:
        watch_id = int(parts[1])

    except ValueError:
        send_message(
            chat_id,
            "❌ Watch ID must be a number."
        )

        return

    watch = get_watch_for_user(
        user_id=user_id,
        watch_id=watch_id,
    )

    if watch is None:
        send_message(
            chat_id,
            f"❌ I couldn't find watch #{watch_id} "
            f"in your watchlist."
        )

        return

    (
        _watch_id,
        retailer,
        url,
        product_name,
        target_price,
        current_price,
        currency,
        available,
        alert_active,
        last_checked,
    ) = watch

    history = get_price_history_for_user(
        user_id=user_id,
        watch_id=watch_id,
        limit=50,
    )

    if not history:
        send_message(
            chat_id,
            f"📈 No price history exists yet for "
            f"watch #{watch_id}."
        )

        return

    prices = [
        row[1]
        for row in history
    ]

    lowest_price = min(prices)
    highest_price = max(prices)

    lines = [
        "🦅 PRICE HISTORY",
        "",
        f"📦 {product_name}",
        "",
        (
            f"💰 Current: "
            f"₹{current_price:,.0f}"
            if current_price is not None
            else "💰 Current: Unknown"
        ),
        f"🎯 Target: "
        f"₹{target_price:,.0f}",
        "",
        "━━━━━━━━━━━━━━━━",
    ]

    for (
        interval_id,
        price,
        started_at,
        ended_at,
    ) in reversed(history):

        duration = format_duration(
            started_at,
            ended_at,
        )

        lines.append(
            f"₹{price:,.0f}  •  {duration}"
        )

    lines.extend([
        "━━━━━━━━━━━━━━━━",
        "",
        f"📉 Lowest:  ₹{lowest_price:,.0f}",
        f"📈 Highest: ₹{highest_price:,.0f}",
    ])

    send_message(
        chat_id,
        "\n".join(lines)
    )


# ==================================================
# MANUAL PRICE CHECK
# ==================================================


def handle_price(
    chat_id,
    user_id,
    text,
):
    parts = text.split(maxsplit=1)

    if len(parts) != 2:
        send_message(
            chat_id,
            "Usage:\n"
            "/price <watch ID>\n\n"
            "Example:\n"
            "/price 2"
        )

        return

    try:
        watch_id = int(parts[1])

    except ValueError:
        send_message(
            chat_id,
            "❌ Watch ID must be a number."
        )

        return

    # --------------------------------------------------
    # VERIFY OWNERSHIP
    # --------------------------------------------------

    watch = get_watch_for_user(
        user_id=user_id,
        watch_id=watch_id,
    )

    if watch is None:
        send_message(
            chat_id,
            f"❌ I couldn't find watch #{watch_id} "
            f"in your watchlist."
        )

        return

    (
        _watch_id,
        retailer,
        url,
        product_name,
        target_price,
        current_price,
        currency,
        available,
        alert_active,
        last_checked,
    ) = watch

    # --------------------------------------------------
    # START CHECK
    # --------------------------------------------------

    send_message(
        chat_id,
        "🔎 Checking the latest price..."
    )

    logger.info(
        f"User #{user_id} requested manual "
        f"price check for watch #{watch_id}"
    )

    # --------------------------------------------------
    # BUILD CHECKER WATCH
    # --------------------------------------------------
    #
    # get_watch_for_user() returns 10 fields.
    #
    # checker.check_watch() expects the 12-field
    # get_all_active_watches() format:
    #
    # id
    # user_id
    # retailer
    # url
    # product_id
    # product_name
    # target_price
    # current_price
    # currency
    # available
    # alert_active
    # last_checked
    #

    watch_for_checker = (
        watch_id,
        user_id,
        retailer,
        url,
        None,
        product_name,
        target_price,
        current_price,
        currency,
        available,
        alert_active,
        last_checked,
    )

    # --------------------------------------------------
    # RUN SHARED CHECKER
    # --------------------------------------------------

    try:
        result = check_watch(
            watch_for_checker
        )

    except Exception:
        logger.exception(
            f"Manual price check failed for "
            f"watch #{watch_id}"
        )

        send_message(
            chat_id,
            "❌ Something went wrong while "
            "checking that product."
        )

        return

    # --------------------------------------------------
    # HANDLE FAILURE
    # --------------------------------------------------

    if not result["success"]:

        error_type = result["error"]

        if error_type == "blocked":
            message = (
                "⚠️ The retailer blocked the request.\n\n"
                "Try again later."
            )

        elif error_type == "product_not_found":
            message = (
                "❌ I couldn't find product "
                "information on that page."
            )

        elif error_type in (
            "scraper_error",
            "no_product",
        ):
            message = (
                "❌ I couldn't retrieve the "
                "latest price.\n\n"
                "Please try again later."
            )

        elif error_type == "unsupported_retailer":
            message = (
                "❌ I don't support that retailer yet."
            )

        else:
            message = (
                "❌ I couldn't complete the "
                "price check.\n\n"
                "Please try again later."
            )

        send_message(
            chat_id,
            message
        )

        return

    # --------------------------------------------------
    # SUCCESS
    # --------------------------------------------------

    new_price = result["price"]
    new_currency = result["currency"]
    new_available = result["available"]
    previous_price = result["previous_price"]

    if previous_price is None:

        price_change_text = (
            "📊 First recorded price"
        )

    elif new_price < previous_price:

        price_change_text = (
            f"📉 Down from "
            f"₹{previous_price:,.0f}"
        )

    elif new_price > previous_price:

        price_change_text = (
            f"📈 Up from "
            f"₹{previous_price:,.0f}"
        )

    else:

        price_change_text = (
            "➡️ Price unchanged"
        )

    availability_text = (
        "In stock"
        if new_available
        else "Currently unavailable"
    )

    target_status = (
        "🎯 AT OR BELOW TARGET"
        if new_price <= target_price
        else "🎯 Above target"
    )

    send_message(
        chat_id,
        f"🦅 LATEST PRICE\n\n"
        f"📦 {product_name}\n\n"
        f"💰 Current: ₹{new_price:,.0f}\n"
        f"{price_change_text}\n"
        f"{target_status}\n"
        f"📦 Availability: "
        f"{availability_text}\n\n"
        f"Your target: ₹{target_price:,.0f}"
    )


# ==================================================
# REMOVE
# ==================================================


def handle_remove(
    chat_id,
    user_id,
    text,
):
    parts = text.split(maxsplit=1)

    if len(parts) != 2:
        send_message(
            chat_id,
            "Usage:\n"
            "/remove <watch ID>\n\n"
            "Example:\n"
            "/remove 2"
        )

        return

    try:
        watch_id = int(parts[1])

    except ValueError:
        send_message(
            chat_id,
            "❌ Watch ID must be a number.\n\n"
            "Example: /remove 2"
        )

        return

    deleted = delete_watch(
        user_id,
        watch_id,
    )

    if deleted:

        logger.info(
            f"Watch #{watch_id} deleted by "
            f"user #{user_id}"
        )

        send_message(
            chat_id,
            f"🗑️ Watch #{watch_id} removed."
        )

    else:

        send_message(
            chat_id,
            f"❌ I couldn't find watch #{watch_id} "
            f"in your watchlist."
        )


# ==================================================
# CANCEL
# ==================================================


def handle_cancel(chat_id):
    if chat_id in pending_adds:

        pending_adds.pop(
            chat_id,
            None,
        )

        send_message(
            chat_id,
            "🛑 Cancelled."
        )

    else:

        send_message(
            chat_id,
            "Nothing is currently in progress."
        )


# ==================================================
# MAIN BOT LOOP
# ==================================================


def main():
    initialize_database()

    logger.info(
        "🟢 Price Hawk bot started."
    )

    offset = None

    while True:

        try:
            data = get_updates(offset)

        except requests.RequestException:
            logger.exception(
                "Telegram polling request failed"
            )

            continue

        if not data.get("ok"):
            logger.error(
                f"Telegram returned an error: "
                f"{data}"
            )

            continue

        for update in data["result"]:

            offset = (
                update["update_id"] + 1
            )

            message = update.get(
                "message"
            )

            if not message:
                continue

            chat = message["chat"]

            chat_id = chat["id"]

            first_name = chat.get(
                "first_name"
            )

            user_id = get_or_create_user(
                telegram_chat_id=chat_id,
                name=first_name,
            )

            text = message.get(
                "text",
                ""
            ).strip()

            if not text:
                continue

            logger.info(
                f"Received message from "
                f"user #{user_id}: {text}"
            )

            # --------------------------------------------------
            # GLOBAL COMMANDS
            # --------------------------------------------------

            if text == "/start":

                pending_adds.pop(
                    chat_id,
                    None,
                )

                send_message(
                    chat_id,
                    "🦅 Price Hawk is alive!\n\n"
                    "I watch product prices and "
                    "alert you when they hit your target.\n\n"
                    "Use /help to see what I can do."
                )

                continue

            if text == "/help":

                send_help(chat_id)

                continue

            if text == "/cancel":

                handle_cancel(chat_id)

                continue

            # --------------------------------------------------
            # REMOVE
            # --------------------------------------------------

            if text.startswith("/remove"):

                handle_remove(
                    chat_id,
                    user_id,
                    text,
                )

                continue

            # --------------------------------------------------
            # LIST / WATCHES
            # --------------------------------------------------

            if text in (
                "/list",
                "/watches",
            ):

                handle_list(
                    chat_id,
                    user_id,
                )

                continue

            # --------------------------------------------------
            # HISTORY
            # --------------------------------------------------

            if text.startswith("/history"):

                handle_history(
                    chat_id,
                    user_id,
                    text,
                )

                continue

            # --------------------------------------------------
            # MANUAL PRICE
            # --------------------------------------------------

            if text.startswith("/price"):

                handle_price(
                    chat_id,
                    user_id,
                    text,
                )

                continue

            # --------------------------------------------------
            # ADD / WATCH
            # --------------------------------------------------

            if text == "/add":

                start_add(chat_id)

                continue

            if text.startswith("/add "):

                handle_direct_watch(
                    chat_id,
                    user_id,
                    text,
                )

                continue

            if text.startswith("/watch"):

                handle_direct_watch(
                    chat_id,
                    user_id,
                    text,
                )

                continue

            # --------------------------------------------------
            # CONVERSATIONAL STATE
            # --------------------------------------------------

            pending = pending_adds.get(
                chat_id
            )

            if pending:

                stage = pending.get(
                    "stage"
                )

                if stage == "url":

                    handle_add_url(
                        chat_id,
                        user_id,
                        text,
                    )

                    continue

                if stage == "target":

                    handle_add_target(
                        chat_id,
                        user_id,
                        text,
                    )

                    continue

            # --------------------------------------------------
            # UNKNOWN COMMAND
            # --------------------------------------------------

            send_message(
                chat_id,
                "I don't know that command yet.\n\n"
                "Try /help."
            )


# ==================================================
# ENTRY POINT
# ==================================================


if __name__ == "__main__":
    main()