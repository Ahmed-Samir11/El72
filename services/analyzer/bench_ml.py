"""Benchmark ML scorers (MAD vs IsolationForest) for different window sizes.

Run to compare latency of the default MAD scorer vs sklearn IsolationForest (offloaded).
Example:
    python -m services.analyzer.bench_ml --sizes 20 100 500 --iters 20
"""

import argparse
import asyncio
import time

import numpy as np

from services.analyzer import ml_detector


def bench_sync_mad(window):
    start = time.perf_counter()
    s = ml_detector.score_prices(window, method="mad")
    return time.perf_counter() - start, s


def bench_sync_isolation(window):
    start = time.perf_counter()
    s = ml_detector.score_prices(window, method="isolation")
    return time.perf_counter() - start, s


async def bench_async_isolation(window):
    start = time.perf_counter()
    s = await ml_detector.score_prices_async(window, method="isolation")
    return time.perf_counter() - start, s


def run_bench(sizes, iters):
    for n in sizes:
        window = np.random.normal(loc=100.0, scale=5.0, size=n)
        # MAD (sync)
        times = []
        for _ in range(iters):
            t, _ = bench_sync_mad(window)
            times.append(t)
        avg = sum(times) / len(times)
        mn = min(times)
        mx = max(times)
        print(f"MAD size={n}: avg={avg:.6f}s min={mn:.6f}s max={mx:.6f}s")

        # Isolation (sync) - may be slow
        times = []
        for _ in range(iters):
            t, _ = bench_sync_isolation(window)
            times.append(t)
        avg = sum(times) / len(times)
        mn = min(times)
        mx = max(times)
        print(f"Isolation size={n}: avg={avg:.6f}s min={mn:.6f}s max={mx:.6f}s")

        # Isolation (async offloaded)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        times = []
        for _ in range(iters):
            t, _ = loop.run_until_complete(bench_async_isolation(window))
            times.append(t)
        avg = sum(times) / len(times)
        mn = min(times)
        mx = max(times)
        print(f"Isolation(async) size={n}: avg={avg:.6f}s min={mn:.6f}s max={mx:.6f}s")
        loop.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="+",
        default=[20, 100, 500],
        help="window sizes to test",
    )
    parser.add_argument("--iters", type=int, default=10, help="iterations per size")
    args = parser.parse_args()
    run_bench(args.sizes, args.iters)


if __name__ == "__main__":
    main()
