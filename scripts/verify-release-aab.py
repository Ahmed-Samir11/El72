#!/usr/bin/env python3
"""Verify that a release AAB is signed with the release keystore and carries
the intended versionCode.

Used by the flutter-ci GitHub workflow after `flutter build appbundle`.
Fails the build (exit 1) when:
  - the AAB's certificate SHA256 does not match the keystore's certificate,
  - the versionCode in BaseManifest.xml differs from the intended value.

Both fingerprint sources are normalized to lowercase hex before comparison:
keytool prints uppercase on old JDKs and "Certificate fingerprint
(SHA-256): ..." on modern JDKs; apksigner prints "SHA256 digest: ...".
"""

import argparse
import re
import subprocess
import sys
import zipfile


def sha256_hex(text: str, patterns: list[str], source: str) -> str:
    """Extract a SHA-256 fingerprint (64 hex chars) from tool output.

    Tries each label pattern in order (keytool changed its output format
    across JDK versions); returns lowercase hex without colons.
    """
    for pat in patterns:
        # Match the whole colon-separated hex token, then validate that it
        # is exactly 32 bytes (64 hex chars) after stripping colons.
        m = re.search(pat + r"\s*([0-9A-Fa-f][0-9A-Fa-f:]*)", text)
        if m:
            hexchars = m.group(1).replace(":", "").lower()
            if len(hexchars) == 64:
                return hexchars
    raise SystemExit(f"error: could not find SHA256 fingerprint in {source} output")


def main_with_args(argv: list[str]) -> None:
    """Run the verification with an explicit argument list (testable)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keystore", required=True, help="path to the release keystore")
    parser.add_argument("--storepass", required=True, help="keystore password")
    parser.add_argument("--alias", required=True, help="key alias in the keystore")
    parser.add_argument("--apksigner", required=True, help="path to apksigner (build-tools)")
    parser.add_argument("--aab", required=True, help="path to the built .aab")
    parser.add_argument(
        "--intended-version-code", default="",
        help="expected versionCode; when set, the AAB must match it exactly",
    )
    args = parser.parse_args(argv)

    # 1. Expected fingerprint: from the keystore certificate (alias-scoped).
    try:
        keytool_out = subprocess.run(
            ["keytool", "-list", "-keystore", args.keystore,
             "-storepass", args.storepass, "-alias", args.alias],
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError as e:
        raise SystemExit(
            f"error: keytool failed (exit {e.returncode}): "
            f"{e.stderr.strip()[:200]}"
        )
    expected = sha256_hex(
        keytool_out, [r"SHA256:", r"\(SHA-?256\)\s*:"], "keytool",
    )

    # 2. Actual fingerprint: from the AAB's signing certificate.
    apksigner = subprocess.run(
        [args.apksigner, "verify", "--print-certs", args.aab],
        capture_output=True, text=True,
    )
    if apksigner.returncode != 0:
        raise SystemExit(
            f"error: apksigner failed (exit {apksigner.returncode}): "
            f"{apksigner.stderr.strip()[:200]}"
        )
    actual = sha256_hex(apksigner.stdout, [r"SHA256 digest:"], "apksigner")

    if expected != actual:
        raise SystemExit(
            f"error: AAB certificate ({actual}) does not match the release "
            f"keystore certificate ({expected})"
        )
    print(f"AAB signed with the release keystore (SHA256 {actual}).")

    # 3. versionCode: lives in BaseManifest.xml inside the AAB zip.
    with zipfile.ZipFile(args.aab) as z:
        manifest = z.read("BaseManifest.xml").decode("utf-8")
    m = re.search(r'android:versionCode="(\d+)"', manifest)
    if not m:
        raise SystemExit("error: could not find versionCode in BaseManifest.xml")
    built = m.group(1)

    intended = args.intended_version_code.strip()
    if intended and built != intended:
        raise SystemExit(f"error: AAB versionCode {built} != intended {intended}")
    print(f"AAB versionCode: {built}")


def main() -> None:
    main_with_args(sys.argv[1:])


if __name__ == "__main__":
    main()
