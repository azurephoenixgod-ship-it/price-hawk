from datetime import datetime, timezone
import os

import requests
from dotenv import load_dotenv

from database import (
    initialize_database,
    get_all_active_watches,
    get_telegram_chat_id,
    update_watch_price,
    set_alert_active,
    get_latest_price_interval,
    create_price_interval,
    close_price_interval,
    update_daily_summary,
)

from retailers.flipkart import (
    get_product,
    FlipkartBlockedError,
    FlipkartProductNotFoundError,
    FlipkartScraperError,
)

from logger import get_logger


load_dotenv()

logger = get_logger("checker")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def now():
    return datetime.now(timezone.utc)


def send_message(chat_id, text):
    response = requests.post(
        f"{TELEGRAM_URL}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": text,
        },
        timeout=20,
    )

    response.raise_for_status()

    return response.json()


def check_watch(watch):
    (
        watch_id,
        user_id,
        retailer,
        url,
        product_id,
        product_name,
        target_price,
        current_price,
        currency,
        available,
        alert_active,
        last_checked,
    ) = watch

    logger.info(
        f"Checking watch #{watch_id}: "
        f"{product_name}"
    )

    # --------------------------------------------------
    # SCRAPE
    # --------------------------------------------------

    try:

        if retailer == "flipkart":

            product = get_product(url)

        else:

            logger.warning(
                f"Watch #{watch_id}: "
                f"unsupported retailer "
                f"'{retailer}'"
            )

            return

    except FlipkartBlockedError as error:

        logger.warning(
            f"Watch #{watch_id}: "
            f"Flipkart blocked the request: "
            f"{error}"
        )

        return

    except FlipkartProductNotFoundError as error:

        logger.warning(
            f"Watch #{watch_id}: "
            f"product data not found: "
            f"{error}"
        )

        return

    except FlipkartScraperError as error:

        logger.warning(
            f"Watch #{watch_id}: "
            f"scraper failure: "
            f"{error}"
        )

        return

    except Exception:

        logger.exception(
            f"Watch #{watch_id}: "
            f"unexpected scraper error"
        )

        return

    if product is None:

        logger.warning(
            f"Watch #{watch_id}: "
            f"scraper returned no product"
        )

        return

    # --------------------------------------------------
    # PRODUCT DATA
    # --------------------------------------------------

    new_price = product["price"]
    new_currency = product["currency"]
    new_available = product["available"]

    checked_at = now()
    checked_at_iso = checked_at.isoformat()

    # --------------------------------------------------
    # UPDATE CURRENT STATE
    # --------------------------------------------------

    update_watch_price(
        watch_id=watch_id,
        price=new_price,
        currency=new_currency,
        available=new_available,
        checked_at=checked_at_iso,
    )

    # --------------------------------------------------
    # PRICE INTERVAL
    # --------------------------------------------------

    latest_interval = get_latest_price_interval(
        watch_id
    )

    if latest_interval is None:

        create_price_interval(
            watch_id=watch_id,
            price=new_price,
            started_at=checked_at_iso,
        )

        logger.info(
            f"Watch #{watch_id}: "
            f"initial price recorded at "
            f"₹{new_price:,.0f}"
        )

    else:

        (
            interval_id,
            old_price,
            started_at,
            ended_at,
        ) = latest_interval

        if old_price == new_price:

            logger.info(
                f"Watch #{watch_id}: "
                f"price unchanged at "
                f"₹{new_price:,.0f}"
            )

        else:

            close_price_interval(
                interval_id=interval_id,
                ended_at=checked_at_iso,
            )

            create_price_interval(
                watch_id=watch_id,
                price=new_price,
                started_at=checked_at_iso,
            )

            logger.info(
                f"Watch #{watch_id}: "
                f"price changed from "
                f"₹{old_price:,.0f} "
                f"to ₹{new_price:,.0f}"
            )

    # --------------------------------------------------
    # DAILY SUMMARY
    # --------------------------------------------------

    date = checked_at.date().isoformat()

    update_daily_summary(
        watch_id=watch_id,
        date=date,
        price=new_price,
    )

    # --------------------------------------------------
    # RE-ARM ALERT
    # --------------------------------------------------

    if (
        new_price > target_price
        and not alert_active
    ):

        set_alert_active(
            watch_id=watch_id,
            active=True,
        )

        logger.info(
            f"Watch #{watch_id}: "
            f"price recovered above target; "
            f"alert re-armed"
        )

        alert_active = 1

    # --------------------------------------------------
    # TARGET ALERT
    # --------------------------------------------------

    if (
        new_price <= target_price
        and alert_active
    ):

        chat_id = get_telegram_chat_id(user_id)

        if chat_id is None:

            logger.warning(
                f"Watch #{watch_id}: "
                f"no Telegram chat ID found"
            )

        else:

            try:

                send_message(
                    chat_id,
                    f"🚨 PRICE ALERT!\n\n"
                    f"📦 {product_name}\n\n"
                    f"💰 Current price: "
                    f"₹{new_price:,.0f}\n"
                    f"🎯 Your target: "
                    f"₹{target_price:,.0f}\n\n"
                    f"🔗 {url}"
                )

                logger.info(
                    f"🚨 Alert sent for "
                    f"watch #{watch_id}"
                )

                set_alert_active(
                    watch_id=watch_id,
                    active=False,
                )

            except requests.RequestException:

                logger.exception(
                    f"Watch #{watch_id}: "
                    f"Telegram request failed"
                )


def run_check_cycle():
    initialize_database()

    watches = get_all_active_watches()

    logger.info(
        f"Found {len(watches)} active watch(es)."
    )

    for watch in watches:

        try:

            check_watch(watch)

        except Exception:

            watch_id = watch[0]

            logger.exception(
                f"Watch #{watch_id}: "
                f"unexpected check error"
            )


if __name__ == "__main__":
    run_check_cycle()