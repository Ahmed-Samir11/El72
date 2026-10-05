"""Paymob REST API client (customer, payment method, payment).

PCI note: this client only ever exchanges Paymob *tokens* (staging tokens and
on-device tokenization tokens) with the Paymob API. Raw card data never
passes through our servers — tokenization happens on-device via the ToC SDK.

Configuration (environment variables, never in code or logs):
- PAYMOB_API_KEY:    Paymob API key (rotate immediately if leaked).
- PAYMOB_API_BASE:   API base URL (defaults to the production endpoint;
                      point it at the sandbox for staging deployments).
"""

import os
from typing import Any, Dict

import requests

PAYMOB_API_BASE = os.getenv("PAYMOB_API_BASE", "https://ciumpaymob.com/api")
PAYMOB_API_KEY = os.getenv("PAYMOB_API_KEY", "")

_REQUEST_TIMEOUT_SECONDS = 15


class PaymobApiError(Exception):
    """Raised when the Paymob API returns an error response.

    The message is safe to log (it never contains card data or tokens —
    Paymob error payloads are generic), but the raw response body is NOT
    attached to avoid leaking anything sensitive into logs.
    """

    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Paymob API {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


def _headers() -> Dict[str, str]:
    return {"Authorization": PAYMOB_API_KEY}


def _post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST to the Paymob API and return the parsed JSON body.

    Raises PaymobApiError on any non-2xx response.
    """
    if not PAYMOB_API_KEY:
        raise PaymobApiError(503, "payment provider is not configured")
    url = f"{PAYMOB_API_BASE}/{path}"
    try:
        resp = requests.post(
            url, json=payload, headers=_headers(), timeout=_REQUEST_TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        raise PaymobApiError(502, "paymob api unreachable") from exc
    if resp.status_code >= 400:
        # Do not echo the response body — it may contain sensitive context.
        raise PaymobApiError(resp.status_code, "payment provider rejected the request")
    try:
        return resp.json()
    except ValueError as exc:
        raise PaymobApiError(502, "paymob api returned invalid json") from exc


def create_customer(email: str) -> Dict[str, Any]:
    """Create a Paymob customer. Returns ``{"id": ..., "staging_token": ...}``.

    The email is a deterministic synthetic identity (``u{user_id}@elhaq.local``)
    — users have no real email on file, and the value contains no PII.
    """
    return _post("customer", {"email": email})


def create_payment_method(
    token: str, payment_method_type: str = "card"
) -> Dict[str, Any]:
    """Register an on-device tokenization token as a Paymob payment method.

    ``token`` is the ToC SDK output (a reference only — never card data).
    Returns ``{"id": ...}``.
    """
    return _post(
        "payment_method",
        {"token": token, "payment_method_type": payment_method_type},
    )


def create_payment(
    method_id: str, amount_paisa: int, currency: str, reference_id: str
) -> Dict[str, Any]:
    """Create a Paymob payment. Returns ``{"id": ..., "authentication_token": ...}``.

    ``amount_paisa`` is the minor-unit amount (server-determined from the
    package). ``reference_id`` carries our ``elhaq-{user_id}-{package}``
    marker so the webhook can resolve user + package.
    """
    return _post(
        "payment",
        {
            "amount": amount_paisa,
            "currency": currency,
            "payment_method_id": method_id,
            "reference_id": reference_id,
        },
    )


# Mapping from the canonical (upper-case) wallet types accepted by our API
# to the wallet_type enum values the Paymob payment_method endpoint expects.
PAYMOB_WALLET_TYPES: Dict[str, str] = {
    "VODAFONE_CASH": "Vodafone_Cash",
    "ORANGE_MONEY": "Orange_money",
    "ETISALAT_CASH": "Etisalat_Cash",
    "FAWRY": "Fawry",
}


def create_wallet_payment_method(
    staging_token: str, wallet_type: str, wallet_number: str
) -> Dict[str, Any]:
    """Create a Paymob wallet payment method. Returns ``{"id": ...}``.

    ``wallet_type`` must be one of :data:`PAYMOB_WALLET_TYPES` (the router
    validates it against the same allowlist before calling). ``wallet_number``
    is the user's wallet phone (validated in the router); it is sent to
    Paymob in the request payload only and is never logged or stored.
    """
    paymob_type = PAYMOB_WALLET_TYPES.get(wallet_type)
    if paymob_type is None:
        raise PaymobApiError(400, "unsupported wallet type")
    return _post(
        "payment_method",
        {
            "staging_token": staging_token,
            "wallet_type": paymob_type,
            "wallet_number": wallet_number,
        },
    )


def confirm_wallet_otp(payment_id: str, otp: str) -> Dict[str, Any]:
    """Confirm a wallet payment with the OTP the user received.

    Returns the payment object (including ``status``). The OTP is sent in the
    request payload only — ``_post`` never logs request bodies (plan 2.6).
    """
    return _post(f"payment/{payment_id}/otp_confirmation", {"otp": otp})
