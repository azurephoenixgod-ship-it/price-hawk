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
from retailers.flipkart import get_product


load_dotenv()

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_message(chat_id, text):
    response = requests.post(
        f"{BASE_URL}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": text,
        },
        timeout=20,
    )

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

    return response.json()


def handle_watch(chat_id, user_id, text):
    parts = text.split(maxsplit=2)

    if len(parts) != 3:
        send_message(
            chat_id,
            "Usage:\n"
            "/watch <product URL> <target price>\n\n"
            "Example:\n"
            "/watch https://www.flipkart.com/... 5000"
        )
        return

    _, url, target_text = parts

    try:
        target_price = float(target_text)
    except ValueError:
        send_message(
            chat_id,
            "❌ Target price must be a number.\n\n"
            "Example: /watch https://www.flipkart.com/... 5000"
        )
        return

    if target_price <= 0:
        send_message(
            chat_id,
            "❌ Target price must be greater than zero."
        )
        return

    if "flipkart.com" not in url.lower():
        send_message(
            chat_id,
            "❌ I don't support that retailer yet.\n\n"
            "Currently supported: Flipkart"
        )
        return

    send_message(
        chat_id,
        "🔎 Checking the product..."
    )

    try:
        product = get_product(url)
    except Exception as error:
        print("Scraping error:", error)

        send_message(
            chat_id,
            "❌ I couldn't retrieve that product page.\n\n"
            "Please check the URL and try again."
        )
        return

    if product is None:
        send_message(
            chat_id,
            "❌ I couldn't find product information on that page.\n\n"
            "The page may be temporarily unavailable."
        )
        return

    product_name = product["name"]
    current_price = product["price"]
    currency = product["currency"]
    available = product["available"]

    watch_id = create_watch(
        user_id=user_id,
        retailer="flipkart",
        url=url,
        target_price=target_price,
        product_name=product_name,
        current_price=current_price,
        currency=currency,
        available=available,
    )

    availability_text = (
        "In stock" if available else "Currently unavailable"
    )

    send_message(
        chat_id,
        f"🦅 Price Hawk is watching!\n\n"
        f"📦 {product_name}\n"
        f"💰 Current price: ₹{current_price:,.0f}\n"
        f"🎯 Alert below: ₹{target_price:,.0f}\n"
        f"📦 Availability: {availability_text}\n\n"
        f"Watch ID: #{watch_id}"
    )


def handle_list(chat_id, user_id):
    watches = get_watches_for_user(user_id)

    if not watches:
        send_message(
            chat_id,
            "🦅 You aren't watching anything yet.\n\n"
            "Use /watch <URL> <target price> to add a product."
        )
        return

    lines = ["🦅 Your Price Hawk watches:\n"]

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
            current_text = f"₹{current_price:,.0f}"
        else:
            current_text = "Unknown"

        target_text = f"₹{target_price:,.0f}"

        status = (
            "🟢 Watching"
            if alert_active
            else "🔔 Alert triggered"
        )

        lines.append(
            f"#{watch_id} {product_name}\n"
            f"   Current: {current_text}\n"
            f"   Target:  {target_text}\n"
            f"   Status:  {status}\n"
        )

    send_message(
        chat_id,
        "\n".join(lines)
    )


def handle_remove(chat_id, user_id, text):
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

    deleted = delete_watch(user_id, watch_id)

    if deleted:
        send_message(
            chat_id,
            f"🗑️ Watch #{watch_id} removed."
        )
    else:
        send_message(
            chat_id,
            f"❌ I couldn't find watch #{watch_id} in your watchlist."
        )


def main():
    initialize_database()

    print("🟢 Price Hawk is running.")

    offset = None

    while True:
        data = get_updates(offset)

        if not data.get("ok"):
            print("Telegram error:", data)
            continue

        for update in data["result"]:
            offset = update["update_id"] + 1

            message = update.get("message")

            if not message:
                continue

            chat = message["chat"]
            chat_id = chat["id"]

            first_name = chat.get("first_name")

            user_id = get_or_create_user(
                telegram_chat_id=chat_id,
                name=first_name,
            )

            text = message.get("text", "").strip()

            if text == "/start":
                send_message(
                    chat_id,
                    "🦅 Price Hawk is alive!\n\n"
                    "Commands:\n"
                    "/watch <URL> <target price>\n"
                    "/list\n"
                    "/remove <watch ID>"
                )

            elif text == "/list":
                handle_list(
                    chat_id,
                    user_id,
                )

            elif text.startswith("/remove"):
                handle_remove(
                    chat_id,
                    user_id,
                    text,
                )

            elif text.startswith("/watch"):
                handle_watch(
                    chat_id,
                    user_id,
                    text,
                )

            else:
                send_message(
                    chat_id,
                    "I don't know that command yet.\n\n"
                    "Try /start."
                )


if __name__ == "__main__":
    main()