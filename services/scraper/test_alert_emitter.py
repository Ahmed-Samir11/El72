"""Tests for alert emitter."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import json

from services.scraper.alert_emitter import AlertEmitter, AlertEvent, AlertType


@pytest.fixture
def mock_redis_client():
    """Create mock Redis client."""
    client = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_emit_price_drop_alert(mock_redis_client):
    """Test emitting price drop alert."""
    emitter = AlertEmitter(mock_redis_client)
    
    event = AlertEvent(
        alert_type=AlertType.PRICE_DROP,
        tracked_item_id=1,
        user_id=123,
        store_id="amazon_eg",
        canonical_product_id="test-product",
        url="https://test.com",
        new_price_usd=90.0,
        new_price_local=2812.5,
        currency="EGP",
        old_price_usd=100.0,
        metadata={"drop_percentage": 10.0}
    )
    
    await emitter.emit_alert(event)
    
    # Verify xadd was called
    mock_redis_client.xadd.assert_called_once()
    call_args = mock_redis_client.xadd.call_args
    assert call_args[0][0] == "stream:alerts"


@pytest.mark.asyncio
async def test_check_and_emit_price_drop(mock_redis_client):
    """Test automatic price drop alert emission."""
    emitter = AlertEmitter(mock_redis_client)
    
    processing_result = {
        "new_price_usd": 90.0,
        "new_price_local": 2812.5,
        "currency": "EGP",
        "old_price_usd": 100.0,
        "price_changed": True,
        "stock_changed": False,
        "in_stock": True,
        "is_lowest": False
    }
    
    await emitter.check_and_emit_alerts(
        tracked_item_id=1,
        user_id=123,
        store_id="amazon_eg",
        canonical_product_id="test",
        url="https://test.com",
        processing_result=processing_result
    )
    
    # Should emit price drop alert
    assert mock_redis_client.xadd.call_count >= 1


@pytest.mark.asyncio
async def test_check_and_emit_back_in_stock(mock_redis_client):
    """Test back in stock alert emission."""
    emitter = AlertEmitter(mock_redis_client)
    
    processing_result = {
        "new_price_usd": 100.0,
        "new_price_local": 3125.0,
        "currency": "EGP",
        "old_price_usd": 100.0,
        "price_changed": False,
        "stock_changed": True,
        "in_stock": True,
        "is_lowest": False
    }
    
    await emitter.check_and_emit_alerts(
        tracked_item_id=1,
        user_id=123,
        store_id="amazon_eg",
        canonical_product_id="test",
        url="https://test.com",
        processing_result=processing_result
    )
    
    # Should emit back in stock alert
    mock_redis_client.xadd.assert_called()


@pytest.mark.asyncio
async def test_check_and_emit_threshold_crossed(mock_redis_client):
    """Test threshold crossed alert emission."""
    emitter = AlertEmitter(mock_redis_client)
    
    processing_result = {
        "new_price_usd": 80.0,
        "new_price_local": 2500.0,
        "currency": "EGP",
        "old_price_usd": 100.0,
        "price_changed": True,
        "stock_changed": False,
        "in_stock": True,
        "is_lowest": False
    }
    
    await emitter.check_and_emit_alerts(
        tracked_item_id=1,
        user_id=123,
        store_id="amazon_eg",
        canonical_product_id="test",
        url="https://test.com",
        processing_result=processing_result,
        target_price=90.0  # Price crossed below target
    )
    
    # Should emit threshold crossed alert
    assert mock_redis_client.xadd.call_count >= 2  # Price drop + threshold


@pytest.mark.asyncio
async def test_emit_scrape_failure(mock_redis_client):
    """Test scrape failure event emission."""
    emitter = AlertEmitter(mock_redis_client)
    
    await emitter.emit_scrape_failure(
        tracked_item_id=1,
        user_id=123,
        store_id="amazon_eg",
        url="https://test.com",
        error_message="Timeout error"
    )
    
    # Verify xadd was called with failure stream
    mock_redis_client.xadd.assert_called_once()
    call_args = mock_redis_client.xadd.call_args
    assert call_args[0][0] == "stream:scrape_failures"


def test_alert_event_to_dict():
    """Test alert event serialization."""
    event = AlertEvent(
        alert_type=AlertType.PRICE_DROP,
        tracked_item_id=1,
        user_id=123,
        store_id="amazon_eg",
        canonical_product_id="test",
        url="https://test.com",
        new_price_usd=90.0,
        new_price_local=2812.5,
        currency="EGP",
        old_price_usd=100.0
    )
    
    data = event.to_dict()
    assert data["alert_type"] == "price_drop"
    assert data["tracked_item_id"] == 1
    assert data["new_price_usd"] == 90.0
    assert "timestamp" in data
