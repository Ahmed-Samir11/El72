"""Tests for the shared JWT contract used by every service that accepts a token.

The point of the shared library is that no service can quietly pick its own
algorithm, its own claim names or a fallback signing key.
"""

import datetime

import pytest
from jose import jwt

from services.common.auth import (
    ALGORITHM,
    TokenDecodeError,
    bearer_token,
    decode_access_token,
    get_secret_key,
    require_secret_key,
    token_subject,
)

SECRET = "unit-test-secret"


def _token(payload: dict, secret: str = SECRET) -> str:
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def test_the_shared_algorithm_is_hs256():
    """The API issues HS256 tokens; every verifier must match it."""
    assert ALGORITHM == "HS256"


def test_a_token_signed_with_the_shared_secret_round_trips():
    """A valid token decodes to the payload the API signed."""
    token = _token({"sub": "201234567890", "exp": _future()})

    payload = decode_access_token(token, SECRET)

    assert payload["sub"] == "201234567890"


def test_a_foreign_signature_is_rejected_as_a_token_error():
    """A token signed with another key must not be trusted, and the error type
    is the generic one callers turn into a 401 without echoing details."""
    token = _token({"sub": "201234567890", "exp": _future()}, "someone-elses-key")

    with pytest.raises(TokenDecodeError):
        decode_access_token(token, SECRET)


def test_an_expired_token_is_rejected():
    """``exp`` is enforced by the shared decoder, not by each service."""
    token = _token({"sub": "201234567890", "exp": _past()})

    with pytest.raises(TokenDecodeError):
        decode_access_token(token, SECRET)


def test_garbage_and_empty_tokens_are_token_errors():
    """Nothing about the input may reach the client as an exception message."""
    for token in ("", "not.a.jwt", "Bearer abc"):
        with pytest.raises(TokenDecodeError):
            decode_access_token(token, SECRET)


def _future() -> int:
    return int(
        (
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)
        ).timestamp()
    )


def _past() -> int:
    return int(
        (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
        ).timestamp()
    )


def test_the_subject_is_the_phone_number_and_must_be_a_string():
    """A client must not be able to pick an arbitrary internal user id."""
    assert token_subject({"sub": "201234567890"}) == "201234567890"
    assert token_subject({"sub": 42}) is None
    assert token_subject({"sub": "   "}) is None
    assert token_subject({}) is None


def test_the_bearer_scheme_is_parsed_without_trusting_the_case():
    assert bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"
    assert bearer_token("bearer abc.def.ghi") == "abc.def.ghi"
    assert bearer_token("Basic abc") is None
    assert bearer_token("Bearer") is None
    assert bearer_token(None) is None


def test_get_secret_key_reports_a_missing_configuration(monkeypatch):
    """A decode path with no key is a 503, never an unverified token."""
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(TokenDecodeError):
        get_secret_key()

    monkeypatch.setenv("SECRET_KEY", SECRET)
    assert get_secret_key() == SECRET


def test_a_service_refuses_to_start_without_a_signing_key(monkeypatch):
    """No fallback key: a predictable secret would forge any user's token."""
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        require_secret_key()

    monkeypatch.setenv("SECRET_KEY", "configured-at-last")
    assert require_secret_key() == "configured-at-last"
