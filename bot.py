import os

import requests
from dotenv import load_dotenv

from database import (
    initialize_database,
    get_or_create_user,
    create_watch,
    get_watches_for_user,
    delete_watch,
)

from retailers import get_retailer

from retry import scrape_with_retry
from logger import get_logger


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

        "/remove <watch ID>\n"
        "Remove one of your watches.\n\n"

        "/cancel\n"
        "Cancel the current operation.\n\n"

        "/help\n"
        "Show this help message."
    )


# ==================================================
# PRODUCT SCRAPING
# ==================================================

def scrape_product(url):

    retailer = get_retailer(url)

    if retailer is None:

        raise ValueError(
            "Unsupported retailer"
        )

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

    except retailer.blocked_error as error:

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

        return

    except retailer.product_not_found_error as error:

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

        return

    except retailer.scraper_error as error:

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

        return

    except ValueError as error:

        logger.warning(
            f"User #{user_id}: "
            f"{error}"
        )

        send_message(
            chat_id,
            "❌ I don't recognize that retailer."
        )

        return

    except Exception as error:

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

    watch_id = create_user_watch(
        user_id=user_id,
        retailer_name=retailer.name,
        url=url,
        target_price=target_price,
        product=product,
    )

    send_watch_created(
        chat_id=chat_id,
        watch_id=watch_id,
        product=product,
        target_price=target_price,
    )


# ==================================================
# DIRECT WATCH COMMAND
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

    except retailer.blocked_error as error:

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

        pending_adds.pop(chat_id, None)

        return

    except retailer.product_not_found_error as error:

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

        pending_adds.pop(chat_id, None)

        return

    except retailer.scraper_error as error:

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

        pending_adds.pop(chat_id, None)

        return

    except Exception as error:

        logger.exception(
            f"User #{user_id}: "
            f"unexpected scraping error"
        )

        send_message(
            chat_id,
            "❌ I couldn't retrieve that product page.\n\n"
            "Please check the URL and try again."
        )

        pending_adds.pop(chat_id, None)

        return

    if product is None:

        send_message(
            chat_id,
            "❌ I couldn't find product information "
            "on that page.\n\n"
            "The page may be temporarily unavailable."
        )

        pending_adds.pop(chat_id, None)

        return

    pending_adds[chat_id] = {
        "stage": "target",
        "url": url,
        "retailer": retailer,
        "product": product,
    }

    product_name = product["name"]
    current_price = product["price"]

    send_message(
        chat_id,
        f"📦 {product_name}\n"
        f"💰 Current price: "
        f"₹{current_price:,.0f}\n\n"
        f"🎯 What price should I alert you at?"
    )


def handle_add_target(
    chat_id,
    user_id,
    text,
):

    state = pending_adds.get(chat_id)

    if state is None:
        return

    try:

        target_price = float(text.strip())

    except ValueError:

        send_message(
            chat_id,
            "❌ Target price must be a number.\n\n"
            "Example: 5000"
        )

        return

    if target_price <= 0:

        send_message(
            chat_id,
            "❌ Target price must be greater than zero."
        )

        return

    retailer = state["retailer"]
    url = state["url"]
    product = state["product"]

    watch_id = create_user_watch(
        user_id=user_id,
        retailer_name=retailer.name,
        url=url,
        target_price=target_price,
        product=product,
    )

    pending_adds.pop(chat_id, None)

    send_watch_created(
        chat_id=chat_id,
        watch_id=watch_id,
        product=product,
        target_price=target_price,
    )


# ==================================================
# WATCH LIST
# ==================================================

def handle_watches(
    chat_id,
    user_id,
):

    watches = get_watches_for_user(user_id)

    if not watches:

        send_message(
            chat_id,
            "🦅 You aren't watching anything yet.\n\n"
            "Use /add <URL> <target price> "
            "to add a product."
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

        if current_price is not None:

            current_text = (
                f"₹{current_price:,.0f}"
            )

        else:

            current_text = "Unknown"

        target_text = (
            f"₹{target_price:,.0f}"
        )

        status = (
            "🟢 Watching"
            if alert_active
            else "🔔 Alert triggered"
        )

        lines.append(
            f"#{watch_id} {product_name}\n"
            f"   Retailer: {retailer}\n"
            f"   Current: {current_text}\n"
            f"   Target:  {target_text}\n"
            f"   Status:  {status}\n"
        )

    send_message(
        chat_id,
        "\n".join(lines)
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

        send_message(
            chat_id,
            f"🗑️ Watch #{watch_id} removed."
        )

    else:

        send_message(
            chat_id,
            f"❌ I couldn't find watch "
            f"#{watch_id} in your watchlist."
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
            "🦅 Operation cancelled."
        )

    else:

        send_message(
            chat_id,
            "Nothing to cancel."
        )


# ==================================================
# MAIN
# ==================================================

def main():

    initialize_database()

    logger.info(
        "🟢 Price Hawk is running."
    )

    offset = None

    while True:

        try:

            data = get_updates(offset)

            if not data.get("ok"):

                logger.error(
                    f"Telegram error: {data}"
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

                logger.info(
                    f"Received message from "
                    f"user #{user_id}: {text}"
                )

                # ------------------------------------------
                # ACTIVE CONVERSATION
                # ------------------------------------------

                state = pending_adds.get(
                    chat_id
                )

                if state:

                    if text == "/cancel":

                        handle_cancel(
                            chat_id
                        )

                        continue

                    if state["stage"] == "url":

                        handle_add_url(
                            chat_id,
                            user_id,
                            text,
                        )

                        continue

                    if state["stage"] == "target":

                        handle_add_target(
                            chat_id,
                            user_id,
                            text,
                        )

                        continue

                # ------------------------------------------
                # COMMANDS
                # ------------------------------------------

                if text == "/start":

                    send_message(
                        chat_id,
                        "🦅 Price Hawk is alive!\n\n"
                        "Use /help to see what I can do."
                    )

                elif text == "/help":

                    send_help(chat_id)

                elif text == "/add":

                    start_add(chat_id)

                elif text.startswith("/add "):

                    handle_direct_watch(
                        chat_id,
                        user_id,
                        text,
                    )

                elif text in (
                    "/watches",
                    "/list",
                ):

                    handle_watches(
                        chat_id,
                        user_id,
                    )

                elif text.startswith("/remove"):

                    handle_remove(
                        chat_id,
                        user_id,
                        text,
                    )

                elif text == "/cancel":

                    handle_cancel(
                        chat_id
                    )

                else:

                    send_message(
                        chat_id,
                        "I don't know that command yet.\n\n"
                        "Try /help."
                    )

        except requests.RequestException:

            logger.exception(
                "Telegram request failed"
            )

        except Exception:

            logger.exception(
                "Unexpected error in main bot loop"
            )


# ==================================================
# ENTRY POINT
# ==================================================

if __name__ == "__main__":
    main()