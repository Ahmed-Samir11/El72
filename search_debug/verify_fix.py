import sys
sys.path.insert(0, "e:/repos/El72")
from services.api.price_fetcher import (
    _extract_price_from_html,
    _jsonld_title,
    _jsonld_image,
    _extract_meta,
)

html = open("search_debug/compumarts_price.html", encoding="utf-8").read()
print("price:", _extract_price_from_html(html))
print("title:", _jsonld_title(html))
print("image:", _jsonld_image(html))
print("og:title:", _extract_meta(html, "og:title"))
print("og:image:", _extract_meta(html, "og:image"))
