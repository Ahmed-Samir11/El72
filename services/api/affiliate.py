"""Store-aware affiliate URL generation and redirect validation."""

from __future__ import annotations

import os
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

STORE_HOSTS = {
    "amazon_eg": {"amazon.eg", "www.amazon.eg"},
    "noon_eg": {"noon.com", "www.noon.com"},
    "jumia_eg": {"jumia.com.eg", "www.jumia.com.eg"},
}

# Per-store affiliate program tag (monetization constants come from env —
# never a global constant). The env contract mirrors .env.example.
AFFILIATE_TAG_ENV_VARS = {
    "amazon_eg": "AMAZON_AFFILIATE_TAG",
    "noon_eg": "NOON_AFFILIATE_TAG",
    "jumia_eg": "JUMIA_AFFILIATE_TAG",
}

# Stable app-surface identifiers for affiliate_clicks.source (report §11: CTR
# must be separable per surface). A value outside this set is recorded as
# 'unknown' rather than dropped: an unknown source is still a click.
VALID_CLICK_SOURCES = frozenset(
    {"deal_feed", "search_result", "tracker_card", "browse", "web", "unknown"}
)


def _affiliate_tag(store_id: str) -> str:
    return os.getenv(AFFILIATE_TAG_ENV_VARS.get(store_id, ""), "").strip()


def tag_presence() -> dict[str, bool]:
    """Per-store affiliate tag presence (env var set and non-blank).

    Consumed by the /affiliate/config admin report and the production startup
    warning: an unconfigured tag means "no revenue path configured", never
    "no traffic" — the click is still logged (build_affiliate_url passes the
    URL through).
    """
    return {
        store_id: bool(_affiliate_tag(store_id)) for store_id in AFFILIATE_TAG_ENV_VARS
    }


def missing_affiliate_tags() -> list[tuple[str, str]]:
    """(store_id, env_var) pairs whose affiliate tag is unset in production."""
    return [
        (store_id, env_name)
        for store_id, env_name in AFFILIATE_TAG_ENV_VARS.items()
        if not _affiliate_tag(store_id)
    ]


def normalize_click_source(source: str | None) -> str:
    """Clamp a client-supplied source to the allowlist.

    The surface label comes from the client, so it is context, not identity:
    anything unrecognized (or absent) becomes 'unknown' — the click stays
    attributable and no caller can inject arbitrary strings into the metric
    dimension.
    """
    value = (source or "").strip().lower()
    return value if value in VALID_CLICK_SOURCES else "unknown"


# Bounded, printable, hostile-free charset for a client-declared category. A
# category is display context (unlike source, it is not an enum the app
# controls), so anything outside this set — markup, scheme-ish or path-like
# tokens, control characters — is dropped to NULL rather than stored and later
# rendered. No slash: a real category label never needs one, while
# 'example.com/path' always has one.
_CATEGORY_RE = re.compile(r"[A-Za-z0-9 ()&,.'+-]{1,100}\Z")


def normalize_category(category: str | None) -> str | None:
    """Clamp a client-supplied category to a safe display string or None.

    Returns the trimmed value when it matches the bounded charset (ASCII
    letters/digits and a small set of separators), otherwise None — so a
    probe with markup or a URL-shaped category cannot pollute the §11
    category dimension. None then lets the server fill the real category
    from its own alerts context.
    """
    value = (category or "").strip()
    return value if value and _CATEGORY_RE.match(value) else None


# Allowlist charset for opaque ids: letters, digits and the punctuation real
# product ids actually use — no colon (scheme), slash (path), '?'/'#' (query).
_OPAQUE_ID_RE = re.compile(r"[A-Za-z0-9._+\-]{1,255}\Z")


def is_opaque_id(value: str | None) -> bool:
    """True when a client-supplied id is an opaque token, not a URL.

    sku/deal_id identify products on the server's own tables; a caller that
    smuggles anything URL-shaped (a scheme, a path, a host with dots, query
    punctuation) into an id field is probing the redirect surface, so the
    request is rejected (400) instead of logged. Allowlisting the charset
    beats blacklisting '://' shapes: 'mailto:x', 'example.com/p' or '//evil'
    are all refused, while real opaque product ids pass.
    """
    if value is None:
        return True
    return _OPAQUE_ID_RE.match(value.strip()) is not None


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
