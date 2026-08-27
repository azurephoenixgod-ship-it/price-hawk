import logging
from logging.handlers import RotatingFileHandler
import sys


LOG_FILE = "price_hawk.log"


def get_logger(name="price_hawk"):
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --------------------------------------------------
    # FILE LOGGER
    # --------------------------------------------------

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )

    file_handler.setFormatter(formatter)

    # --------------------------------------------------
    # TERMINAL LOGGER
    # --------------------------------------------------

    # Windows PowerShell may use a legacy encoding.
    # Ask Python to use UTF-8 when possible.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    console_handler = logging.StreamHandler(
        sys.stdout
    )

    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger