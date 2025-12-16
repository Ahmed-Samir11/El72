"""Offline trainer for IsolationForest model.

Usage:
  - From DB: set `DATABASE_URL` env and run without args to build training windows from `price_history`.
  - Output: saves model to `models/isolation-<timestamp>.joblib` and writes metadata.

This is an offline utility and should be run on a machine with access to the TimescaleDB instance.
"""
import os
import json
import time
from argparse import ArgumentParser
from datetime import datetime

import joblib
import numpy as np
import asyncpg
from sklearn.ensemble import IsolationForest


def build_windows_from_series(series, window_size=20, step=1):
    windows = []
    for i in range(0, len(series) - window_size + 1, step):
        w = series[i : i + window_size]
        windows.append(w)
    return np.array(windows)


async def fetch_price_series(database_url: str):
    conn = await asyncpg.connect(database_url)
    rows = await conn.fetch("SELECT sku, store_id, price_egp, extract(epoch from time) as ts FROM price_history ORDER BY sku, store_id, time")
    await conn.close()
    # group by sku|store
    groups = {}
    for r in rows:
        key = f"{r['sku']}|{r['store_id']}"
        groups.setdefault(key, []).append(float(r['price_egp']))
    return groups


async def main_async(database_url: str, window_size: int, out_dir: str):
    groups = await fetch_price_series(database_url)
    X = []
    for key, series in groups.items():
        if len(series) < window_size:
            continue
        windows = build_windows_from_series(series, window_size=window_size, step=1)
        X.append(windows)
    if not X:
        raise RuntimeError("No training windows found; ensure your DB contains price_history with enough samples")
    X = np.vstack(X)
    print(f"Training on {len(X)} windows of size {window_size}")
    model = IsolationForest(contamination=0.05, random_state=42)
    model.fit(X)

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"isolation-{ts}.joblib")
    joblib.dump(model, path)
    meta = {"path": path, "trained_at": ts, "window_size": window_size}
    with open(os.path.join(out_dir, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)
    print("Saved model to", path)


def main():
    p = ArgumentParser()
    p.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="Postgres/Timescale DB URL")
    p.add_argument("--window-size", type=int, default=20)
    p.add_argument("--out-dir", default="models")
    args = p.parse_args()
    if not args.database_url:
        raise SystemExit("Provide DATABASE_URL env or --database-url")
    import asyncio

    asyncio.run(main_async(args.database_url, args.window_size, args.out_dir))


if __name__ == "__main__":
    main()
