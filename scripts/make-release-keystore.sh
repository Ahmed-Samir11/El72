#!/usr/bin/env bash
# MS4: create the Elhaq release keystore (owner runs this ONCE on their own
# machine — the key must stay under the owner's control).
#
# Usage:
#   bash scripts/make-release-keystore.sh
#
# What it does:
#   1. Generates flutter-app/android/release.keystore (keytool, alias "elhaq")
#   2. Writes flutter-app/android/key.properties from key.properties.example
#   3. Prints the base64 of the keystore — paste it into the GitHub secret
#      KEY_STORE on the repo settings screen, and set the three password
#      secrets (KEYSTORE_PASSWORD, KEY_ALIAS_PASSWORD) to the values you chose.
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

read -r -p "Keystore password: " STORE_PW
read -r -p "Confirm password: " STORE_PW_CONFIRM
if [ "$STORE_PW" != "$STORE_PW_CONFIRM" ]; then
  echo "Error: passwords did not match." >&2
  exit 1
fi
read -r -p "Key alias [elhaq]: " ALIAS
ALIAS="${ALIAS:-elhaq}"
read -r -p "Key password: " KEY_PW

keytool -genkeypair \
  -keystore "$KEYSTORE" \
  -alias "$ALIAS" \
  -storetype PKCS12 \
  -validity 10000 \
  -keyalg RSA \
  -keysize 2048 \
  -storepass "$STORE_PW" \
  -dname "CN=Elhaq Release, OU=El72, O=Elhaq, L=Cairo, ST=Cairo, C=EG" \
  -ext "SAN=dns:elhaq.app"

sed "s|^storeFile=.*|storeFile=$KEYSTORE|; s|^storePassword=.*|storePassword=$STORE_PW|; s|^keyAlias=.*|keyAlias=$ALIAS|; s|^keyPassword=.*|keyPassword=$KEY_PW|" \
  "$ANDROID_DIR/key.properties.example" > "$ANDROID_DIR/key.properties"

echo ""
echo "Keystore created: $KEYSTORE"
echo "key.properties written (gitignored)."
echo ""
echo "=== Set these GitHub secrets on the repo ==="
echo "  KEY_STORE          <- base64 below"
echo "  KEYSTORE_PASSWORD  = $STORE_PW"
echo "  KEY_ALIAS           = $ALIAS"
echo "  KEY_ALIAS_PASSWORD  = $KEY_PW"
echo ""
echo "=== KEY_STORE value (base64) ==="
base64 -w 0 "$KEYSTORE"
echo ""
