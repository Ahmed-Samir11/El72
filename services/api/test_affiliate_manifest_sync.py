"""Anti-drift guard: Android's launch allowlist, the server's redirect
allowlist and the client's Location-gate allowlist must agree.

Android refuses to open any host not declared in
``flutter-app/android/app/src/main/AndroidManifest.xml`` ``<queries>``
entries, while ``GET /affiliate/redirect`` will happily log and 307 to any
host in ``services/api/affiliate.py::STORE_HOSTS``. If the two drift,
real-device taps silently fail (plan p1 finding C5: the manifest pointed at
a host that exists nowhere else in the repo). ``MerchantLink`` additionally
refuses a server Location outside ``flutter-app/lib/src/core/url_guard.dart``
``merchantHostSuffixes`` — this test is the link between all three lists.
"""

import re
import warnings
from pathlib import Path

from services.api.affiliate import STORE_HOSTS

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = (
    REPO_ROOT
    / "flutter-app"
    / "android"
    / "app"
    / "src"
    / "main"
    / "AndroidManifest.xml"
)
URL_GUARD = REPO_ROOT / "flutter-app" / "lib" / "src" / "core" / "url_guard.dart"

# <data android:scheme="https" android:host="…"/> inside the <queries> block.
# Attribute order is not guaranteed, so host is matched independently of
# scheme, and only within the queries element so unrelated hosts cannot
# satisfy the guard.
_QUERIES_BLOCK = re.compile(r"<queries>(.*?)</queries>", re.DOTALL)
_HOST_ATTR = re.compile(r'android:host="([^"]+)"')


def _manifest_hosts() -> set[str]:
    text = MANIFEST.read_text(encoding="utf-8")
    blocks = _QUERIES_BLOCK.findall(text)
    assert blocks, "AndroidManifest.xml has no <queries> launch handlers"
    return {match for block in blocks for match in _HOST_ATTR.findall(block)}


def test_manifest_exists():
    assert MANIFEST.is_file(), f"missing manifest: {MANIFEST}"


def test_manifest_hosts_equal_store_hosts():
    """Every merchant the server can redirect to must be openable on Android,
    and the manifest must not promise hosts the server would reject (400)."""
    expected = {host for hosts in STORE_HOSTS.values() for host in hosts}
    actual = _manifest_hosts()
    assert actual == expected, (
        "Android <queries> hosts and STORE_HOSTS drifted apart — "
        f"manifest-only: {sorted(actual - expected)}, "
        f"server-only: {sorted(expected - actual)}. "
        "Add the merchant to BOTH services/api/affiliate.py::STORE_HOSTS "
        "and the manifest <queries>, or remove it from both."
    )


def test_every_store_has_at_least_one_host():
    """A store id in STORE_HOSTS with no host is a dead allowlist entry."""
    for store_id, hosts in STORE_HOSTS.items():
        assert hosts, f"STORE_HOSTS[{store_id}] is empty"


_SUFFIX_LIST = re.compile(r"merchantHostSuffixes\s*=\s*\[(.*?)\];", re.DOTALL)
_STRING_LIT = re.compile(r"'([^']+)'")


def test_client_location_gate_matches_server_hosts():
    """The Dart list gating the server's Location answer must cover exactly
    the merchants the server can redirect to (as registrable domains: the
    Dart check accepts each suffix plus its subdomains, so www.* variants of
    the same merchant are one entry here). Drift means MerchantLink would
    either ignore a legitimate tagged URL or honor a host the server never
    promised.

    Pre-merge tolerance: the constant lands with client PR #47; branches
    opened before it lacks the declaration entirely and skips, mirroring
    the UPSTREAM_ADDED pattern in services/common/test_migration_files.py.
    """
    if not URL_GUARD.is_file():
        return  # flutter-app core not present on this branch's tree
    text = URL_GUARD.read_text(encoding="utf-8")
    match = _SUFFIX_LIST.search(text)
    if match is None:
        # Loud, not silent: the constant lands with client PR #47, so a
        # pre-merge branch warns; the MERGED tree (where this guard exists
        # for a reason) must carry the declaration and reach the assert.
        warnings.warn(
            "url_guard.dart does not declare merchantHostSuffixes yet — "
            "the client Location gate is unguarded until PR #47 merges",
            stacklevel=1,
        )
        return
    declared = set(_STRING_LIT.findall(match.group(1)))
    server_domains = {
        host.removeprefix("www.") for hosts in STORE_HOSTS.values() for host in hosts
    }
    assert declared == server_domains, (
        "url_guard.dart merchantHostSuffixes and STORE_HOSTS drifted apart — "
        f"client-only: {sorted(declared - server_domains)}, "
        f"server-only: {sorted(server_domains - declared)}. "
        "Add the merchant to STORE_HOSTS, the manifest <queries> and "
        "merchantHostSuffixes together, or remove it from all three."
    )
