import time

from logger import get_logger


logger = get_logger("retry")


def scrape_with_retry(
    scrape_function,
    url,
    attempts=3,
    delays=(0, 2, 5),
    blocked_error=Exception,
    product_not_found_error=Exception,
    scraper_error=Exception,
):
    last_error = None

    for attempt in range(attempts):

        if attempt > 0:
            delay = delays[
                min(attempt, len(delays) - 1)
            ]

            logger.info(
                f"Retrying scrape in "
                f"{delay} seconds "
                f"(attempt {attempt + 1}/{attempts})..."
            )

            time.sleep(delay)

        try:
            return scrape_function(url)

        except blocked_error:
            # A retailer explicitly blocked us.
            # Retrying is pointless.
            raise

        except product_not_found_error:
            # The page loaded, but product data wasn't found.
            # Retrying won't necessarily help.
            raise

        except scraper_error as error:

            last_error = error

            logger.warning(
                f"Scrape attempt "
                f"{attempt + 1}/{attempts} failed: "
                f"{error}"
            )

    raise last_error