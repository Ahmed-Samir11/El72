"""On-demand price fetcher.

Visits a single product URL and extracts the price, currency, title and
image. Tries a plain HTTP fetch first (fast, no browser), then falls back
to headless Chromium for JS-rendered or bot-protected pages.

Every outcome is **classified** (see ``FetchResult.status``) so callers —
and ultimately the app — can tell "no price found (not a product page?)"
apart from "bot-blocked / server down" from "network failure", instead of
treating all failures as one silent timeout.

Extraction strategy is deterministic (JSON-LD → meta → store markup →
visible text); there is intentionally no LLM/agent involved.

Lifecycle: :func:`fetch_price` calls are **serialized** on a module-level
lock. That is deliberate: the connect-time DNS guard temporarily wraps
``socket.getaddrinfo`` (thread-global) so only one fetch may run at a
time, and serialization bounds headless-Chromium launches to one at a
time (each launch is expensive; a burst of tracker additions must not
spawn a browser per item). Fetches are network-bound and user-driven
(low frequency), so the queue cost is negligible.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import logging
import re
import socket
import threading
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import urljoin, urlsplit

logger = logging.getLogger(__name__)

# 1 EGP = 0.032 USD (approximate; matches services.scraper.price_processor).
EGP_TO_USD = 0.032

# Fetch statuses — persisted to tracked_item_stores.last_fetch_status.
FETCH_OK = "ok"
FETCH_NO_PRICE = "no_price_found"
FETCH_BLOCKED = "blocked"
FETCH_FAILED = "fetch_failed"

# Server-side block/unavailability: Cloudflare challenge codes plus the
# origin-error range (520-524) plus standard 5xx availability errors.
_BLOCKED_HTTP_CODES = {
    "403",
    "429",
    "500",
    "502",
    "503",
    "504",
    "520",
    "521",
    "522",
    "523",
    "524",
}


@dataclass
class FetchedPrice:
    price_local: float
    currency: str
    title: Optional[str] = None
    image_url: Optional[str] = None
    in_stock: bool = True


@dataclass
class FetchResult:
    """Classified outcome of a price fetch.

    ``status`` is one of FETCH_OK / FETCH_NO_PRICE / FETCH_BLOCKED /
    FETCH_FAILED; ``reason`` is a short, log-safe explanation for non-OK
    results; ``price`` is set only when ``status == FETCH_OK``.
    """

    status: str
    reason: str = ""
    price: Optional[FetchedPrice] = None


def _is_blocked_ip(ip: str) -> bool:
    """True if [ip] must never be fetched (SSRF protection).

    Blocks loopback, private (RFC1918 + ULA), link-local (including the
    169.254.169.254 cloud-metadata address), multicast, reserved and
    unspecified ranges — for both IPv4 and IPv6, including IPv4-mapped
    IPv6 forms such as ``::ffff:127.0.0.1``.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable → refuse
    # IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1): Python marks the entire
    # ::ffff:0:0/96 range as private, so judge the mapped IPv4 address
    # directly instead — before the generic checks below.
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        return mapped.is_loopback or mapped.is_private or mapped.is_link_local
    return any(
        (
            addr.is_loopback,
            addr.is_private,
            addr.is_link_local,
            addr.is_multicast,
            addr.is_reserved,
            addr.is_unspecified,
        ),
    )


class _BlockedAddressError(ValueError):
    """A connect-time DNS resolution returned a non-public address."""


@contextlib.contextmanager
def _connect_time_ssrf_guard():
    """Re-validate DNS at connect time (closes the DNS-rebinding TOCTOU).

    :func:`_validate_public_url` resolves the host once before the fetch;
    an attacker domain could answer with a public IP then and a private one
    at connect time. While the fetch runs, ``socket.getaddrinfo`` is wrapped
    so **every** resolution (requests resolves at connect time) is checked,
    and any blocked IP fails the connection instead of completing it.
    """
    original = socket.getaddrinfo

    def guarded(host, port, *args, **kwargs):
        results = original(host, port, *args, **kwargs)
        for info in results:
            if _is_blocked_ip(info[4][0]):
                raise _BlockedAddressError("non-public address at connect time")
        return results

    socket.getaddrinfo = guarded
    try:
        yield
    finally:
        socket.getaddrinfo = original


