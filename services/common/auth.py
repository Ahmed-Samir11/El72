"""Shared JWT helpers for services that authenticate API-issued tokens.

Service isolation forbids importing between services, but `services/common/`
is the one shared library. The API service issues the access token and every
other service that accepts it must decode it with the same secret, algorithm
and claim contract, so that contract lives here and cannot drift.

Contract of an El72 access token:

* signed with ``HS256`` and the ``SECRET_KEY`` environment variable;
* ``sub`` is the user's phone number (never a user id — a client must not be
  able to pick an arbitrary internal id);
* ``exp`` is enforced by the decoder.
"""

import logging
import os
from typing import Optional

from jose import JWTError, jwt

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"


class TokenDecodeError(Exception):
    """Raised when a bearer token is missing, malformed, expired or unsigned.

    The message is deliberately generic: the caller turns it into an HTTP
    401 and must never echo the underlying jose error (which can carry claim
    contents) back to the client.
    """


def get_secret_key(secret_key: Optional[str] = None) -> str:
    """Return the JWT secret, from the argument or the environment.

    Raises:
        TokenDecodeError: when no secret is configured (a server-side
        misconfiguration, which callers should surface as 503, not 401).
    """
    secret = secret_key or os.getenv("SECRET_KEY")
    if not secret:
        raise TokenDecodeError("JWT secret is not configured")
    return secret


def require_secret_key() -> str:
    """Return the service's ``SECRET_KEY``, refusing to start without one.

    A deployed service that falls back to a hard-coded signing key lets anyone
    mint a token whose ``sub`` is any phone number, which is full access to
    every account. The old behaviour was a silent default; here it is a startup
    error with the fix spelled out, so it lands in the container log.

    Raises:
        RuntimeError: when the ``SECRET_KEY`` environment variable is unset
            or empty.
    """
    secret = os.getenv("SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "SECRET_KEY is not configured. Export it before starting this "
            "service (docker-compose already requires it through .env): a "
            "fallback signing key would let anyone forge access tokens."
        )
    return secret


def decode_access_token(
    token: str,
    secret_key: Optional[str] = None,
    algorithms: Optional[list] = None,
) -> dict:
    """Decode and validate an El72 access token.

    Args:
        token: The raw JWT (no ``Bearer`` prefix).
        secret_key: Overrides the ``SECRET_KEY`` env var; use it when a service
            validates a token space with its own key (e.g. admin tokens).

    Returns:
        The decoded payload as a dict.

    Raises:
        TokenDecodeError: on a missing secret, a malformed token or an
        expired signature.
    """
    if not token:
        raise TokenDecodeError("Empty bearer token")
    try:
        return jwt.decode(
            token,
            get_secret_key(secret_key),
            algorithms=algorithms or [ALGORITHM],
        )
    except JWTError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise TokenDecodeError("Could not validate credentials") from None


def token_subject(payload: dict) -> Optional[str]:
    """The phone number carried by a token's ``sub`` claim, else ``None``.

    A token without a usable ``sub`` cannot be mapped to a user, so callers
    reject it rather than falling back to a client-supplied user id.
    """
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        return None
    return subject.strip()


def bearer_token(authorization_header: Optional[str]) -> Optional[str]:
    """Extract the JWT from an ``Authorization: Bearer <jwt>`` header.

    Returns ``None`` when the header is absent or not a bearer scheme.
    """
    if not authorization_header:
        return None
    scheme, _, credentials = authorization_header.partition(" ")
    if scheme.lower() != "bearer" or not credentials.strip():
        return None
    return credentials.strip()
