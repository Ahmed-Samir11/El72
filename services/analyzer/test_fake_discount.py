import pytest

from services.analyzer.fake_discount import detect_fake_discount


def test_recent_inflation_before_discount_is_detected():
    result = detect_fake_discount(
        current_price=9600,
        historical_prices=[10000] * 20,
        advertised_reference_price=12000,
        recent_prices=[10000, 12000, 9600],
    )
    assert result["is_suspicious"] is True
    assert result["signals"]["recent_inflation"] == 0.2
    assert any("Recent price" in reason for reason in result["reasons"])


def test_genuine_historical_low_without_inflation_is_not_suspicious():
    result = detect_fake_discount(
        current_price=7500,
        historical_prices=[10000, 9900, 10100, 9800],
        competitor_prices=[8000, 8200],
        recent_prices=[10000, 9800, 7500],
    )
    assert result["is_suspicious"] is False
    assert result["confidence"] == 0


def test_invalid_reference_and_recent_prices_are_rejected():
    with pytest.raises(ValueError):
        detect_fake_discount(100, [100], advertised_reference_price=0)
    with pytest.raises(ValueError):
        detect_fake_discount(100, [100], recent_prices=[0])


def test_recent_prices_are_optional_and_constant_history_is_safe():
    result = detect_fake_discount(100, [100], recent_prices=[100, 100])
    assert result["signals"]["recent_inflation"] == 0
    assert result["is_suspicious"] is False


def test_reference_mismatch_without_historical_low_adds_reason():
    result = detect_fake_discount(
        10500,
        [10000] * 5,
        advertised_reference_price=12000,
    )
    assert result["is_suspicious"] is True
    assert "Current price is not near the historical low" in result["reasons"]


def test_nonpositive_current_price_is_rejected():
    with pytest.raises(ValueError):
        detect_fake_discount(0, [100])
