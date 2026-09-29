"""Unit tests for the on-demand price fetcher's extraction logic.

Covers the JSON-LD parsing paths (top-level objects, lists, @graph nesting,
URI-typed @type), robust amount parsing (currency symbols/prefixes/comma
grouping), the intentional EGP default, and the meta/visible-text fallbacks.
"""

import pytest

from services.api.price_fetcher import (
    _extract_from_html,
    _jsonld_product,
    _parse_amount,
    _parse_jsonld,
)


def _page_with_jsonld(payload: str) -> str:
    return (
        "<html><head>"
        f'<script type="application/ld+json">{payload}</script>'
        "</head><body>content</body></html>"
    )


# --------------------------------------------------------------------------- #
#  _parse_jsonld                                                               #
# --------------------------------------------------------------------------- #


class TestParseJsonld:
    def test_single_object(self):
        html = _page_with_jsonld('{"@type": "Product"}')
        objs = _parse_jsonld(html)
        assert len(objs) == 1
        assert objs[0]["@type"] == "Product"

    def test_list_of_objects(self):
        html = _page_with_jsonld('[{"@type": "WebSite"}, {"@type": "Product"}]')
        objs = _parse_jsonld(html)
        assert len(objs) == 2

    def test_invalid_json_is_skipped(self):
        html = _page_with_jsonld("{not valid json")
        assert _parse_jsonld(html) == []

    def test_empty_blocks_are_skipped(self):
        html = (
            "<html><head><script type='application/ld+json'>   </script></head></html>"
        )
        assert _parse_jsonld(html) == []

    def test_multiple_blocks(self):
        html = (
            "<html><head>"
            '<script type="application/ld+json">{"@type": "A"}</script>'
            '<script type="application/ld+json">[{"@type": "B"}]</script>'
            "</head></html>"
        )
        objs = _parse_jsonld(html)
        assert {o["@type"] for o in objs} == {"A", "B"}

    def test_no_jsonld(self):
        assert _parse_jsonld("<html><body>plain</body></html>") == []


# --------------------------------------------------------------------------- #
#  _jsonld_product                                                             #
# --------------------------------------------------------------------------- #


class TestJsonldProduct:
    def test_top_level_product(self):
        html = _page_with_jsonld('{"@type": "Product", "name": "X"}')
        prod = _jsonld_product(html)
        assert prod is not None and prod["name"] == "X"

    def test_product_nested_in_graph(self):
        html = _page_with_jsonld(
            '{"@context": "https://schema.org", "@graph": ['
            '{"@type": "WebSite"}, {"@type": "Product", "name": "In Graph"}'
            "]}"
        )
        prod = _jsonld_product(html)
        assert prod is not None and prod["name"] == "In Graph"

    def test_uri_typed_product(self):
        html = _page_with_jsonld(
            '{"@type": "https://schema.org/Product", "name": "URI"}'
        )
        prod = _jsonld_product(html)
        assert prod is not None and prod["name"] == "URI"

    def test_type_as_list(self):
        html = _page_with_jsonld('{"@type": ["Thing", "Product"], "name": "List"}')
        prod = _jsonld_product(html)
        assert prod is not None and prod["name"] == "List"

    def test_non_product_ignored(self):
        html = _page_with_jsonld('{"@type": "WebPage", "name": "Nope"}')
        assert _jsonld_product(html) is None

    def test_no_jsonld(self):
        assert _jsonld_product("<html></html>") is None


# --------------------------------------------------------------------------- #
#  _parse_amount                                                               #
# --------------------------------------------------------------------------- #


class TestParseAmount:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (129999.0, 129999.0),
            (5, 5.0),
            ("129999.00", 129999.0),
            ("129,999", 129999.0),
            ("1,299.50", 1299.5),
            ("129,999 EGP", 129999.0),
            ("EGP 1,299.50", 1299.5),
            ("£ 450", 450.0),
        ],
    )
    def test_parses(self, raw, expected):
        assert _parse_amount(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "abc", "EGP", 0, -5])
    def test_rejects(self, raw):
        assert _parse_amount(raw) is None


# --------------------------------------------------------------------------- #
#  _extract_from_html                                                          #
# --------------------------------------------------------------------------- #


