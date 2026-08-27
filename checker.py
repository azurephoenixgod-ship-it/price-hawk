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
from retry import scrape_with_retry


load_dotenv()

logger = get_logger("checker")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ==================================================
# HELPERS
# ==================================================


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


# ==================================================
# CHECK RESULT
# ==================================================


def make_success_result(
    price,
    currency,
    available,
    previous_price,
):
    return {
        "success": True,
        "price": price,
        "currency": currency,
        "available": available,
        "previous_price": previous_price,
    }


def make_failure_result(
    error_type,
    message,
):
    return {
        "success": False,
        "error": error_type,
        "message": message,
    }


# ==================================================
# WATCH CHECK
# ==================================================


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

            product = scrape_with_retry(
                get_product,
                url,
            )

        else:

            message = (
                f"Unsupported retailer "
                f"'{retailer}'"
            )

            logger.warning(
                f"Watch #{watch_id}: "
                f"{message}"
            )

            return make_failure_result(
                error_type="unsupported_retailer",
                message=message,
            )

    except FlipkartBlockedError as error:

        logger.warning(
            f"Watch #{watch_id}: "
            f"Flipkart blocked the request: "
            f"{error}"
        )

        return make_failure_result(
            error_type="blocked",
            message=str(error),
        )

    except FlipkartProductNotFoundError as error:

        logger.warning(
            f"Watch #{watch_id}: "
            f"product data not found: "
            f"{error}"
        )

        return make_failure_result(
            error_type="product_not_found",
            message=str(error),
        )

    except FlipkartScraperError as error:

        logger.warning(
            f"Watch #{watch_id}: "
            f"scraper failure: "
            f"{error}"
        )

        return make_failure_result(
            error_type="scraper_error",
            message=str(error),
        )

    except Exception as error:

        logger.exception(
            f"Watch #{watch_id}: "
            f"unexpected scraper error"
        )

        return make_failure_result(
            error_type="unexpected_error",
            message=str(error),
        )

    if product is None:

        message = (
            "Scraper returned no product."
        )

        logger.warning(
            f"Watch #{watch_id}: "
            f"{message}"
        )

        return make_failure_result(
            error_type="no_product",
            message=message,
        )

    # --------------------------------------------------
    # PRODUCT DATA
    # --------------------------------------------------

    new_price = product["price"]
    new_currency = product["currency"]
    new_available = product["available"]

    previous_price = current_price

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

        # Keep local state correct for the
        # target-alert check below.
        alert_active = 1

    # --------------------------------------------------
    # TARGET ALERT
    # --------------------------------------------------

    if (
        new_price <= target_price
        and alert_active
    ):

        chat_id = get_telegram_chat_id(
            user_id
        )

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

    # --------------------------------------------------
    # RETURN RESULT
    # --------------------------------------------------

    return make_success_result(
        price=new_price,
        currency=new_currency,
        available=new_available,
        previous_price=previous_price,
    )


# ==================================================
# CHECK ALL ACTIVE WATCHES
# ==================================================


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


# ==================================================
# ENTRY POINT
# ==================================================


if __name__ == "__main__":
    run_check_cycle()