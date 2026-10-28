"""The one rule for "may this service fetch the url a client asked for?".

The Flutter app has its own copy of this idea
(``flutter-app/lib/src/core/url_guard.dart``), and it decides only what the
*user's browser* may be asked to open. That guard
so the endpoint that hands a url to a fetcher has to make the same decision itself.

``POST /tracked-items/from-url`` is that endpoint: it stores the url and then
visits it server-side (``_persist_fetched_price``), so an unchecked url turns the
app's own server into a proxy for whatever host the caller names — the cloud
metadata IP (``169.254.169.254``), the instance-metadata hostnames the clouds
answer on (``metadata.google.internal``, ``metadata.tencentyun.com``), the container
agent socket (``+agent.sock``, and the ``169.254.170.189`` address it pairs with
on AWS), or a credential-free service on the private network. Blocking those here
is what keeps tracker creation inside the public web, whatever the client claims.

Deliberately *not* a store allowlist: supported domains change every time a scraper
is added, and a pinned list would silently break legitimate trackers the moment it
drifts. The private-target blocklist is the half that has to be right. It is a
blocklist nonetheless: a public hostname can still resolve somewhere internal (an
operator's ``/etc/hosts``), and the CGNAT range is not treated as private here, so
the real boundary is egress control at the network layer. What this stops is the
caller naming an internal target outright, which is the attack as it gets written.

The predicate returns the *reason* a url is refused (or ``None`` when it is safe)
so a log line can name the class of problem without echoing hostile input back.
"""

from ipaddress import ip_address
from typing import Optional
from urllib.parse import urlsplit

_BLOCKED = "malformed"


def _is_private_host(host: str) -> bool:
    """Whether `host` names a machine-local or private-network target.

    Compared lower-cased and with the trailing dot a browser adds for an absolute
    DNS name stripped, both of which are ways to hide a blocked host from a naive
    string comparison.
    """
    host = host.strip(".").lower()
    if not host:
        return True

    # A bracketed IPv6 literal, or a bare IPv4/IPv6 address: loopback, the RFC
    # 1918 private ranges (10.x, 172.16-31.x, 192.168.x) and link-local, which is
    # where the cloud metadata IPs live.
    candidate = host.strip("[]")
    try:
        ip = ip_address(candidate)
    except ValueError:
        pass
    else:
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True

    # `http://127.0.0.1.nip.io/` and friends (dssl, sslip, *.xip.io) embed a
    # dotted-quad in an otherwise ordinary hostname and resolve it back to that
    # address, so the quad is checked wherever it sits in the host, not only
    # when the host is just an address.
    labels = host.split(".")
    for i in range(len(labels) - 3):
        try:
            embedded = ip_address(".".join(labels[i : i + 4]))
        except ValueError:
            continue
        if embedded.is_private or embedded.is_loopback or embedded.is_link_local:
            return True

    # Names that resolve to this machine, or to a metadata/agent endpoint by
    # convention, before any suffix trickery.
    if host in {"localhost", "broadcasthost"}:
        return True
    if host.endswith((".local", ".localhost", ".internal", ".localdomain")):
        return True
    if host in {"metadata", "metadata.google", "metadata.google.internal"}:
        return True
    if host == "metadata.tencentyun.com":
        return True
    if host.isdigit() or (
        host.startswith("0x") and all(c in "0123456789abcdef" for c in host[2:])
    ):
        # A bare decimal or hex host is not an address as far as Python's own
        # resolver goes, but some HTTP stacks (Java's `InetAddress` among them)
        # read `2130746113` back as 127.0.0.1, and no product page lives on such
        # a host. The bracketed socket form (`http://+[agent.sock]/…`) never parses
        # at all, which the caller also treats as a refusal.
        return True
    return False


def fetch_block_reason(url: str) -> Optional[str]:
    """Why `url` must not be fetched, or ``None`` when fetching it is safe.

    Rejects non-http schemes, a missing host, a private/loopback/link-local host,
    and any url carrying whitespace or control characters — a raw newline or NUL
    inside a url is how request smuggling and log injection start.
    """
    if not isinstance(url, str) or not url:
        return "empty"
    if any(ord(c) < 32 or ord(c) == 127 or c.isspace() for c in url):
        return "control-characters"
    try:
        parts = urlsplit(url)
    except ValueError:
        return _BLOCKED
    if parts.scheme not in ("http", "https"):
        return "scheme"
    # `hostname` is the lower-cased host with userinfo and port removed; None
    # means the url is a relative path or a scheme with no address at all.
    host = parts.hostname
    if host is None:
        return "missing-host"
    if _is_private_host(host):
        return "private-host"
    return None
