"""Tests for scripts/verify-release-aab.py (MS4 release verification)."""

import importlib.util
import sys
import types
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Load the script (it lives outside the package, so load by path).
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify-release-aab.py"
spec = importlib.util.spec_from_file_location("verify_release_aab", SCRIPT_PATH)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def test_sha256_hex_modern_keytool_format():
    # Modern JDK: "Certificate fingerprint (SHA-256): 2F:DA:..."
    fp = (
        "2F:DA:BC:0D:4B:1A:EE:B6:38:00:00:CE:FE:D3:13:3C:C5:46:5B:01:"
        "B5:7F:3D:41:25:F7:F8:FE:40:9A:BE:FC"
    )
    assert fp.count(":") == 31  # 32 pairs = 64 hex chars
    text = (
        "elhaq, Sep 29 2026, PrivateKeyEntry,\n"
        f"Certificate fingerprint (SHA-256): {fp}\n"
    )
    assert verify.sha256_hex(
        text, [r"SHA256:", r"\(SHA-?256\)\s*:"], "keytool",
    ) == fp.replace(":", "").lower()


def test_sha256_hex_legacy_keytool_format():
    # Older JDK: "  SHA256: AB:CD:..." under "Certificate fingerprints:"
    fp = "AB:CD:EF:01:23:45:67:89:" * 4
    text = (
        "Certificate fingerprints:\n"
        "  SHA1: aa:bb\n"
        f"  SHA256: {fp}\n"
    )
    assert verify.sha256_hex(
        text, [r"SHA256:", r"\(SHA-?256\)\s*:"], "keytool",
    ) == fp.replace(":", "").lower()


def test_sha256_hex_apksigner_format():
    text = (
        "Verify using signer 'signer 0' certificate.\n"
        "Signer #1 certificate:\n"
        "SHA256 digest: " + "ab:cd:ef:01:23:45:67:89:" * 4 + "\n"
    )
    assert verify.sha256_hex(text, [r"SHA256 digest:"], "apksigner") == \
        "abcdef0123456789" * 4


def test_sha256_hex_requires_full_64_chars():
    # A truncated (40-char, SHA-1-length) fingerprint must NOT match.
    text = "SHA256 digest: ab:cd:ef:01:23:45\n"
    with pytest.raises(SystemExit):
        verify.sha256_hex(text, [r"SHA256 digest:"], "apksigner")


def test_sha256_hex_no_match_raises():
    with pytest.raises(SystemExit, match="could not find SHA256"):
        verify.sha256_hex("no fingerprint here", [r"SHA256 digest:"], "apksigner")


def _fake_aab(tmp_path: Path, version_code: str) -> Path:
    aab = tmp_path / "app-release.aab"
    manifest = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<manifest android:versionCode="{}" android:versionName="1.0.0">'
        "</manifest>".format(version_code)
    )
    with zipfile.ZipFile(aab, "w") as z:
        z.writestr("BaseManifest.xml", manifest)
    return aab


def _run_mock(fp_hex: str):
    keytool_out = "Certificate fingerprint (SHA-256): " + fp_hex + ":"
    apksigner_out = "SHA256 digest: " + fp_hex + ":"
    return [
        types.SimpleNamespace(stdout=keytool_out, returncode=0, stderr=""),
        types.SimpleNamespace(stdout=apksigner_out, returncode=0, stderr=""),
    ]


def test_main_version_code_match(tmp_path):
    aab = _fake_aab(tmp_path, "42")
    ks = tmp_path / "ks.p12"
    ks.write_bytes(b"fake")

    with patch.object(verify.subprocess, "run") as run:
        run.side_effect = _run_mock("ab:" * 32)
        # Should not raise.
        verify.main_with_args([
            "--keystore", str(ks), "--storepass", "pw", "--alias", "a",
            "--apksigner", "/bin/true", "--aab", str(aab),
            "--intended-version-code", "42",
        ])


def test_main_version_code_mismatch(tmp_path):
    aab = _fake_aab(tmp_path, "42")
    ks = tmp_path / "ks.p12"
    ks.write_bytes(b"fake")

    with patch.object(verify.subprocess, "run") as run:
        run.side_effect = _run_mock("ab:" * 32)
        with pytest.raises(SystemExit, match="versionCode 42 != intended 43"):
            verify.main_with_args([
                "--keystore", str(ks), "--storepass", "pw", "--alias", "a",
                "--apksigner", "/bin/true", "--aab", str(aab),
                "--intended-version-code", "43",
            ])


def test_main_certificate_mismatch(tmp_path):
    aab = _fake_aab(tmp_path, "1")
    ks = tmp_path / "ks.p12"
    ks.write_bytes(b"fake")

    with patch.object(verify.subprocess, "run") as run:
        run.side_effect = [
            types.SimpleNamespace(
                stdout="Certificate fingerprint (SHA-256): " + "aa:" * 32,
                returncode=0, stderr=""),
            types.SimpleNamespace(
                stdout="SHA256 digest: " + "bb:" * 32,
                returncode=0, stderr=""),
        ]
        with pytest.raises(SystemExit, match="does not match the release keystore"):
            verify.main_with_args([
                "--keystore", str(ks), "--storepass", "pw", "--alias", "a",
                "--apksigner", "/bin/true", "--aab", str(aab),
            ])