class TestExtractFromHtml:
    def test_full_product_page(self):
        html = _page_with_jsonld(
            '{"@type": "Product", "name": "GPU", '
            '"image": "https://img.com/gpu.jpg", '
            '"offers": {"@type": "Offer", "price": "129999.00", '
            '"priceCurrency": "EGP"}}'
        )
        price, currency, title, image = _extract_from_html(html)
        assert (price, currency, title, image) == (
            129999.0,
            "EGP",
            "GPU",
            "https://img.com/gpu.jpg",
        )

    def test_missing_price_currency_defaults_to_egp(self):
        html = _page_with_jsonld('{"@type": "Product", "offers": {"price": 450}}')
        price, currency, _, _ = _extract_from_html(html)
        assert (price, currency) == (450.0, "EGP")

    def test_price_string_with_currency_suffix(self):
        html = _page_with_jsonld(
            '{"@type": "Product", "offers": '
            '{"price": "129,999 EGP", "priceCurrency": "EGP"}}'
        )
        price, currency, _, _ = _extract_from_html(html)
        assert (price, currency) == (129999.0, "EGP")

    def test_offers_as_list(self):
        html = _page_with_jsonld(
            '{"@type": "Product", "offers": [ {"price": null}, '
            '{"price": "899", "priceCurrency": "USD"} ]}'
        )
        price, currency, _, _ = _extract_from_html(html)
        assert (price, currency) == (899.0, "USD")

    def test_image_as_list_of_objects(self):
        html = _page_with_jsonld(
            '{"@type": "Product", "image": '
            '[{"url": "https://img.com/1.jpg"}, "https://img.com/2.jpg"], '
            '"offers": {"price": 10}}'
        )
        _, _, _, image = _extract_from_html(html)
        assert image == "https://img.com/1.jpg"

    def test_meta_tag_fallback(self):
        html = (
            "<html><head>"
            '<meta property="og:price:amount" content="45,000.00">'
            '<meta property="og:title" content="Meta Title">'
            '<meta property="og:image" content="https://img.com/m.jpg">'
            "</head><body></body></html>"
        )
        price, currency, title, image = _extract_from_html(html)
        assert (price, currency, title, image) == (
            45000.0,
            "EGP",
            "Meta Title",
            "https://img.com/m.jpg",
        )

    def test_visible_text_fallback_english(self):
        html = "<html><body><span>Price: 129,999 EGP</span></body></html>"
        price, currency, title, image = _extract_from_html(html)
        assert (price, currency) == (129999.0, "EGP")
        assert title is None and image is None

    def test_visible_text_fallback_arabic(self):
        html = "<html><body><span>السعر: 129,999 جنيه</span></body></html>"
        price, currency, _, _ = _extract_from_html(html)
        assert (price, currency) == (129999.0, "EGP")

    def test_no_price_returns_none(self):
        html = "<html><body>no prices here</body></html>"
        assert _extract_from_html(html) is None

    def test_zero_top_level_price_does_not_shadow_offer(self):
        html = _page_with_jsonld(
            '{"@type": "Product", "price": 0, '
            '"offers": {"price": "899", "priceCurrency": "USD"}}'
        )
        price, currency, _, _ = _extract_from_html(html)
        assert (price, currency) == (899.0, "USD")

    def test_negative_top_level_price_does_not_shadow_offer(self):
        html = _page_with_jsonld(
            '{"@type": "Product", "price": -5, "offers": {"price": 12}}'
        )
        price, currency, _, _ = _extract_from_html(html)
        assert (price, currency) == (12.0, "EGP")

    def test_non_string_price_currency_ignored(self):
        html = _page_with_jsonld(
            '{"@type": "Product", "priceCurrency": 42, "offers": {"price": 10}}'
        )
        _, currency, _, _ = _extract_from_html(html)
        assert currency == "EGP"

    def test_visible_text_small_decimal(self):
        html = "<html><body><span>Price: 0.99 EGP</span></body></html>"
        price, currency, _, _ = _extract_from_html(html)
        assert (price, currency) == (0.99, "EGP")

    def test_graph_product_beats_meta(self):
        html = (
            "<html><head>"
            '<script type="application/ld+json">{"@graph": [{"@type": "Product", '
            '"name": "From Graph", "offers": {"price": "500", '
            '"priceCurrency": "EGP"}}]}</script>'
            '<meta property="og:price:amount" content="999,999">'
            "</head><body></body></html>"
        )
        price, currency, title, _ = _extract_from_html(html)
        # JSON-LD is authoritative: 500 from the graph product, not 999,999.
        assert (price, currency, title) == (500.0, "EGP", "From Graph")
