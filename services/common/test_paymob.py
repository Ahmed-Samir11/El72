import pytest
import hmac
import hashlib
from services.common.paymob import verify_paymob_hmac

def test_verify_paymob_hmac_valid():
    secret = "test_secret"
    payload = b'{"test": "data"}'
    signature = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
    assert verify_paymob_hmac(secret, payload, signature) == True

def test_verify_paymob_hmac_invalid():
    secret = "test_secret"
    payload = b'{"test": "data"}'
    signature = "invalid"
    assert verify_paymob_hmac(secret, payload, signature) == False

def test_verify_paymob_hmac_wrong_secret():
    secret = "wrong_secret"
    payload = b'{"test": "data"}'
    correct_secret = "test_secret"
    signature = hmac.new(correct_secret.encode(), payload, hashlib.sha512).hexdigest()
    assert verify_paymob_hmac(secret, payload, signature) == False

def test_verify_paymob_hmac_empty_payload():
    secret = "test_secret"
    payload = b""
    signature = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
    assert verify_paymob_hmac(secret, payload, signature) == True

def test_verify_paymob_hmac_case_sensitive():
    secret = "test_secret"
    payload = b'{"test": "data"}'
    signature = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest().upper()
    # hmac.compare_digest is case sensitive, so upper case should fail
    assert verify_paymob_hmac(secret, payload, signature) == False