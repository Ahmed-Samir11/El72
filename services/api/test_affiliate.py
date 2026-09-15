"""Tests for store-aware affiliate URL generation."""

import pytest

from services.api.affiliate import build_affiliate_url, store_for_url


def test_amazon_tag_is_added(monkeypatch):
    monkeypatch.setenv("AMAZON_AFFILIATE_TAG", "el72-20")

    result = build_affiliate_url(
        "amazon_eg", "https://www.amazon.eg/dp/ABC?ref=search"
    )

    assert "tag=el72-20" in result
    assert "ref=search" in result


def test_noon_campaign_is_added(monkeypatch):
    monkeypatch.setenv("NOON_AFFILIATE_TAG", "noon-demo")

    result = build_affiliate_url("noon_eg", "https://www.noon.com/egypt-en/item")

    assert "utm_source=el72" in result
    assert "utm_medium=affiliate" in result
    assert "utm_campaign=noon-demo" in result


def test_missing_tag_preserves_supported_url(monkeypatch):
    monkeypatch.delenv("JUMIA_AFFILIATE_TAG", raising=False)
    url = "https://www.jumia.com.eg/item?sku=J1"

    assert build_affiliate_url("jumia_eg", url) == url


def test_unsupported_host_is_rejected():
    with pytest.raises(ValueError):
        build_affiliate_url("amazon_eg", "https://evil.example/item")


def test_store_for_url_rejects_open_redirect_target():
    with pytest.raises(ValueError):
        store_for_url("https://evil.example/item")
