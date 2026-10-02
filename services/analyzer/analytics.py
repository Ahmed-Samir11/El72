"""Persistence helpers for the TimescaleDB analytical fact constellation."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from statistics import mean
from typing import Any, Sequence


async def _dimension_key(
    conn: Any,
    table: str,
    key_column: str,
    lookup_sql: str,
    lookup_values: tuple[Any, ...],
    insert_sql: str,
    insert_values: tuple[Any, ...],
) -> int:
    """Return an existing dimension key or insert a conformed dimension row."""
    row = await conn.fetchrow(lookup_sql, *lookup_values)
    if row:
        return int(row[key_column])
    row = await conn.fetchrow(insert_sql, *insert_values)
    if not row:
        raise RuntimeError(f"Unable to create analytics dimension row in {table}")
    return int(row[key_column])


def _date_key(evaluated_at: datetime) -> int:
    """Build the warehouse YYYYMMDD date key."""
    return int(evaluated_at.strftime("%Y%m%d"))


async def record_deal_evaluation(
    conn: Any,
    *,
    sku: str,
    store: str,
    price: float,
    prices: Sequence[float],
    score: float,
    evaluated_at: datetime | None = None,
    classification: str = "genuine_deal",
    model_version: str = "mad-v1",
) -> int:
    """Persist a deal evaluation derived from the observed price window.

    The price history remains the evidence source. This function stores only the
    analytical result and the summary statistics used to reach it.
    """
    evaluated_at = evaluated_at or datetime.now(timezone.utc)
    historical = [float(value) for value in prices if value is not None]
    historical_avg = mean(historical) if historical else price
    historical_min = min(historical) if historical else price
    historical_max = max(historical) if historical else price
    historical_discount = (
        ((historical_avg - price) / historical_avg) * 100
        if historical_avg
        else 0.0
    )

    product_key = await _dimension_key(
        conn,
        "dim_product",
        "product_key",
        """SELECT product_key FROM analytics.dim_product
           WHERE source_system = 'el72' AND source_product_id = $1
             AND is_current = TRUE
           ORDER BY product_key LIMIT 1""",
        (sku,),
        """INSERT INTO analytics.dim_product
           (source_product_id, name)
           VALUES ($1, $1)
           RETURNING product_key""",
        (sku,),
    )
    retailer_key = await _dimension_key(
        conn,
        "dim_retailer",
        "retailer_key",
        "SELECT retailer_key FROM analytics.dim_retailer WHERE source_retailer_id = $1",
        (store,),
        """INSERT INTO analytics.dim_retailer (source_retailer_id, name)
           VALUES ($1, $1)
           ON CONFLICT (source_retailer_id) DO UPDATE SET name = EXCLUDED.name
           RETURNING retailer_key""",
        (store,),
    )
    date_key = _date_key(evaluated_at)
    await conn.execute(
        """INSERT INTO analytics.dim_date
           (date_key, full_date, day, day_of_week, week, month, month_name, quarter, year)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
           ON CONFLICT (date_key) DO NOTHING""",
        date_key,
        evaluated_at.date(),
        evaluated_at.day,
        evaluated_at.isoweekday(),
        evaluated_at.isocalendar().week,
        evaluated_at.month,
        evaluated_at.strftime("%B"),
        ((evaluated_at.month - 1) // 3) + 1,
        evaluated_at.year,
    )
    row = await conn.fetchrow(
        """INSERT INTO analytics.fact_deal
           (evaluated_at, product_key, retailer_key, date_key, current_price,
            historical_avg_price, historical_min_price, historical_max_price,
            historical_discount_percentage, deal_score, classification, model_version)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
           RETURNING deal_key""",
        evaluated_at,
        product_key,
        retailer_key,
        date_key,
        Decimal(str(price)),
        Decimal(str(round(historical_avg, 2))),
        Decimal(str(round(historical_min, 2))),
        Decimal(str(round(historical_max, 2))),
        Decimal(str(round(historical_discount, 4))),
        Decimal(str(round(score, 4))),
        classification,
        model_version,
    )
    if not row:
        raise RuntimeError("Unable to persist analytics fact_deal row")
    return int(row["deal_key"])


async def record_price_observation(
    conn: Any,
    *,
    sku: str,
    store: str,
    price: float,
    price_usd: float | None = None,
    in_stock: bool = True,
    observed_at: datetime | None = None,
) -> None:
    """Project one persisted price observation into the analytical fact."""
    observed_at = observed_at or datetime.now(timezone.utc)
    product_key = await _dimension_key(
        conn,
        "dim_product",
        "product_key",
        """SELECT product_key FROM analytics.dim_product
           WHERE source_system = 'el72' AND source_product_id = $1
             AND is_current = TRUE
           ORDER BY product_key LIMIT 1""",
        (sku,),
        """INSERT INTO analytics.dim_product (source_product_id, name)
           VALUES ($1, $1) RETURNING product_key""",
        (sku,),
    )
    retailer_key = await _dimension_key(
        conn,
        "dim_retailer",
        "retailer_key",
        "SELECT retailer_key FROM analytics.dim_retailer WHERE source_retailer_id = $1",
        (store,),
        """INSERT INTO analytics.dim_retailer (source_retailer_id, name)
           VALUES ($1, $1)
           ON CONFLICT (source_retailer_id) DO UPDATE SET name = EXCLUDED.name
           RETURNING retailer_key""",
        (store,),
    )
    date_key = _date_key(observed_at)
    time_key = (
        observed_at.hour * 10000 + observed_at.minute * 100 + observed_at.second
    )
    await conn.execute(
        """INSERT INTO analytics.dim_date
           (date_key, full_date, day, day_of_week, week, month, month_name, quarter, year)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
           ON CONFLICT (date_key) DO NOTHING""",
        date_key,
        observed_at.date(),
        observed_at.day,
        observed_at.isoweekday(),
        observed_at.isocalendar().week,
        observed_at.month,
        observed_at.strftime("%B"),
        ((observed_at.month - 1) // 3) + 1,
        observed_at.year,
    )
    await conn.execute(
        """INSERT INTO analytics.dim_time
           (time_key, hour, minute, second, time_period)
           VALUES ($1, $2, $3, $4,
                   CASE WHEN $2 < 12 THEN 'morning'
                        WHEN $2 < 18 THEN 'afternoon' ELSE 'evening' END)
           ON CONFLICT (time_key) DO NOTHING""",
        time_key,
        observed_at.hour,
        observed_at.minute,
        observed_at.second,
    )
    await conn.execute(
        """INSERT INTO analytics.fact_price_history
           (observed_at, product_key, retailer_key, date_key, time_key,
            observed_price, currency, availability, source_sku, source_timestamp)
           VALUES ($1, $2, $3, $4, $5, $6, 'EGP', $7, $8, $1)
           ON CONFLICT (observed_at, price_history_key) DO NOTHING""",
        observed_at,
        product_key,
        retailer_key,
        date_key,
        time_key,
        Decimal(str(price)),
        in_stock,
        sku,
    )