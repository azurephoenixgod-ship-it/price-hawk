import time

from checker import run_check_cycle
from logger import get_logger


CHECK_INTERVAL_SECONDS = 120

logger = get_logger("scheduler")


def main():
    logger.info(
        "🦅 Price Hawk scheduler started."
    )

    logger.info(
        f"⏱️ Target interval: "
        f"{CHECK_INTERVAL_SECONDS} seconds."
    )

    next_run = time.monotonic()

    while True:

        try:

            logger.info(
                "🔎 Starting price check..."
            )

            run_check_cycle()

        except Exception:

            logger.exception(
                "Check cycle failed"
            )

        next_run += CHECK_INTERVAL_SECONDS

        sleep_for = (
            next_run - time.monotonic()
        )

        if sleep_for > 0:

            logger.info(
                f"💤 Next check in "
                f"{sleep_for:.1f} seconds..."
            )

            time.sleep(sleep_for)

        else:

            logger.warning(
                "Check cycle took longer than "
                "the target interval."
            )

            # Reset the schedule rather than
            # attempting to catch up with a pile
            # of missed checks.
            next_run = time.monotonic()


if __name__ == "__main__":
    main()