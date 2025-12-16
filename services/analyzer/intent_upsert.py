from typing import Any, List, Tuple


async def upsert_retailer_analytics(
    conn: Any,
    store_id: str,
    category: str,
    target_price_bucket: str,
    delta_count: int = 1,
    delta_velocity: float = 1.0,
) -> None:
    """Backward-compatible single upsert helper."""
    await upsert_retailer_analytics_batch(
        conn, [(store_id, category, target_price_bucket, delta_count, delta_velocity)]
    )


async def upsert_retailer_analytics_batch(
    conn: Any, items: List[Tuple[str, str, str, int, float]]
) -> None:
    """Batch upsert aggregated intent into `retailer_analytics` using UNNEST.

    `items` is a list of tuples: (store_id, category, target_price_bucket,
    delta_count, delta_velocity)
    """
    if not items:
        return

    store_ids = [i[0] for i in items]
    categories = [i[1] for i in items]
    buckets = [i[2] for i in items]
    delta_counts = [i[3] for i in items]
    delta_velocities = [i[4] for i in items]

    sql = (
        "INSERT INTO retailer_analytics (store_id, category, "
        "target_price_bucket, user_waitlist_count, demand_velocity, "
        "last_updated) "
        "SELECT store_id, category, target_price_bucket, delta_count::int, "
        "delta_velocity::double precision, now() FROM ("
        "SELECT UNNEST($1::text[]) AS store_id, UNNEST($2::text[]) AS category, "
        "UNNEST($3::text[]) AS target_price_bucket, UNNEST($4::int[]) AS delta_count, "
        "UNNEST($5::double precision[]) AS delta_velocity) AS t "
        "ON CONFLICT (store_id, category, target_price_bucket) DO UPDATE "
        "SET user_waitlist_count = retailer_analytics.user_waitlist_count + "
        "EXCLUDED.user_waitlist_count, "
        "demand_velocity = retailer_analytics.demand_velocity + "
        "EXCLUDED.demand_velocity, last_updated = now();"
    )

    await conn.execute(
        sql, store_ids, categories, buckets, delta_counts, delta_velocities
    )
