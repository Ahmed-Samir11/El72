"""Unit tests for the API credit ledger service."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from services.api.credits import deduct, get_balance, grant


def _database(existing_credit=None):
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value.first.return_value = existing_credit
    return db


def test_get_balance_lazy_provisions_free_allowance_without_writing():
    user = SimpleNamespace(id="user-1", tier="free")
    db = _database()

    assert get_balance(db, user) == 3
    db.add.assert_not_called()


def test_deduct_creates_credit_row_and_ledger_entry():
    user = SimpleNamespace(id="user-1", tier="free")
    db = _database()

    remaining = deduct(db, user)

    assert remaining == 2
    db.add.assert_called()
    db.flush.assert_called()


def test_deduct_rejects_insufficient_balance():
    user = SimpleNamespace(id="user-1", tier="free")
    credit = SimpleNamespace(balance=0)
    db = _database(credit)

    with pytest.raises(HTTPException) as error:
        deduct(db, user)

    assert error.value.status_code == 402
    assert credit.balance == 0
    db.flush.assert_not_called()


def test_grant_adds_credits_and_records_transaction():
    user = SimpleNamespace(id="user-1", tier="free")
    credit = SimpleNamespace(balance=2)
    db = _database(credit)

    assert grant(db, user, 10, reason="standard_purchase") == 12
    assert credit.balance == 12
    db.add.assert_called_once()
    db.flush.assert_called_once()


def test_paid_tiers_do_not_receive_implicit_package_credits():
    for tier in ("standard", "premium"):
        user = SimpleNamespace(id="user-1", tier=tier)
        db = _database()
        assert get_balance(db, user) == 0
