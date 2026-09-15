"""Store-aware affiliate URL generation and redirect validation."""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

STORE_HOSTS = {
    "amazon_eg": {"amazon.eg", "www.amazon.eg"},
    "noon_eg": {"noon.com", "www.noon.com"},
    "jumia_eg": {"jumia.com.eg", "www.jumia.com.eg"},
}


def _affiliate_tag(store_id: str) -> str:
    env_names = {
        "amazon_eg": "AMAZON_AFFILIATE_TAG",
        "noon_eg": "NOON_AFFILIATE_TAG",
        "jumia_eg": "JUMIA_AFFILIATE_TAG",
    }
    return os.getenv(env_names.get(store_id, ""), "").strip()


def _host_allowed(store_id: str, hostname: str) -> bool:
    return hostname.lower().rstrip(".") in STORE_HOSTS.get(store_id, set())


def build_affiliate_url(store_id: str, target_url: str) -> str:
    """Return an affiliate URL for a supported merchant URL.

    URLs without a configured merchant tag are returned unchanged so local
    development and scraping continue to work without affiliate credentials.
    """
    parsed = urlparse(target_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("target_url must be an HTTP or HTTPS URL")
    if not _host_allowed(store_id, parsed.hostname):
        raise ValueError("target_url does not belong to the selected store")

    tag = _affiliate_tag(store_id)
    if not tag:
        return target_url

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if store_id == "amazon_eg":
        query["tag"] = tag
    else:
        query["utm_source"] = "el72"
        query["utm_medium"] = "affiliate"
        query["utm_campaign"] = tag

    return urlunparse(parsed._replace(query=urlencode(query)))


def store_for_url(target_url: str) -> str:
    """Return the supported store ID for a merchant URL."""
    parsed = urlparse(target_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("target_url must be an HTTP or HTTPS URL")
    for store_id in STORE_HOSTS:
        if _host_allowed(store_id, parsed.hostname):
            return store_id
    raise ValueError("target_url host is not an allowed merchant")
