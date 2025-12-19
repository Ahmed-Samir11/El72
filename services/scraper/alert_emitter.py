"""Alert event emission system.

Emits alert events to Redis Streams when:
1. Price drops
2. Item comes back in stock
3. Price crosses user-defined threshold

Does NOT send notifications - just emits events for downstream processing.
"""

import asyncio
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Any

from services.common.redis_client import RedisStreamClient

logger = logging.getLogger(__name__)


class AlertType(Enum):
    """Types of alert events."""
    PRICE_DROP = "price_drop"
    BACK_IN_STOCK = "back_in_stock"
    THRESHOLD_CROSSED = "threshold_crossed"
    LOWEST_PRICE_CHANGED = "lowest_price_changed"


class AlertEvent:
    """Structured alert event."""
    
    def __init__(
        self,
        alert_type: AlertType,
        tracked_item_id: int,
        user_id: int,
        store_id: str,
        canonical_product_id: str,
        url: str,
        new_price_usd: float,
        new_price_local: float,
        currency: str,
        old_price_usd: Optional[float] = None,
        target_price: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.alert_type = alert_type
        self.tracked_item_id = tracked_item_id
        self.user_id = user_id
        self.store_id = store_id
        self.canonical_product_id = canonical_product_id
        self.url = url
        self.new_price_usd = new_price_usd
        self.new_price_local = new_price_local
        self.currency = currency
        self.old_price_usd = old_price_usd
        self.target_price = target_price
        self.metadata = metadata or {}
        self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "alert_type": self.alert_type.value,
            "tracked_item_id": self.tracked_item_id,
            "user_id": self.user_id,
            "store_id": self.store_id,
            "canonical_product_id": self.canonical_product_id,
            "url": self.url,
            "new_price_usd": self.new_price_usd,
            "new_price_local": self.new_price_local,
            "currency": self.currency,
            "old_price_usd": self.old_price_usd,
            "target_price": self.target_price,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }


class AlertEmitter:
    """Emits alert events to Redis Streams."""
    
    # Stream names for different alert types
    ALERTS_STREAM = "stream:alerts"
    
    def __init__(self, redis_client: RedisStreamClient):
        """Initialize emitter with Redis client.
        
        Args:
            redis_client: Redis stream client for publishing events
        """
        self.redis_client = redis_client
    
    async def emit_alert(self, event: AlertEvent):
        """Emit an alert event to Redis Stream.
        
        Args:
            event: Alert event to emit
        """
        try:
            payload = event.to_dict()
            msg_id = await self.redis_client.xadd(
                self.ALERTS_STREAM,
                {"payload": json.dumps(payload)}
            )
            logger.info(
                f"Emitted {event.alert_type.value} alert for tracked_item_id={event.tracked_item_id}, "
                f"user_id={event.user_id}, msg_id={msg_id}"
            )
        except Exception as e:
            logger.exception(
                f"Failed to emit alert for tracked_item_id={event.tracked_item_id}: {e}"
            )
    
    async def check_and_emit_alerts(
        self,
        tracked_item_id: int,
        user_id: int,
        store_id: str,
        canonical_product_id: str,
        url: str,
        processing_result: Dict[str, Any],
        target_price: Optional[float] = None
    ):
        """Check processing result and emit relevant alerts.
        
        Args:
            tracked_item_id: Database ID of tracked item
            user_id: User ID who owns this tracked item
            store_id: Store identifier
            canonical_product_id: Product identifier
            url: Product URL
            processing_result: Result from PriceProcessor.process_scrape_result
            target_price: Optional user-defined target price (in USD)
        """
        new_price_usd = processing_result["new_price_usd"]
        new_price_local = processing_result["new_price_local"]
        currency = processing_result["currency"]
        old_price_usd = processing_result.get("old_price_usd")
        price_changed = processing_result["price_changed"]
        stock_changed = processing_result["stock_changed"]
        in_stock = processing_result["in_stock"]
        is_lowest = processing_result["is_lowest"]
        
        # 1. Price Drop Alert
        if price_changed and old_price_usd and new_price_usd < old_price_usd:
            drop_percentage = ((old_price_usd - new_price_usd) / old_price_usd) * 100
            await self.emit_alert(AlertEvent(
                alert_type=AlertType.PRICE_DROP,
                tracked_item_id=tracked_item_id,
                user_id=user_id,
                store_id=store_id,
                canonical_product_id=canonical_product_id,
                url=url,
                new_price_usd=new_price_usd,
                new_price_local=new_price_local,
                currency=currency,
                old_price_usd=old_price_usd,
                metadata={"drop_percentage": round(drop_percentage, 2)}
            ))
        
        # 2. Back in Stock Alert
        if stock_changed and in_stock:
            await self.emit_alert(AlertEvent(
                alert_type=AlertType.BACK_IN_STOCK,
                tracked_item_id=tracked_item_id,
                user_id=user_id,
                store_id=store_id,
                canonical_product_id=canonical_product_id,
                url=url,
                new_price_usd=new_price_usd,
                new_price_local=new_price_local,
                currency=currency,
                metadata={"was_out_of_stock": True}
            ))
        
        # 3. Threshold Crossed Alert (if user has target price)
        if target_price and in_stock:
            # Check if price just crossed below threshold
            if new_price_usd <= target_price:
                # Only emit if this is a new crossing (price was above before)
                if old_price_usd is None or old_price_usd > target_price:
                    await self.emit_alert(AlertEvent(
                        alert_type=AlertType.THRESHOLD_CROSSED,
                        tracked_item_id=tracked_item_id,
                        user_id=user_id,
                        store_id=store_id,
                        canonical_product_id=canonical_product_id,
                        url=url,
                        new_price_usd=new_price_usd,
                        new_price_local=new_price_local,
                        currency=currency,
                        old_price_usd=old_price_usd,
                        target_price=target_price,
                        metadata={
                            "threshold_crossed": True,
                            "below_target_by": round(target_price - new_price_usd, 2)
                        }
                    ))
        
        # 4. Lowest Price Changed Alert (optional, only if this is now the best deal)
        if is_lowest and in_stock:
            await self.emit_alert(AlertEvent(
                alert_type=AlertType.LOWEST_PRICE_CHANGED,
                tracked_item_id=tracked_item_id,
                user_id=user_id,
                store_id=store_id,
                canonical_product_id=canonical_product_id,
                url=url,
                new_price_usd=new_price_usd,
                new_price_local=new_price_local,
                currency=currency,
                old_price_usd=old_price_usd,
                metadata={"is_lowest_price": True, "store": store_id}
            ))
    
    async def emit_scrape_failure(
        self,
        tracked_item_id: int,
        user_id: int,
        store_id: str,
        url: str,
        error_message: str
    ):
        """Emit a scraping failure event for monitoring.
        
        Args:
            tracked_item_id: Database ID of tracked item
            user_id: User ID
            store_id: Store identifier
            url: Failed URL
            error_message: Error description
        """
        try:
            payload = {
                "event_type": "scrape_failure",
                "tracked_item_id": tracked_item_id,
                "user_id": user_id,
                "store_id": store_id,
                "url": url,
                "error": error_message,
                "timestamp": datetime.utcnow().isoformat()
            }
            await self.redis_client.xadd(
                "stream:scrape_failures",
                {"payload": json.dumps(payload)}
            )
        except Exception as e:
            logger.exception(f"Failed to emit scrape failure event: {e}")
