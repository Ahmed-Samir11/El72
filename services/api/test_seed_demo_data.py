"""Focused tests for the canonical TimescaleDB demo-history target."""

from sqlalchemy import create_engine, text
from services.api import seed_demo_data


def test_missing_history_table_fails_without_credentials():
    engine = create_engine("sqlite:///:memory:")

    try:
        seed_demo_data._validate_price_history_target(engine)
    except RuntimeError as exc:
        message = str(exc)
        assert "price_history" in message
        assert "secret" not in message
    else:  # pragma: no cover - assertion guard
        raise AssertionError("missing canonical history table was accepted")


def test_run_seed_uses_history_engine_for_price_rows(monkeypatch):
    operational = create_engine("sqlite:///:memory:")
    history = create_engine("sqlite:///:memory:")
    with history.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE price_history ("
                "time TIMESTAMP, sku TEXT, store_id TEXT, "
                "price_usd NUMERIC, price_local NUMERIC, "
                "currency TEXT, in_stock BOOLEAN, source_url TEXT, image_url TEXT)"
            )
        )

    seen = {}
    monkeypatch.setattr(seed_demo_data.Base.metadata, "create_all", lambda bind: None)
    def seed_history(session):
        seen["history_engine"] = session.get_bind()
        return 3

    monkeypatch.setattr(seed_demo_data, "_seed_price_history", seed_history)
    monkeypatch.setattr(seed_demo_data, "_seed_demo_user", lambda session: False)

    summary = seed_demo_data.run_seed(
        engine=operational,
        history_engine=history,
    )

    assert summary["price_history_rows"] == 3
    assert seen["history_engine"] is history


def test_run_seed_requires_explicit_timescale_url(monkeypatch):
    monkeypatch.setattr(seed_demo_data, "DATABASE_URL", None)
    monkeypatch.setattr(seed_demo_data, "TIMESCALE_URL", None)

    try:
        seed_demo_data.run_seed()
    except RuntimeError as exc:
        assert "DATABASE_URL" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("missing database configuration was accepted")