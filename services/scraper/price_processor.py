"""Price processing, currency conversion, and lowest price resolution.

This module handles:
1. Currency conversion to base currency (USD)
2. Price change detection
3. Idempotent price history storage
4. Lowest price calculation across stores
"""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import asyncpg

from services.scraper.store_scrapers import ScrapeResult

logger = logging.getLogger(__name__)


# Exchange rates (should be fetched from API in production)
EXCHANGE_RATES = {
    "EGP": 0.032,  # 1 EGP = 0.032 USD (approximate)
    "USD": 1.0,
    "AED": 0.27,   # UAE Dirham
    "SAR": 0.27,   # Saudi Riyal
}


class PriceProcessor:
    """Handles price conversion, comparison, and storage."""
    
    def __init__(self, db_pool: asyncpg.Pool):
        """Initialize processor with database pool.
        
        Args:
            db_pool: Asyncpg connection pool for database operations
        """
        self.db_pool = db_pool
    
    @staticmethod
    def convert_to_usd(price: float, currency: str) -> float:
        """Convert price to USD using exchange rates.
        
        Args:
            price: Original price
            currency: Currency code (e.g., 'EGP', 'USD')
            
        Returns:
            Price in USD
        """
        rate = EXCHANGE_RATES.get(currency.upper(), 1.0)
        return round(price * rate, 4)
    
    async def process_scrape_result(
        self,
        result: ScrapeResult,
        tracked_item_id: int
    ) -> Dict[str, any]:
        """Process a scrape result: convert currency, detect changes, update DB.
        
        Args:
            result: Scrape result from store scraper
            tracked_item_id: Database ID of tracked item
            
        Returns:
            Dictionary with processing info:
            - price_changed: bool
            - stock_changed: bool
            - old_price_usd: float or None
            - new_price_usd: float
            - is_lowest: bool
        """
        # Convert to USD
        price_usd = self.convert_to_usd(result.price, result.currency)
        
        async with self.db_pool.acquire() as conn:
            # Check if price changed (idempotent check)
            price_changed, old_price_usd = await self._detect_price_change(
                conn, tracked_item_id, result.store, price_usd
            )
            
            # Check if stock status changed
            stock_changed = await self._detect_stock_change(
                conn, tracked_item_id, result.store, result.in_stock
            )
            
            # Update current price snapshot
            await self._update_current_price(
                conn,
                tracked_item_id,
                result.store,
                price_usd,
                result.price,
                result.currency,
                result.in_stock
            )
            
            # Insert price history only if price changed
            if price_changed:
                await self._insert_price_history(
                    conn,
                    tracked_item_id,
                    result.store,
                    result.canonical_product_id,
                    price_usd,
                    result.price,
                    result.currency,
                    result.in_stock
                )
            
            # Recalculate lowest price across stores
            is_lowest = await self._update_lowest_price(
                conn, tracked_item_id, result.url
            )
            
            return {
                "price_changed": price_changed,
                "stock_changed": stock_changed,
                "old_price_usd": old_price_usd,
                "new_price_usd": price_usd,
                "new_price_local": result.price,
                "currency": result.currency,
                "is_lowest": is_lowest,
                "in_stock": result.in_stock
            }
    
    async def _detect_price_change(
        self,
        conn: asyncpg.Connection,
        tracked_item_id: int,
        store_id: str,
        new_price_usd: float
    ) -> Tuple[bool, Optional[float]]:
        """Detect if price has changed since last check.
        
        Returns:
            (price_changed: bool, old_price_usd: float or None)
        """
        query = """
            SELECT price_usd FROM current_prices
            WHERE tracked_item_id = $1 AND store_id = $2
        """
        row = await conn.fetchrow(query, tracked_item_id, store_id)
        
        if row is None:
            # First time seeing this item at this store
            return True, None
        
        old_price = float(row["price_usd"])
        # Consider changed if difference > 0.01 USD to avoid floating point noise
        changed = abs(old_price - new_price_usd) > 0.01
        return changed, old_price if changed else None
    
    async def _detect_stock_change(
        self,
        conn: asyncpg.Connection,
        tracked_item_id: int,
        store_id: str,
        new_in_stock: bool
    ) -> bool:
        """Detect if stock status changed."""
        query = """
            SELECT in_stock FROM current_prices
            WHERE tracked_item_id = $1 AND store_id = $2
        """
        row = await conn.fetchrow(query, tracked_item_id, store_id)
        
        if row is None:
            return False  # First time, no change
        
        return row["in_stock"] != new_in_stock
    
    async def _update_current_price(
        self,
        conn: asyncpg.Connection,
        tracked_item_id: int,
        store_id: str,
        price_usd: float,
        price_local: float,
        currency: str,
        in_stock: bool
    ):
        """Update current price snapshot (upsert)."""
        query = """
            INSERT INTO current_prices (
                tracked_item_id, store_id, price_usd, price_local,
                currency, in_stock, last_updated
            )
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            ON CONFLICT (tracked_item_id, store_id)
            DO UPDATE SET
                price_usd = EXCLUDED.price_usd,
                price_local = EXCLUDED.price_local,
                currency = EXCLUDED.currency,
                in_stock = EXCLUDED.in_stock,
                last_updated = NOW()
        """
        await conn.execute(
            query, tracked_item_id, store_id, price_usd, price_local,
            currency, in_stock
        )
    
    async def _insert_price_history(
        self,
        conn: asyncpg.Connection,
        tracked_item_id: int,
        store_id: str,
        sku: str,
        price_usd: float,
        price_local: float,
        currency: str,
        in_stock: bool
    ):
        """Insert price into TimescaleDB price_history table.
        
        Note: Uses current timestamp. TimescaleDB will handle deduplication
        if the same price is inserted multiple times at the same timestamp.
        """
        query = """
            INSERT INTO price_history (
                time, sku, store_id, price_egp, in_stock
            )
            VALUES (NOW(), $1, $2, $3, $4)
            ON CONFLICT (time, sku, store_id) DO NOTHING
        """
        # Note: price_egp column is legacy - storing USD converted to EGP equivalent
        # In production, you'd want to add a price_usd column to price_history
        price_egp = price_local if currency == "EGP" else price_usd / EXCHANGE_RATES.get("EGP", 0.032)
        
        await conn.execute(query, sku, store_id, price_egp, in_stock)
    
    async def _update_lowest_price(
        self,
        conn: asyncpg.Connection,
        tracked_item_id: int,
        current_url: str
    ) -> bool:
        """Recalculate and update lowest price across all stores.
        
        Returns:
            True if the just-processed price is now the lowest
        """
        # Find lowest price across all stores (only in-stock items)
        query = """
            SELECT store_id, price_usd, price_local, currency, url
            FROM current_prices cp
            JOIN tracked_item_stores tis
                ON cp.tracked_item_id = tis.tracked_item_id
                AND cp.store_id = tis.store_id
            WHERE cp.tracked_item_id = $1
                AND cp.in_stock = TRUE
            ORDER BY cp.price_usd ASC
            LIMIT 1
        """
        row = await conn.fetchrow(query, tracked_item_id)
        
        if row is None:
            # No in-stock prices available
            # Delete lowest_price entry if exists
            await conn.execute(
                "DELETE FROM lowest_prices WHERE tracked_item_id = $1",
                tracked_item_id
            )
            return False
        
        # Upsert lowest price
        upsert_query = """
            INSERT INTO lowest_prices (
                tracked_item_id, store_id, price_usd, price_local,
                currency, url, last_updated
            )
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            ON CONFLICT (tracked_item_id)
            DO UPDATE SET
                store_id = EXCLUDED.store_id,
                price_usd = EXCLUDED.price_usd,
                price_local = EXCLUDED.price_local,
                currency = EXCLUDED.currency,
                url = EXCLUDED.url,
                last_updated = NOW()
        """
        await conn.execute(
            upsert_query,
            tracked_item_id,
            row["store_id"],
            row["price_usd"],
            row["price_local"],
            row["currency"],
            row["url"]
        )
        
        # Check if the current URL is the lowest
        return row["url"] == current_url
    
    async def get_lowest_price_for_item(
        self,
        tracked_item_id: int
    ) -> Optional[Dict[str, any]]:
        """Get cached lowest price for a tracked item.
        
        Args:
            tracked_item_id: Database ID of tracked item
            
        Returns:
            Dictionary with lowest price info or None
        """
        async with self.db_pool.acquire() as conn:
            query = """
                SELECT store_id, price_usd, price_local, currency, url, last_updated
                FROM lowest_prices
                WHERE tracked_item_id = $1
            """
            row = await conn.fetchrow(query, tracked_item_id)
            
            if row is None:
                return None
            
            return {
                "store_id": row["store_id"],
                "price_usd": float(row["price_usd"]),
                "price_local": float(row["price_local"]),
                "currency": row["currency"],
                "url": row["url"],
                "last_updated": row["last_updated"]
            }
    
    async def get_all_current_prices(
        self,
        tracked_item_id: int
    ) -> List[Dict[str, any]]:
        """Get all current prices across stores for a tracked item.
        
        Args:
            tracked_item_id: Database ID of tracked item
            
        Returns:
            List of dictionaries with price info per store
        """
        async with self.db_pool.acquire() as conn:
            query = """
                SELECT
                    cp.store_id,
                    cp.price_usd,
                    cp.price_local,
                    cp.currency,
                    cp.in_stock,
                    cp.last_updated,
                    tis.store_url
                FROM current_prices cp
                JOIN tracked_item_stores tis
                    ON cp.tracked_item_id = tis.tracked_item_id
                    AND cp.store_id = tis.store_id
                WHERE cp.tracked_item_id = $1
                ORDER BY cp.price_usd ASC
            """
            rows = await conn.fetch(query, tracked_item_id)
            
            return [
                {
                    "store_id": row["store_id"],
                    "price_usd": float(row["price_usd"]),
                    "price_local": float(row["price_local"]),
                    "currency": row["currency"],
                    "in_stock": row["in_stock"],
                    "last_updated": row["last_updated"],
                    "url": row["store_url"]
                }
                for row in rows
            ]
