import hmac
import hashlib


def verify_paymob_hmac(secret: str, payload: bytes, header_signature: str) -> bool:
    """Verify HMAC signature from Paymob webhooks.

    - `secret` is the webhook secret (shared key)
+    - `payload` is raw request body bytes
+    - `header_signature` is the signature string from the header
+    Return True if matches.
+    """
+    computed = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
+    return hmac.compare_digest(computed, header_signature)
+