# Serializes fetch_price (see module docstring): keeps the connect-time
# DNS guard's thread-global socket patching safe and bounds concurrent
# headless-Chromium launches to one.
_FETCH_LOCK = threading.Lock()


def _validate_public_url(url: str) -> None:
    """Raise :class:`ValueError` unless [url] is a fetchable public URL.

    Enforced before any user-supplied URL is fetched (SSRF protection):
    only http/https, and every IP the host resolves to must be public —
    loopback, private, link-local (cloud metadata), multicast, reserved and
    unspecified addresses are refused. DNS is resolved here so obfuscated
    hosts (decimal/octal IP literals) are caught; the follow-up fetch is
    additionally wrapped in :func:`_connect_time_ssrf_guard` so a DNS
    rebinding answer at connect time is refused too.
    """
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise ValueError(f"malformed URL: {exc}") from exc
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError(f"scheme not allowed: {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise ValueError("missing host")
    try:
        infos = socket.getaddrinfo(
            host, parts.port or (443 if parts.scheme.lower() == "https" else 80)
        )
    except socket.gaierror as exc:
        raise ValueError(f"unresolvable host: {exc}") from exc
    except ValueError as exc:
        # Invalid port etc. surfaced by urlsplit/getaddrinfo — report it
        # uniformly as a rejected URL.
        raise ValueError(f"malformed URL: {exc}") from exc
    for info in infos:
        ip = info[4][0]
        if _is_blocked_ip(ip):
            raise ValueError("host resolves to a non-public address")


def _safe_fetch_error(reason: Optional[str], limit: int = 200) -> Optional[str]:
    """Sanitize a fetch reason before it is persisted / exposed via the API.

    Reasons are already short fixed strings (HTTP codes, exception class
    names, fixed messages), but this is the single boundary that guarantees
    nothing longer or non-printable ever reaches the client.
    """
    if reason is None:
        return None
    cleaned = "".join(ch if ch.isprintable() else " " for ch in str(reason)).strip()
    return cleaned[:limit] or None


def _to_usd(price: float, currency: str) -> float:
    return (
        round(price * EGP_TO_USD, 4) if currency.upper() == "EGP" else round(price, 4)
    )


def _parse_jsonld(html: str) -> list:
    """Return the parsed JSON-LD objects (dicts) embedded in the page."""
    blocks = re.findall(
        r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    objs: list = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, list):
            objs.extend(d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            objs.append(data)
    return objs


def _type_is_product(types) -> bool:
    """True if any ``@type`` entry denotes a schema.org Product.

    Accepts plain names ("Product") and full URIs
    ("https://schema.org/Product"), case-insensitively.
    """
    for t in types:
        if not isinstance(t, str):
            continue
        tail = t.rsplit("/", 1)[-1].lower()
        if tail == "product":
            return True
    return False


def _jsonld_product(html: str, objs: Optional[list] = None) -> Optional[dict]:
    """Return the schema.org ``Product`` JSON-LD object, if present.

    Scans top-level objects, entries nested in ``@graph`` (one extra
    nesting level), and ``mainEntity`` references (the Bootstrap-schema
    layout). Matches ``@type`` as a plain name or URI. Pass pre-parsed
    ``objs`` to avoid re-parsing the page.
    """
    if objs is None:
        objs = _parse_jsonld(html)
    candidates: list = []
    for obj in objs:
        candidates.append(obj)
        _add_main_entity(candidates, obj)
        graph = obj.get("@graph")
        if isinstance(graph, list):
            for g in graph:
                if not isinstance(g, dict):
                    continue
                candidates.append(g)
                _add_main_entity(candidates, g)
                sub = g.get("@graph")
                if isinstance(sub, list):
                    candidates.extend(d for d in sub if isinstance(d, dict))
    for obj in candidates:
        t = obj.get("@type")
        types = t if isinstance(t, list) else [t]
        if _type_is_product(types):
            return obj
    return None


def _add_main_entity(candidates: list, obj: dict) -> None:
    """Append ``mainEntity`` (dict or list of dicts) from [obj] to [candidates]."""
    me = obj.get("mainEntity")
    if isinstance(me, dict):
        candidates.append(me)
    elif isinstance(me, list):
        candidates.extend(d for d in me if isinstance(d, dict))


def _parse_amount(raw) -> Optional[float]:
    """Parse a price value that may be numeric or a messy string.

    Handles ints/floats and strings containing currency symbols,
    prefixes, or comma grouping (e.g. ``"129,999 EGP"``,
    ``"EGP 1,299.50"``). Returns ``None`` for missing/non-positive values.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        m = re.search(r"(\d[\d,]*(?:\.\d+)?)", str(raw))
        if not m:
            return None
        try:
            value = float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return value if value > 0 else None


def _first_image_url(image) -> Optional[str]:
    """First usable URL from a JSON-LD ``image`` value (str, list, or dict).

    Inline ``data:`` URIs are not usable by the app's ``Image.network`` and
    are rejected (the next cascade level wins).
    """
    candidates: list = []
    if isinstance(image, str):
        candidates.append(image)
    elif isinstance(image, list):
        for entry in image:
            if isinstance(entry, str):
                candidates.append(entry)
            elif isinstance(entry, dict) and isinstance(entry.get("url"), str):
                candidates.append(entry["url"])
    elif isinstance(image, dict) and isinstance(image.get("url"), str):
        candidates.append(image["url"])
    for cand in candidates:
        if not cand.strip().lower().startswith(("data:", "javascript:")):
            return cand
    return None


def _absolutize(url: Optional[str], page_url: str) -> Optional[str]:
    """Resolve [url] to an absolute HTTPS/HTTP URL against [page_url].

    Handles relative paths (``/cdn/shop/x.jpg``), protocol-relative URLs
    (``//cdn.shop/x.jpg``) and upgrades ``http://`` assets to ``https://``
    when the page itself was served over HTTPS (Android blocks cleartext).
    Returns ``None`` for missing/blank input; returns the URL unchanged if
    [page_url] is empty (e.g. in unit tests).
    """
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    if url.lower().startswith(("data:", "javascript:")):
        # Not network-loadable; treat as missing so the next cascade level
        # (or the placeholder) is used instead.
        return None
    if url.startswith("//"):
        scheme = "https:" if page_url.startswith("https") else "http:"
        url = scheme + url
    elif not url.lower().startswith(("http://", "https://")):
        if page_url:
            url = urljoin(page_url, url)
    if page_url.startswith("https") and url.lower().startswith("http://"):
        url = "https://" + url[len("http://") :]
    return url or None


_OG_IMAGE_PROPS = (
    "og:image:secure_url",
    "og:image",
    "twitter:image",
    "twitter:image:src",
)

_IMG_SKIP_HINTS = (
    "logo",
    "icon",
    "flag",
    "sprite",
    "spacer",
    "pixel",
    "badge",
    "avatar",
    ".svg",
    "data:",
)


def _extract_image_from_meta(html: str, page_url: str) -> Optional[str]:
    """First usable image from OG/Twitter meta tags, absolutized."""
    for prop in _OG_IMAGE_PROPS:
        value = _extract_meta(html, prop)
        if value:
            return _absolutize(value, page_url)
    return None


def _best_srcset_url(srcset: str) -> Optional[str]:
    """Largest-declared image from a ``srcset`` attribute, else None.

    Entries look like ``"url 800w"``, ``"url 2x"`` or a bare ``"url"``. The
    entry with the largest declared width/density wins (the plan: prefer the
    largest resolution when the page offers several).
    """
    best: Optional[Tuple[float, str]] = None
    for entry in srcset.split(","):
        parts = entry.strip().split()
        if not parts:
            continue
        url = parts[0]
        weight = 0.0
        if len(parts) > 1:
            descriptor = parts[1]
            try:
                if descriptor.endswith("w"):
                    weight = float(descriptor[:-1])
                elif descriptor.endswith("x"):
                    weight = float(descriptor[:-1]) * 1000.0
            except ValueError:
                pass
        if best is None or weight > best[0]:
            best = (weight, url)
    return best[1] if best else None


def _extract_image_from_imgs(html: str, page_url: str) -> Optional[str]:
    """First plausible product image from ``<img>`` tags, absolutized.

    Last-resort fallback: skips obvious non-product assets (logos, icons,
    flags, sprites, inline data-URIs, SVGs) by URL heuristics. When an img
    carries a ``srcset`` (multiple resolutions), the largest declared entry
    is preferred over ``src``.
    """
    for tag in re.findall(r"<img[^>]+>", html, re.IGNORECASE):
        srcset = re.search(r'\bsrcset=["\']([^"\']+)["\']', tag, re.IGNORECASE)
        candidates: list = []
        if srcset:
            best = _best_srcset_url(srcset.group(1))
            if best:
                candidates.append(best)
        m = re.search(r'\bsrc=["\']([^"\']+)["\']', tag, re.IGNORECASE)
        if m and m.group(1).strip():
            candidates.append(m.group(1).strip())
        for url in candidates:
            if not url:
                continue
            low = url.lower()
            if low.startswith("data:") or any(h in low for h in _IMG_SKIP_HINTS):
                continue
            return _absolutize(url, page_url)
    return None


def _extract_woocommerce_price(html: str) -> Tuple[Optional[float], Optional[str]]:
    """(price, currency) from WooCommerce price markup, else (None, None).

    WooCommerce renders the price as::

        <span class="woocommerce-Price-amount amount">
          <bdi><span class="woocommerce-Price-currencySymbol">EGP </span>1,299.00</bdi>
        </span>

    which the visible-text regex misses when the currency marker is not
    textually adjacent to the amount. On sale pages (``<del>`` old +
    ``<ins>`` new) the *last* occurrence holds the current price, so the
    last parseable match wins.
    """
    result: Tuple[Optional[float], Optional[str]] = (None, None)
    for m in re.finditer(r'class="woocommerce-Price-amount[^"]*"[^>]*>', html):
        # The amount follows the currency-symbol span inside <bdi>; a bounded
        # window avoids reaching into unrelated markup.
        window = html[m.end() : m.end() + 300]
        sym = re.search(r'woocommerce-Price-currencySymbol[^>]*>([^<]+)<', window)
        after = window[sym.end() :] if sym else window
        num = re.search(r"(\d[\d,]*(?:\.\d+)?)", after)
        if not num:
            continue
        price = _parse_amount(num.group(1))
        currency = "EGP"
        if sym:
            s = sym.group(1).strip()
            if s.upper() in ("USD", "$"):
                currency = "USD"
            else:
                tok = re.search(r"[A-Za-z]{3}", s)
                if tok:
                    currency = tok.group(0).upper()
        if price is not None:
            result = (price, currency)
    return result


def _jsonld_offer_price(
    prod: dict,
) -> Tuple[Optional[float], Optional[str], Optional[str], Optional[str]]:
    """(price, currency, title, image) from a Product JSON-LD node.

    The first parseable price candidate wins (top-level ``price`` before
    offers): a missing/zero/negative top-level price must not shadow a valid
    offer price.
    """
    currency = prod.get("priceCurrency")
    if not isinstance(currency, str):
        currency = None
    title = prod.get("name")
    if not isinstance(title, str):
        title = None
    image_url = _first_image_url(prod.get("image"))

    offers = prod.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    elif not isinstance(offers, list):
        offers = []
    price_candidates: list = [prod.get("price")]
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        if offer.get("price") is not None:
            price_candidates.append(offer["price"])
        if currency is None and isinstance(offer.get("priceCurrency"), str):
            currency = offer["priceCurrency"]

    price = next(
        (v for v in map(_parse_amount, price_candidates) if v is not None),
        None,
    )
    return price, currency, title, image_url


def _extract_from_html(
    html: str, page_url: str = ""
) -> Optional[tuple[float, str, Optional[str], Optional[str]]]:
    """Best-effort extraction of ``(price, currency, title, image_url)``.

    Tries, in order:
    1. The schema.org ``Product``/``Offer`` JSON-LD values (authoritative).
    2. OpenGraph / product meta price tags.
    3. WooCommerce price markup.
    4. A regex over visible text for an EGP amount.

    Image cascade: JSON-LD ``image`` → OG/Twitter meta → ``<img>`` scan.
    All image URLs are resolved to absolute (see :func:`_absolutize`).

    Returns ``(price, currency, title, image_url)`` or ``None`` if no price
    could be determined.
    """
    objs = _parse_jsonld(html)
    prod = _jsonld_product(html, objs)

    price: Optional[float] = None
    currency: Optional[str] = None
    title: Optional[str] = None
    image_url: Optional[str] = None

    # 1. schema.org Product/Offer JSON-LD.
    if prod is not None:
        price, currency, title, image_url = _jsonld_offer_price(prod)

    if price is None:
        # 2. Meta tags.
        meta = re.search(
            r'<meta[^>]+(?:property|name)=["\'](?:og:price:amount|product:price:amount|price)["\'][^>]+content=["\']([\d,]+(?:\.\d+)?)',
            html,
            re.IGNORECASE,
        )
        if meta:
            price = _parse_amount(meta.group(1))

    if price is None:
        # 3. WooCommerce markup.
        woocommerce_price, woocommerce_currency = _extract_woocommerce_price(html)
        if woocommerce_price is not None:
            price = woocommerce_price
            if currency is None:
                currency = woocommerce_currency

    if price is None:
        # 4. Visible-text fallback: a number followed by an EGP marker.
        text = re.sub(r"<[^>]+>", " ", html)
        m = re.search(
            r"(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:EGP|ج\.م|جنيه|£|pound)",
            text,
            re.IGNORECASE,
        )
        if m:
            price = _parse_amount(m.group(1))

    if price is None:
        return None

    # Title fallback (JSON-LD takes precedence).
    if title is None:
        title = _extract_meta(html, "og:title")

    # Image fallbacks (JSON-LD takes precedence), then normalize whatever we
    # found to an absolute URL the app can load directly.
    if image_url is None:
        image_url = _extract_image_from_meta(html, page_url)
    if image_url is None:
        image_url = _extract_image_from_imgs(html, page_url)
    if image_url is not None and page_url:
        image_url = _absolutize(image_url, page_url)

    # The app targets the Egyptian market; pages that omit priceCurrency
    # are assumed to quote EGP.
    return price, (currency or "EGP"), title, image_url


def _extract_meta(html: str, prop: str) -> Optional[str]:
    """Extract a meta tag's content value by property/name (og:title etc.)."""
    m = re.search(
        r'<meta[^>]+(?:property|name)=["\']'
        + re.escape(prop)
        + r'["\'][^>]+content=["\']([^"\']*)',
        html,
        re.IGNORECASE,
    )
    return m.group(1) if m else None


def _looks_like_bot_wall(html: str) -> bool:
    """Heuristic: a very small page that is a challenge/wall, not a product.

    Cloudflare challenge/5xx landing pages and thin bot-walls are typically
    well under 50 KB. Signals, checked in priority order:

    1. **Challenge markers** win outright: Cloudflare/Turnstile tokens,
       "Just a moment", captcha, access-denied phrasing. This fixes the
       earlier gap where a block page quoting the words "product"/"price" in
       boilerplate slipped through as a product page.
    2. **Strong product markers** (JSON-LD, OG price/image, WooCommerce
       price markup, EGP/جنيه amounts) mean a real page — even a minimal
       one.
    3. Otherwise the legacy word check ("product"/"price") keeps thin real
       pages — and user-mislinked plain pages such as a portfolio —
       classified as "no price found", which is the actionable answer for
       both.

    A page under 50 KB with none of the above is a wall.
    """
    if len(html) > 50_000:
        return False
    low = html.lower()
    challenge_markers = (
        "cf-chl",
        "challenge-platform",
        "challenge-running",
        "turnstile",
        "captcha",
        "just a moment",
        "are you a robot",
        "access denied",
        "attention required",
        "unusual traffic",
        "error 1015",
        "error 521",
        "web server is down",
    )
    if any(marker in low for marker in challenge_markers):
        return True
    product_markers = (
        "ld+json",
        "og:image",
        "og:price",
        "product:price",
        "woocommerce-price",
        "price__current",
        "product",
        "price",
        "egp",
        "جنيه",
    )
    return not any(marker in low for marker in product_markers)


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _url_candidates(url: str) -> list:
    """Fetch-order candidates for [url].

    For non-secure ``http://`` links the HTTPS upgrade is tried **first**
    (many stores redirect or block cleartext); the original URL is the
    fallback. Scheme comparison is case-insensitive.
    """
    if url.lower().startswith("http://"):
        return ["https://" + url[len("http://") :], url]
    return [url]


def _fetch_html_requests(
    url: str, timeout: int = 30, max_redirects: int = 5
) -> Tuple[Optional[str], Optional[str]]:
    """Fetch page HTML with a standard browser User-Agent.

    Returns ``(html, None)`` on success or ``(None, reason)`` on any
    failure — the reason is a short log-safe string such as ``"HTTP 521"``.

    Redirects are followed **manually** so every hop's target is re-validated
    by :func:`_validate_public_url` — a public domain that 302s to an
    internal address is refused (redirect-based SSRF).
    """
    try:
        import requests
    except ImportError:
        return None, "requests not installed"
    current = url
    try:
        # Re-validate DNS at connect time (DNS-rebinding protection); the
        # guard raises ValueError if the OS resolves a blocked IP while
        # connecting.
        with _connect_time_ssrf_guard():
            for _ in range(max_redirects + 1):
                try:
                    r = requests.get(
                        current,
                        headers=_HEADERS,
                        timeout=timeout,
                        allow_redirects=False,
                    )
                except _BlockedAddressError:
                    raise  # connect-time SSRF guard signal — re-raised below
                except Exception as exc:  # noqa: BLE001
                    logger.warning("requests fetch failed for %s: %s", current, exc)
                    return None, f"request error: {type(exc).__name__}"
                if r.status_code in (301, 302, 303, 307, 308):
                    location = r.headers.get("Location")
                    if not location:
                        return None, f"HTTP {r.status_code}"
                    target = urljoin(current, location)
                    try:
                        _validate_public_url(target)
                    except ValueError:
                        logger.warning(
                            "Blocked redirect to %s from %s", target, current
                        )
                        return None, "blocked: redirect to non-public address"
                    current = target
                    continue
                if r.status_code == 200:
                    return r.text, None
                logger.warning("HTTP %s fetching %s", r.status_code, current)
                return None, f"HTTP {r.status_code}"
            return None, "too many redirects"
    except ValueError:
        return None, "blocked: non-public address at connect time"


# JS predicate for Playwright: true once a price indicator is in the DOM.
# JS stores render prices late; waiting for this (capped at 8s) is more
# reliable than a blind sleep and no longer when static content suffices.
_PRICE_INDICATOR_JS = """
() => {
  return document.querySelector(
    'script[type="application/ld+json"], '
    '.woocommerce-Price-amount, '
    '[class*="price"], '
    'meta[property="og:price:amount"], '
    'meta[property="product:price:amount"]'
  ) !== null;
}
"""


def _fetch_html_playwright(url: str, timeout_ms: int = 25000) -> Optional[str]:
    """Fetch page HTML via headless Chromium (JS-rendered pages).

    Returns ``None`` on failure.

    Runs with ``--no-sandbox``/``--disable-dev-shm-usage`` (Chromium's
    sandbox fails in the container API image). SSRF: a route guard aborts
    navigations to non-public URLs, and the target host's DNS is pinned to
    its validated IP via ``--host-resolver-rules`` so the browser process
    cannot be DNS-rebound either.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright not installed; skipping browser fallback")
        return None
    try:
        logger.info("Launching Playwright browser for %s", url)
        launch_args = ["--no-sandbox", "--disable-dev-shm-usage"]
        # Pin the target host's DNS to its validated IP (DNS-rebinding
        # protection inside the browser process). Skipped for IP-literal
        # hosts (nothing to rebind).
        _host = urlsplit(url).hostname
        if _host:
            try:
                ipaddress.ip_address(_host)
            except ValueError:
                try:
                    _port = 443 if urlsplit(url).scheme.lower() == "https" else 80
                    _ip = socket.getaddrinfo(_host, _port)[0][4][0]
                    if not _is_blocked_ip(_ip):
                        launch_args.append(f"--host-resolver-rules=MAP {_host} {_ip}")
                except (socket.gaierror, ValueError):
                    pass
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=launch_args)
            try:
                context = browser.new_context(user_agent=_HEADERS["User-Agent"])

                def _ssrf_guard(route):
                    # Attacker-controlled pages can also fire subresource
                    # requests (fetch/XHR/image) at internal addresses from
                    # inside the browser — so EVERY request type is
                    # validated, not just main-frame navigations.
                    target = route.request.url
                    try:
                        _validate_public_url(target)
                    except ValueError:
                        logger.warning("Blocked browser request to %s", target)
                        return route.abort()
                    return route.continue_()

                context.route("**/*", _ssrf_guard)
                page = context.new_page()
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                # Wait (capped) for a price indicator instead of a blind
                # sleep; non-fatal when the page is static or blocked.
                try:
                    page.wait_for_function(_PRICE_INDICATOR_JS, timeout=8000)
                except Exception:
                    pass
                html = page.content()
                context.close()
            finally:
                browser.close()
        return html
    except Exception as exc:  # noqa: BLE001
        logger.warning("Playwright fetch failed for %s: %s", url, exc)
        return None


def fetch_price(url: str) -> FetchResult:
    """Fetch ``url`` and extract a price, classified (see :class:`FetchResult`).

    Tries a plain HTTP fetch first (fast, no browser); falls back to
    headless Chromium for JS-rendered pages. Non-secure ``http://`` URLs
    are attempted over HTTPS first.

    Serialized on :data:`_FETCH_LOCK` — see the module docstring.
    """
    with _FETCH_LOCK:
        return _fetch_price_unlocked(url)


def _fetch_price_unlocked(url: str) -> FetchResult:
    """Body of :func:`fetch_price` (caller holds :data:`_FETCH_LOCK`)."""
    logger.info("Starting price fetch for %s", url)
    # SSRF guard: user-supplied URLs must be public http/https before
    # anything is fetched (requests or browser).
    try:
        _validate_public_url(url)
    except ValueError as exc:
        logger.warning("Rejected URL %s: %s", url, exc)
        return FetchResult(
            FETCH_BLOCKED, "URL rejected (must be a public http/https address)"
        )
    candidates = _url_candidates(url)

    html: Optional[str] = None
    fetched_url: Optional[str] = None
    last_reason: Optional[str] = None

    for cand in candidates:
        html, reason = _fetch_html_requests(cand)
        if html is not None:
            fetched_url = cand
            break
        last_reason = reason

    if html is None:
        for cand in candidates:
            html = _fetch_html_playwright(cand)
            if html is not None:
                fetched_url = cand
                break

    if html is None:
        reason = last_reason or "could not fetch page"
        if last_reason and last_reason.startswith("HTTP "):
            code = last_reason.split(" ", 1)[1]
            if code in _BLOCKED_HTTP_CODES:
                logger.warning("Blocked (HTTP %s) fetching %s", code, url)
                return FetchResult(FETCH_BLOCKED, f"HTTP {code} from server")
        if last_reason and last_reason.startswith("blocked:"):
            # Policy refusal (e.g. redirect to a non-public address).
            logger.warning("Blocked fetching %s: %s", url, last_reason)
            return FetchResult(FETCH_BLOCKED, last_reason)
        logger.warning("Fetch failed for %s: %s", url, reason)
        return FetchResult(FETCH_FAILED, reason)

    found = _extract_from_html(html, fetched_url or url)
    if found is None:
        if _looks_like_bot_wall(html):
            logger.warning("Bot wall suspected for %s", url)
            return FetchResult(
                FETCH_BLOCKED, "page looks bot-blocked (no product content)"
            )
        logger.warning("No price found in HTML for %s", url)
        return FetchResult(
            FETCH_NO_PRICE, "no price found on page — link may not be a product page"
        )

    price, currency, title, image_url = found
    logger.info(
        "Price fetch succeeded for %s: price=%s %s, title=%s, image_url=%s",
        url,
        price,
        currency,
        title,
        image_url,
    )
    return FetchResult(
        FETCH_OK,
        "",
        FetchedPrice(
            price_local=price,
            currency=currency,
            title=title,
            image_url=image_url,
        ),
    )


def fetch_price_sync(url: str) -> FetchResult:
    """Blocking fetch for use in FastAPI background tasks.

    Always returns a classified :class:`FetchResult` (never raises, never
    ``None``) so the caller can persist a meaningful status.
    """
    try:
        return fetch_price(url)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Price fetch failed for %s: %s", url, exc)
        return FetchResult(FETCH_FAILED, f"unexpected error: {type(exc).__name__}")
