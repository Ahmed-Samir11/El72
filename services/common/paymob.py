import hashlib
import hmac


def verify_paymob_hmac(secret: str, payload: bytes, header_signature: str) -> bool:
    """Verify a Paymob webhook HMAC signature.

    Parameters
    - `secret`: webhook shared secret (string)
    - `payload`: raw request body bytes
    - `header_signature`: signature value received in the webhook headers

    Returns
    - `True` if the computed signature matches `header_signature`, otherwise `False`.
    """
    computed = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, header_signature)
