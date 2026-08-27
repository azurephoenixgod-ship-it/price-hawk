from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Retailer:
    name: str
    domains: tuple[str, ...]
    get_product: Callable
    blocked_error: type[Exception]
    product_not_found_error: type[Exception]
    scraper_error: type[Exception]


_RETAILERS = []


def register_retailer(retailer: Retailer):
    _RETAILERS.append(retailer)


def get_retailer(url: str) -> Retailer | None:
    normalized_url = url.lower()

    for retailer in _RETAILERS:
        for domain in retailer.domains:
            if domain in normalized_url:
                return retailer

    return None


def get_all_retailers():
    return tuple(_RETAILERS)