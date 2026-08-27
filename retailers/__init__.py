from .registry import (
    Retailer,
    register_retailer,
    get_retailer,
    get_all_retailers,
)

from .flipkart import (
    get_product as flipkart_get_product,
    FlipkartBlockedError,
    FlipkartProductNotFoundError,
    FlipkartScraperError,
)

from .amazon import (
    get_product as amazon_get_product,
    AmazonBlockedError,
    AmazonProductNotFoundError,
    AmazonScraperError,
)


register_retailer(
    Retailer(
        name="flipkart",
        domains=(
            "flipkart.com",
        ),
        get_product=flipkart_get_product,
        blocked_error=FlipkartBlockedError,
        product_not_found_error=FlipkartProductNotFoundError,
        scraper_error=FlipkartScraperError,
    )
)


register_retailer(
    Retailer(
        name="amazon",
        domains=(
            "amazon.in",
        ),
        get_product=amazon_get_product,
        blocked_error=AmazonBlockedError,
        product_not_found_error=AmazonProductNotFoundError,
        scraper_error=AmazonScraperError,
    )
)