import pytest

from services.analyzer.deal_scorer import detect_fake_discount, score_deal


HISTORY = [9800, 9950, 10000, 10000, 10100, 10200, 10300]


def test_genuine_deal_scores_high_and_is_explainable():
    result = score_deal(
        current_price=7500,
        historical_prices=HISTORY,
        competitor_prices=[8000, 8200],
        discount_duration_days=5,
    )
    assert result["score"] >= 80
    assert result["grade"] == "Excellent"
    assert result["signals"]["historical_discount"] > 0.20
    assert result["signals"]["cross_store_advantage"] > 0
    assert result["explanation"]


def test_ordinary_price_is_not_presented_as_a_strong_deal():
    result = score_deal(10000, HISTORY, competitor_prices=[10000, 10100])
    assert result["score"] < 40
    assert result["grade"] in {"Weak", "No deal"}
    assert result["signals"]["historical_discount"] == 0


@pytest.mark.parametrize(
    "current_price, expected_grade",
    [(8000, "Good"), (9000, "Fair"), (9800, "Weak"), (10000, "No deal")],
)
def test_score_grade_bands_follow_documented_thresholds(current_price, expected_grade):
    result = score_deal(current_price, HISTORY)
    assert result["grade"] == expected_grade


def test_historical_low_receives_a_distinct_signal():
    result = score_deal(7500, HISTORY, competitor_prices=[9000, 9200])
    assert result["signals"]["is_historical_low"] is True
    assert "Lowest observed price" in " ".join(result["explanation"])
    assert result["score"] >= 80


def test_inflated_reference_price_is_flagged_as_suspicious():
    result = detect_fake_discount(
        current_price=9600,
        historical_prices=[10000] * 15 + [12000] * 5,
        advertised_reference_price=12000,
        recent_prices=[10000, 12000, 10000],
        competitor_prices=[9000, 9200],
    )
    assert result["is_suspicious"] is True
    assert result["confidence"] >= 0.5
    assert any("Reference price" in reason for reason in result["reasons"])
    assert any("Competitors" in reason for reason in result["reasons"])


def test_suspicious_signal_penalizes_fake_discount_score():
    genuine = score_deal(7500, [10000] * 20, competitor_prices=[8200, 8300])
    suspicious = score_deal(
        9600,
        [10000] * 15 + [12000] * 5,
        competitor_prices=[9000, 9200],
        advertised_reference_price=12000,
    )
    assert suspicious["signals"]["suspicious_discount"]["is_suspicious"] is True
    assert suspicious["score"] < genuine["score"]


def test_genuine_discount_without_reference_is_not_flagged():
    result = detect_fake_discount(7500, HISTORY, competitor_prices=[8000, 8200])
    assert result["is_suspicious"] is False
    assert result["confidence"] == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"current_price": 0, "historical_prices": HISTORY},
        {"current_price": 100, "historical_prices": []},
        {"current_price": 100, "historical_prices": HISTORY, "discount_duration_days": -1},
    ],
)
def test_invalid_scoring_inputs_are_rejected(kwargs):
    with pytest.raises(ValueError):
        score_deal(**kwargs)
