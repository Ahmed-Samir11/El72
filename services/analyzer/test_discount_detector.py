"""Tests for the DB-backed fake-discount data + service layers.

These tests exercise the windowing/median/low math and the human-readable
summary without a live database: the data layer is fed synthetic rows and the
service layer is fed a pre-built ``DiscountInputs``.
"""

from datetime import datetime, timedelta, timezone

from services.analyzer.discount_data import (
    DiscountInputs,
    build_discount_inputs,
)
from services.analyzer.discount_service import analyze_discount

NOW = datetime(2025, 9, 1, tzinfo=timezone.utc)


def _rows(prices, store_id="amazon_eg", advertised=None, start_days_ago=90):
    """Build time-ascending rows ending at NOW, one per day."""
    rows = []
    n = len(prices)
    for i, price in enumerate(prices):
        # Spread the points across the window, last one at NOW.
        days_ago = start_days_ago - i * (start_days_ago // max(n - 1, 1))
        rows.append(
            {
                "time": NOW - timedelta(days=days_ago),
                "store_id": store_id,
                "price_local": price,
                "advertised_price": advertised,
            }
        )
    return rows


def test_build_inputs_computes_medians_and_low():
    # 20 points: ten at 1200, ten at 1250 -> median 1225.
    prices = [1200] * 10 + [1250] * 10
    inputs = build_discount_inputs(_rows(prices), "sku-1", now=NOW)
    assert inputs.status == "ok"
    assert inputs.median_90d == 1225
    assert inputs.historical_low == 1200
    assert inputs.current_price == 1250
    assert inputs.point_count == 20


def test_build_inputs_insufficient_history():
    inputs = build_discount_inputs(_rows([1200, 1210, 1190]), "sku-1", now=NOW)
    assert inputs.status == "insufficient_history"
    assert inputs.point_count == 3


def test_build_inputs_extracts_latest_advertised_reference():
    # Advertised price only present on the most recent rows.
    prices = [1200] * 15
    rows = _rows(prices, advertised=None)
    rows[-1]["advertised_price"] = 1800
    inputs = build_discount_inputs(rows, "sku-1", now=NOW)
    assert inputs.advertised_reference_price == 1800


def test_build_inputs_skips_rows_without_usable_price():
    # NULL / invalid price_local rows must be skipped, not raise (review
    # finding: null or invalid price_local values cause a 500 response).
    prices = [1200] * 16
    rows = _rows(prices)
    rows[3]["price_local"] = None
    rows[5]["price_local"] = "not-a-number"
    inputs = build_discount_inputs(rows, "sku-1", now=NOW)
    assert inputs.status == "ok"
    assert inputs.point_count == 14  # 16 - 2 unusable rows


def test_build_inputs_ignores_invalid_advertised_reference():
    # Non-positive / malformed advertised prices are skipped (review finding:
    # advertised reference price is not validated).
    prices = [1200] * 15
    rows = _rows(prices, advertised=None)
    rows[-1]["advertised_price"] = -50
    rows[-2]["advertised_price"] = "garbage"
    rows[-3]["advertised_price"] = 1800
    inputs = build_discount_inputs(rows, "sku-1", now=NOW)
    assert inputs.advertised_reference_price == 1800


def test_build_inputs_scopes_to_store_and_collects_competitors():
    # Target store amazon_eg at 1200; competitor noon at 1150.
    rows = _rows([1200] * 15, store_id="amazon_eg")
    rows += _rows([1150] * 15, store_id="noon")
    # Interleaved stores must be globally time-ordered (the loader returns
    # rows ORDER BY time; build_discount_inputs relies on that).
    rows = sorted(rows, key=lambda r: r["time"])
    inputs = build_discount_inputs(rows, "sku-1", store_id="amazon_eg", now=NOW)
    assert inputs.current_price == 1200
    assert inputs.competitor_prices == [1150]
    # Pooled (no store scope) -> no competitor list, current is the overall last.
    pooled = build_discount_inputs(rows, "sku-1", store_id=None, now=NOW)
    assert pooled.competitor_prices == []


def test_analyze_discount_flags_fake_discount():
    # Typical ~1200, current 1180 (barely below), advertised "was" 1800.
    inputs = DiscountInputs(
        sku="sku-1",
        store_id="amazon_eg",
        status="ok",
        current_price=1180,
        historical_prices=[1200] * 20,
        median_30d=1200,
        median_90d=1200,
        historical_low=1180,
        advertised_reference_price=1800,
        competitor_prices=[],
        recent_prices=[1200, 1180],
        point_count=20,
    )
    result = analyze_discount(inputs)
    assert result["is_suspicious"] is True
    assert result["confidence"] >= 0.5
    assert result["stats"]["reference_source"] == "advertised"
    assert "typically sold for" in result["summary"]


def test_analyze_discount_genuine_discount_not_flagged():
    # Typical ~1200, current 900 (25% below), no inflated reference.
    inputs = DiscountInputs(
        sku="sku-1",
        store_id="amazon_eg",
        status="ok",
        current_price=900,
        historical_prices=[1200] * 20,
        median_30d=1200,
        median_90d=1200,
        historical_low=900,
        advertised_reference_price=None,
        competitor_prices=[950, 980],
        recent_prices=[1200, 1180, 900],
        point_count=20,
    )
    result = analyze_discount(inputs)
    assert result["is_suspicious"] is False
    assert result["confidence"] == 0.0
    assert "genuine discount" in result["summary"]


def test_analyze_discount_price_above_normal_not_nonsensical():
    # Current price above both medians: the summary must not render a
    # negative "below normal" percentage (review finding: summary can
    # produce nonsensical negative 'below normal' text).
    inputs = DiscountInputs(
        sku="sku-1",
        store_id="amazon_eg",
        status="ok",
        current_price=1400,
        historical_prices=[1200] * 20,
        median_30d=1200,
        median_90d=1200,
        historical_low=1180,
        advertised_reference_price=1800,
        competitor_prices=[],
        recent_prices=[1200, 1400],
        point_count=20,
    )
    result = analyze_discount(inputs)
    assert result["is_suspicious"] is True
    assert "at or above its normal price" in result["summary"]
    assert "-%" not in result["summary"]


def test_analyze_discount_insufficient_history_short_circuits():
    inputs = DiscountInputs(
        sku="sku-1",
        store_id=None,
        status="insufficient_history",
        current_price=1200,
        historical_prices=[1200],
        point_count=1,
    )
    result = analyze_discount(inputs)
    assert result["status"] == "insufficient_history"
    assert result["is_suspicious"] is False
    assert "Not enough price history" in result["summary"]
