"""Tests for deterministic product extraction (no network, no LLM)."""

from services.chatbot.extractors import (
    extract_card_products,
    extract_jsonld_products,
    extract_products,
)

_JSONLD_PAGE = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Product",
      "name": "Lenovo LOQ 13900HX RTX 4060",
      "@id": "/d/lenovo-loq-13900hx/p/lenovo-loq",
      "image": ["https://store.example/img/loq.jpg"],
      "offers": {
        "@type": "Offer",
        "priceAmount": 64999,
        "currencyIdentifier": "EGP",
        "isAvailable": true
      }
    },
    {
      "@type": "Product",
      "name": "HP Victus 15",
      "url": "https://store.example/d/hp-victus",
      "image": {"@id": "https://store.example/img/victus.jpg"},
      "aggregateOffer": {"lowestPrice": 55000},
      "offers": {"availability": "OutOfStock"}
    },
    {"@type": "Breadcrumb", "name": "ignored"}
  ]
}
</script>
</head><body>results</body></html>
"""


def test_extract_jsonld_products_reads_graph_offers_and_images():
    """JSON-LD is the primary source: title, link, price, image, stock."""
    products = extract_jsonld_products(_JSONLD_PAGE, base_url="https://store.example")

    assert [p["title"] for p in products] == [
        "Lenovo LOQ 13900HX RTX 4060",
        "HP Victus 15",
    ]
    # Relative "@id" is resolved against the store, absolute "url" is kept.
    assert (
        products[0]["url"] == "https://store.example/d/lenovo-loq-13900hx/p/lenovo-loq"
    )
    assert products[1]["url"] == "https://store.example/d/hp-victus"
    assert products[0]["price"] == 64999.0
    # aggregateOffer.lowestPrice is the "from" price of a variant group.
    assert products[1]["price"] == 55000.0
    assert products[0]["image_url"] == "https://store.example/img/loq.jpg"
    assert products[1]["image_url"] == "https://store.example/img/victus.jpg"
    assert [p["in_stock"] for p in products] == [True, False]


def test_extract_jsonld_products_skips_broken_blocks():
    """Store pages ship malformed JSON-LD; one bad block must not lose the page."""
    html = (
        '<script type="application/ld+json">{broken, json</script>'
        '<script type="application/ld+json">'
        '{"@type": "Product", "name": "Acer Nitro V", "url": "/p/nitro",'
        ' "offers": {"priceAmount": "EGP 55,799"}}'
        "</script>"
    )
    products = extract_jsonld_products(html, base_url="https://store.example")

    assert len(products) == 1
    assert products[0]["title"] == "Acer Nitro V"
    # A price string with a thousands separator still parses.
    assert products[0]["price"] == 55799.0
    assert products[0]["url"] == "https://store.example/p/nitro"


def test_a_product_with_one_available_offer_is_buyable():
    """A variant group is buyable when ANY offer is not out of stock.

    The first size being sold out must not hide a product a user can order.
    """
    html = (
        '<script type="application/ld+json">'
        '{"@context": "https://schema.org", "@type": "Product", '
        '"name": "LG UltraGear 32", "url": "/p/ultragear", '
        '"price": 13999, '
        '"offers": ['
        '{"availability": "OutOfStock", "priceAmount": 13999}, '
        '{"availability": "https://schema.org/InStock", "priceAmount": 13999}'
        "]}</script>"
    )
    products = extract_jsonld_products(html, base_url="https://store.example")

    assert len(products) == 1
    assert products[0]["in_stock"] is True


def test_availability_in_its_other_shapes_is_understood():
    """Stores spell stock as a URL object or a boolean, not only a string."""
    url_object = (
        '{"@type": "Product", "name": "Alien S3", "url": "/p/s3", '
        '"offers": {"availability": {"@id": "https://schema.org/OutOfStock"}}}'
    )
    boolean_flag = (
        '{"@type": "Product", "name": "MSI RTX 5060", "url": "/p/rtx5060", '
        '"offers": {"isAvailable": false}}'
    )

    assert not extract_jsonld_products(_ld(url_object))[0]["in_stock"]
    assert not extract_jsonld_products(_ld(boolean_flag))[0]["in_stock"]


def _ld(payload: str) -> str:
    """Wrap [payload] in the script tag a store page would send."""
    return f'<script type="application/ld+json">{payload}</script>'


_CARD_PAGE = """
<div class="card">
  <a href="/d/asus-tuf-a16/p/asus-tuf">
    <img src="https://store.example/img/tuf.jpg" alt="ASUS TUF A16 Gaming Laptop"/>
  </a>
  <span class="price">EGP 86,500</span>
</div>
<div class="card">
  <a href="/d/acer-vg270/p/acer-vg270">
    <img src="/img/vg270.jpg" alt="Acer VG270 Full HD Monitor"/>
  </a>
  <span class="price">1,299 ج.م</span>
</div>
<div class="card">
  <a href="/d/asus-tuf-a16/p/asus-tuf">duplicate card</a>
  <span class="price">EGP 86,500</span>
</div>
"""


def test_extract_card_products_falls_back_to_link_and_price():
    """Stores without JSON-LD still put link, alt title and price in the HTML."""
    products = extract_card_products(_CARD_PAGE, base_url="https://store.example")

    assert [p["title"] for p in products] == [
        "ASUS TUF A16 Gaming Laptop",
        "Acer VG270 Full HD Monitor",
    ]
    assert products[0]["price"] == 86500.0
    assert products[1]["price"] == 1299.0
    # The duplicate card for the same URL is dropped.
    assert len({p["url"] for p in products}) == 2
    assert products[1]["image_url"] == "/img/vg270.jpg"


def test_extract_products_prefers_jsonld_over_cards():
    """When both parsers find products, the structured one wins."""
    html = (
        '<script type="application/ld+json">'
        '{"@type": "Product", "name": "Lenovo LOQ Laptop", "url": "/loq",'
        ' "offers": {"priceAmount": 64999}}</script>'
        '<a href="/other-laptop">Other Laptop</a> EGP 90,000'
    )
    products = extract_products(html, "laptop", base_url="https://store.example")

    assert [p["title"] for p in products] == ["Lenovo LOQ Laptop"]


def test_extract_products_drops_featured_products_on_empty_page():
    """A no-results page shows "best sellers"; they are not what was asked."""
    html = (
        '<a href="/cpu">AMD Ryzen 5 5600 MPK</a> EGP 5,999 '
        '<a href="/monitor">Acer VG270 Monitor</a> EGP 6,799 '
        '<a href="/ideapad">Lenovo IdeaPad Slim 3 Laptop</a> EGP 45,000'
    )
    products = extract_products(html, "laptop", base_url="https://store.example")

    assert [p["title"] for p in products] == ["Lenovo IdeaPad Slim 3 Laptop"]


def test_extract_products_keeps_everything_when_no_title_matches():
    """A translation miss must not turn a real page into an empty search."""
    html = '<a href="/iphone">iPhone 15 Pro Max</a> EGP 175,000'
    products = extract_products(html, "فones", base_url="https://store.example")

    assert len(products) == 1
    assert products[0]["title"] == "iPhone 15 Pro Max"


def test_extract_products_returns_empty_for_a_page_with_no_products():
    """Empty output is the signal for the caller to try the LLM fallback."""
    html = "<html><body>No results found for that query.</body></html>"
    assert extract_products(html, "laptop") == []
    assert extract_products("", "laptop") == []
