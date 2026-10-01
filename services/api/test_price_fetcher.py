"""Unit tests for the on-demand price fetcher's extraction logic.

Covers the JSON-LD parsing paths (top-level objects, lists, @graph nesting,
URI-typed @type), robust amount parsing (currency symbols/prefixes/comma
grouping), the intentional EGP default, the meta/visible-text fallbacks,
image cascades with URL absolutization, WooCommerce markup, fetch-status
classification, and end-to-end extraction on saved real pages.
"""

import os

import pytest

from services.api.price_fetcher import (
    FETCH_BLOCKED,
    FETCH_FAILED,
    FETCH_NO_PRICE,
    FETCH_OK,
    _absolutize,
    _extract_from_html,
    _extract_image_from_imgs,
    _extract_image_from_meta,
    _extract_woocommerce_price,
    _jsonld_product,
    _looks_like_bot_wall,
    _parse_amount,
    _parse_jsonld,
    _url_candidates,
    fetch_price,
    fetch_price_sync,
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


# --------------------------------------------------------------------------- #
#  New: URL absolutization, image cascades, WooCommerce, classification       #
# --------------------------------------------------------------------------- #

_FIXTURES = os.path.join(os.path.dirname(__file__), "test_fixtures")


def _fixture(name: str) -> str:
    with open(os.path.join(_FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


class TestAbsolutize:
    def test_empty_page_url_returns_input(self):
        assert _absolutize("https://a.com/x.jpg", "") == "https://a.com/x.jpg"

    def test_relative_path_resolved(self):
        assert (
            _absolutize("/cdn/shop/x.jpg", "https://store.com/products/p")
            == "https://store.com/cdn/shop/x.jpg"
        )

    def test_protocol_relative_inherits_page_scheme(self):
        assert (
            _absolutize("//cdn.store.com/x.jpg", "https://store.com/p")
            == "https://cdn.store.com/x.jpg"
        )
        assert (
            _absolutize("//cdn.store.com/x.jpg", "http://store.com/p")
            == "http://cdn.store.com/x.jpg"
        )

    def test_http_asset_upgraded_on_https_page(self):
        assert (
            _absolutize("http://img.store.com/x.jpg", "https://store.com/p")
            == "https://img.store.com/x.jpg"
        )

    def test_absolute_http_kept_on_http_page(self):
        assert (
            _absolutize("http://img.store.com/x.jpg", "http://store.com/p")
            == "http://img.store.com/x.jpg"
        )

    def test_blank_returns_none(self):
        assert _absolutize(None, "https://a.com") is None
        assert _absolutize("   ", "https://a.com") is None


class TestExtractImageFromMeta:
    def test_og_image(self):
        html = '<meta property="og:image" content="https://a.com/x.jpg">'
        assert _extract_image_from_meta(html, "") == "https://a.com/x.jpg"

    def test_secure_url_preferred(self):
        html = (
            '<meta property="og:image" content="http://a.com/insecure.jpg">'
            '<meta property="og:image:secure_url" content="https://a.com/secure.jpg">'
        )
        assert _extract_image_from_meta(html, "https://store.com") == (
            "https://a.com/secure.jpg"
        )

    def test_twitter_fallback(self):
        html = '<meta name="twitter:image" content="https://a.com/t.jpg">'
        assert _extract_image_from_meta(html, "") == "https://a.com/t.jpg"

    def test_relative_og_image_absolutized(self):
        html = '<meta property="og:image" content="/cdn/x.jpg">'
        assert (
            _extract_image_from_meta(html, "https://store.com/p")
            == "https://store.com/cdn/x.jpg"
        )

    def test_no_image_meta(self):
        assert _extract_image_from_meta("<html></html>", "") is None


class TestExtractImageFromImgs:
    def test_skips_logos_and_svg(self):
        html = (
            '<img src="/assets/logo.png" alt="logo">'
            '<img src="https://cdn.com/brand.svg" alt="brand">'
            '<img src="https://cdn.com/product-1.jpg" alt="Product">'
        )
        assert (
            _extract_image_from_imgs(html, "https://store.com/p")
            == "https://cdn.com/product-1.jpg"
        )

    def test_data_uri_skipped(self):
        html = '<img src="data:image/png;base64,AAA"><img src="/a.jpg">'
        assert _extract_image_from_imgs(html, "https://store.com/p") == (
            "https://store.com/a.jpg"
        )

    def test_no_imgs(self):
        assert _extract_image_from_imgs("<html></html>", "") is None


class TestExtractWooCommercePrice:
    def test_standard_markup(self):
        html = (
            '<span class="woocommerce-Price-amount amount">'
            "<bdi><span class=\"woocommerce-Price-currencySymbol\">EGP </span>"
            "2,450.00</bdi></span>"
        )
        price, currency = _extract_woocommerce_price(html)
        assert (price, currency) == (2450.0, "EGP")

    def test_usd_symbol(self):
        html = (
            '<span class="woocommerce-Price-amount amount">'
            '<bdi><span class="woocommerce-Price-currencySymbol">$</span>99.90</bdi>'
            "</span>"
        )
        price, currency = _extract_woocommerce_price(html)
        assert (price, currency) == (99.9, "USD")

    def test_no_markup(self):
        assert _extract_woocommerce_price("<html></html>") == (None, None)

    def test_markup_without_number(self):
        html = '<span class="woocommerce-Price-amount amount">Call us</span>'
        assert _extract_woocommerce_price(html) == (None, None)


class TestUrlCandidates:
    def test_https_url_single_candidate(self):
        assert _url_candidates("https://a.com/p") == ["https://a.com/p"]

    def test_http_url_https_first(self):
        assert _url_candidates("http://a.com/p") == [
            "https://a.com/p",
            "http://a.com/p",
        ]


class TestLooksLikeBotWall:
    def test_cloudflare_521_page_is_wall(self):
        assert _looks_like_bot_wall(_fixture("alfrensia_bot_wall.html")) is True

    def test_real_product_page_is_not_wall(self):
        assert _looks_like_bot_wall(_fixture("compumarts_product.html")) is False

    def test_large_page_never_wall(self):
        assert _looks_like_bot_wall("x" * 60_000) is False


class TestJsonldProductMainEntity:
    def test_bootstrap_main_entity_layout(self):
        html = _page_with_jsonld(
            '{"@type": "WebPage", "mainEntity": '
            '{"@type": "Product", "name": "ME", '
            '"offers": {"price": "100", "priceCurrency": "EGP"}}}'
        )
        from services.api.price_fetcher import _jsonld_product

        prod = _jsonld_product(html)
        assert prod is not None and prod["name"] == "ME"

    def test_graph_inside_graph(self):
        html = _page_with_jsonld(
            '{"@graph": [{"@graph": [{"@type": "Product", "name": "Deep"}]}]}'
        )
        from services.api.price_fetcher import _jsonld_product

        prod = _jsonld_product(html)
        assert prod is not None and prod["name"] == "Deep"


class TestFixtureExtraction:
    """End-to-end extraction against saved real pages."""

    def test_real_shopify_product_page_price_and_image(self):
        html = _fixture("compumarts_product.html")
        page_url = "https://www.compumarts.com/lenovo-r27qe-monitor"
        price, currency, title, image = _extract_from_html(html, page_url)
        assert price is not None and price > 0
        assert currency == "EGP"
        assert "Legion" in title
        # The image must be an absolute HTTPS URL the app can load directly.
        assert image is not None
        assert image.startswith("https://")
        assert "/cdn/shop/" in image

    def test_woocommerce_fixture_price_and_relative_image(self):
        html = _fixture("woocommerce_product.html")
        page_url = "https://alfrensia.com/product/baguette-maker"
        price, currency, title, image = _extract_from_html(html, page_url)
        assert (price, currency) == (2450.0, "EGP")
        assert title == "French Baguette Maker | Alfrensia"
        # Relative og:image resolved against the page URL.
        assert (
            image
            == "https://alfrensia.com/wp-content/uploads/2025/09/baguette-maker.jpg"
        )

    def test_relative_og_image_fixture(self):
        html = _fixture("relative_og_image.html")
        page_url = "https://example-store.com/products/widget"
        price, currency, title, image = _extract_from_html(html, page_url)
        assert (price, currency) == (12500.0, "EGP")
        assert title == "Widget"
        # Protocol-relative image inherits the page's https scheme.
        assert image == "https://cdn.example-store.com/products/widget.jpg"

    def test_bot_wall_fixture_yields_no_price(self):
        html = _fixture("alfrensia_bot_wall.html")
        assert _extract_from_html(html, "https://alfrensia.com/product/x") is None


class TestFetchPriceClassification:
    """fetch_price with mocked fetchers (no network in tests)."""

    def _patch(self, monkeypatch, requests_result, playwright_result=None):
        from services.api import price_fetcher as pf

        monkeypatch.setattr(
            pf, "_fetch_html_requests", lambda url, timeout=30: requests_result
        )
        monkeypatch.setattr(
            pf,
            "_fetch_html_playwright",
            lambda url, timeout_ms=25000: playwright_result,
        )

    def test_ok_with_price(self, monkeypatch):
        self._patch(
            monkeypatch,
            ('<html><body><span>Price: 100 EGP</span></body></html>', None),
        )
        result = fetch_price("https://store.com/p")
        assert result.status == FETCH_OK
        assert result.price is not None
        assert result.price.price_local == 100.0

    def test_http_url_tries_https_first(self, monkeypatch):
        from services.api import price_fetcher as pf

        seen = []

        def fake_requests(url, timeout=30):
            seen.append(url)
            return (None, "request error: SSLError")

        monkeypatch.setattr(pf, "_fetch_html_requests", fake_requests)
        monkeypatch.setattr(
            pf, "_fetch_html_playwright", lambda url, timeout_ms=25000: None
        )

        result = fetch_price("http://store.com/p")
        assert seen == ["https://store.com/p", "http://store.com/p"]
        assert result.status == FETCH_FAILED

    def test_blocked_on_521(self, monkeypatch):
        self._patch(monkeypatch, (None, "HTTP 521"))
        result = fetch_price("https://alfrensia.com/product/x")
        assert result.status == FETCH_BLOCKED
        assert "521" in result.reason

    def test_failed_on_network_error(self, monkeypatch):
        self._patch(monkeypatch, (None, "request error: ConnectTimeout"))
        result = fetch_price("https://store.com/p")
        assert result.status == FETCH_FAILED
        assert "ConnectTimeout" in result.reason

    def test_no_price_found_on_plain_page(self, monkeypatch):
        self._patch(
            monkeypatch,
            ("<html><body>This is my portfolio, no prices here.</body></html>", None),
        )
        result = fetch_price("https://example.com/portfolio")
        assert result.status == FETCH_NO_PRICE

    def test_blocked_on_bot_wall_page(self, monkeypatch):
        self._patch(monkeypatch, (_fixture("alfrensia_bot_wall.html"), None))
        result = fetch_price("https://alfrensia.com/product/x")
        assert result.status == FETCH_BLOCKED

    def test_playwright_fallback_used_when_requests_fail(self, monkeypatch):
        self._patch(
            monkeypatch,
            (None, "request error: ConnectTimeout"),
            "<html><body><span>Price: 55 EGP</span></body></html>",
        )
        result = fetch_price("https://store.com/p")
        assert result.status == FETCH_OK
        assert result.price.price_local == 55.0

    def test_fetch_price_sync_never_raises(self, monkeypatch):
        from services.api import price_fetcher as pf

        def boom(url, timeout=30):
            raise RuntimeError("boom")

        monkeypatch.setattr(pf, "_fetch_html_requests", boom)
        monkeypatch.setattr(pf, "_fetch_html_playwright", boom)
        result = fetch_price_sync("https://store.com/p")
        assert result.status == FETCH_FAILED
