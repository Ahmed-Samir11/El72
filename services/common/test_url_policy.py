"""Tests for the server-side url policy (services/common/url_policy.py).

``POST /tracked-items/from-url`` stores the url a client names and then visits
it server-side, so this predicate decides what the API is allowed to fetch. Every
case below is a shape that has been used to reach internal hosts; the reason
strings are pinned because a log line is built from them.
"""

import pytest

from services.common.url_policy import fetch_block_reason

# (url, reason) pairs the API must refuse.
UNSAFE = [
    # Loopback, in the spellings that hide from a naive string compare.
    ("http://127.0.0.1:8000/tracked-items", "private-host"),
    ("http://localhost/latest", "private-host"),
    ("http://LOCALHOST.:80/x", "private-host"),
    ("http://127.0.0.1./x", "private-host"),
    ("http://[::1]/x", "private-host"),
    ("http://127.0.0.1.nip.io/", "private-host"),
    ("http://037777777777/", "private-host"),
    ("http://0x7f000001/", "private-host"),
    ("http://2130746113/", "private-host"),
    # Cloud metadata: the link-local IP, the AWS agent address beside it, and
    # the hostnames the clouds answer on.
    (
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        "private-host",
    ),
    ("http://169.254.170.189/latest/user-data", "private-host"),
    ("http://metadata.google.internal/computeMetadata/v1/", "private-host"),
    ("http://metadata.tencentyun.com/latest/meta-data/", "private-host"),
    # Private ranges inside RFC 1918 (a deployment's own network).
    ("http://10.0.0.5/internal", "private-host"),
    ("http://172.16.0.1/internal", "private-host"),
    ("http://192.168.1.1:5000/internal", "private-host"),
    # A reserved mDNS suffix, and a socket form that does not parse at all.
    ("http://tail.local/x", "private-host"),
    ("http://+[agent.sock+/b", "malformed"),
    # A host that only *starts* with a blocked address is still an address:
    # nip.io-style names resolve the embedded quad, so 169.254.169.254 hides in
    # a hostname that looks public at first glance.
    ("https://169.254.169.254.evil-but-public.test/product", "private-host"),
    # Not a web page: whatever scheme is named, the fetch is not http.
    ("file:///etc/passwd", "scheme"),
    ("data:text/html,hi", "scheme"),
    ("ftp://files.example.com/pub", "scheme"),
    ("javascript:alert(1)", "scheme"),
    ("//www.amazon.eg/dp/1", "scheme"),
    ("www.amazon.eg/dp/1", "scheme"),
    ("/dp/123", "scheme"),
    # A scheme with no address behind it.
    ("https://", "missing-host"),
    # Whitespace and control characters: request smuggling and log injection
    # both start by slipping one of these into a url.
    ("http://example.com/a\nb", "control-characters"),
    ("http://example.com/a b", "control-characters"),
    ("http://exa\u0000ample.com/", "control-characters"),
    ("http://ex\u007fample.com/", "control-characters"),
    ("", "empty"),
]

# Public product pages, in the shapes the scrapers actually return.
SAFE = [
    "https://www.amazon.eg/dp/B0C9L8XYZ",
    "https://www.noon.com/egypt-en/product/N22274511/p/",
    "https://www.jumia.com.eg/bp-fridge-123/",
    "http://alfrensia.com/en/search?q=tv",
    "https://www.sigma-computer.com/en/product?id=7#price",
    "https://elbadrgroupeg.store/index.php?route=product/product&product_id=9",
    "https://shop.example.com:443/product/1",
    # A host that merely differs from a blocked name by case, or that merely
    # starts with a label resembling one, is still public: over-blocking here
    # breaks real trackers.
    "https://8.8.8.8.example.com/x",
    "http://EXAMPLE.COM/",
    "http://Local.Host/",
]

UNSAFE_URLS = [url for url, _ in UNSAFE]
SAFE_URLS = SAFE


@pytest.mark.parametrize(
    "url",
    UNSAFE_URLS,
    ids=UNSAFE_URLS,
)
def test_a_url_the_server_must_not_visit_is_refused(url):
    assert fetch_block_reason(url) is not None, f"{url!r} was accepted"


@pytest.mark.parametrize("url,reason", UNSAFE)
def test_the_refusal_reason_is_named(url, reason):
    assert fetch_block_reason(url) == reason


@pytest.mark.parametrize("url", SAFE_URLS, ids=SAFE_URLS)
def test_a_public_product_page_is_allowed(url):
    assert fetch_block_reason(url) is None


def test_a_non_string_payload_is_refused_not_crashed():
    # The endpoint passes through whatever the client sent, and a body field of
    # the wrong type must end in a refusal rather than an exception that skips
    # the check.
    assert fetch_block_reason(None) == "empty"
    assert fetch_block_reason(123) == "empty"
    assert fetch_block_reason({}) == "empty"
