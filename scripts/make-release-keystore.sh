#!/usr/bin/env bash
# MS4: create the Elhaq release keystore (owner runs this ONCE on their own
# machine — the key must stay under the owner's control).
#
# Usage:
#   bash scripts/make-release-keystore.sh
#
# What it does:
#   1. Generates flutter-app/android/release.keystore (keytool, PKCS12)
#   2. Writes flutter-app/android/key.properties (gitignored)
#   3. Prints the base64 of the keystore for the KEY_STORE GitHub secret and
#      lists the other secrets to set. Passwords are read with hidden input
#      and are NEVER printed or placed on a command line.
#
# The keystore + key.properties are gitignored; only this script and the
# .example file are committed.
set -euo pipefail

cd "$(dirname "$0")/.."
ANDROID_DIR="flutter-app/android"
KEYSTORE="$ANDROID_DIR/release.keystore"

if [ -f "$KEYSTORE" ]; then
  echo "Error: $KEYSTORE already exists. Refusing to overwrite a release key." >&2
  exit 1
fi

read -r -s -p "Keystore password (hidden): " STORE_PW
read -r -s -p "Confirm password (hidden): " STORE_PW_CONFIRM
echo ""
if [ "$STORE_PW" != "$STORE_PW_CONFIRM" ]; then
  echo "Error: passwords did not match." >&2
  exit 1
fi
read -r -p "Key alias [elhaq]: " ALIAS
ALIAS="${ALIAS:-elhaq}"
read -r -s -p "Key password (hidden): " KEY_PW
echo ""

# keytool has no stdin password option; the passwords are on this one-time
# local command line (owner's machine only, never leaves it).
keytool -genkeypair \
  -keystore "$KEYSTORE" \
  -alias "$ALIAS" \
  -storetype PKCS12 \
  -validity 10000 \
  -keyalg RSA \
  -keysize 2048 \
  -storepass "$STORE_PW" \
  -keypass "$KEY_PW" \
  -dname "CN=Elhaq Release, OU=El72, O=Elhaq, L=Cairo, ST=Cairo, C=EG" \
  -ext "SAN=dns:elhaq.app"

# key.properties is written from the environment (never argv). storeFile is
# absolute so Gradle resolves it the same way from any working directory.
KEYSTORE_ABS=$(cd "$ANDROID_DIR" && pwd)/release.keystore
{
  echo "storeFile=$KEYSTORE_ABS"
  echo "storePassword=$STORE_PW"
  echo "keyAlias=$ALIAS"
  echo "keyPassword=$KEY_PW"
} > "$ANDROID_DIR/key.properties"

echo ""
echo "Keystore created: $KEYSTORE"
echo "key.properties written (gitignored)."
echo ""
echo "=== Set these GitHub secrets on the repo ==="
echo "  KEY_STORE            <- base64 printed below"
echo "  KEYSTORE_PASSWORD    <- the keystore password you chose"
echo "  KEY_ALIAS             <- $ALIAS"
echo "  KEY_ALIAS_PASSWORD   <- the key password you chose"
echo "  RELEASE_VERSION_CODE <- positive integer, bumped per release (v* tags)"
echo "  PROD_API_BASE_URL    <- production HTTPS API base"
echo ""
echo "=== KEY_STORE value (base64) ==="
# Portable one-line base64 (GNU and BSD).
base64 "$KEYSTORE" | tr -d '\n'
echo ""
