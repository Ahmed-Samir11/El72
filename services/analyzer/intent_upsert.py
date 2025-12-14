from typing import Any

async def upsert_retailer_analytics(conn: Any, store_id: str, category: str, target_price_bucket: str, delta_count: int = 1, delta_velocity: float = 1.0) -> None:
    """Upsert aggregated intent into `retailer_analytics`.

    - `conn` is an async DB connection (asyncpg or aiopg compatible execute method)
    - This table must NOT contain user-level PII.

    Example usage:
        await upsert_retailer_analytics(pg_conn, 'noon', 'laptops', '0-4999', 1, 0.5)
    """
    sql = """
    INSERT INTO retailer_analytics (store_id, category, target_price_bucket, user_waitlist_count, demand_velocity, last_updated)
    VALUES ($1, $2, $3, $4, $5, now())
    ON CONFLICT (store_id, category, target_price_bucket) DO UPDATE
    SET
      user_waitlist_count = retailer_analytics.user_waitlist_count + EXCLUDED.user_waitlist_count,
      demand_velocity = retailer_analytics.demand_velocity + EXCLUDED.demand_velocity,
      last_updated = now();
    """

    # Use positional params for asyncpg
    await conn.execute(sql, store_id, category, target_price_bucket, delta_count, delta_velocity)
