"""Simple benchmark to simulate scrape worker concurrency and measure throughput.

This script runs `num_tasks` simulated scrape tasks with a configured `simulated_latency`
and measures total time to complete. Use it to tune `SCRAPER_CONCURRENCY` and
`BROWSER_POOL_SIZE` before running real Playwright-based runs.

Example:
    python -m services.scraper.bench --num 100 --concurrency 8 --latency 1.5
"""
import argparse
import asyncio
import time


async def simulated_fetch(latency: float):
    await asyncio.sleep(latency)
    return True


async def run_benchmark(num_tasks: int, concurrency: int, latency: float):
    sem = asyncio.Semaphore(concurrency)

    async def worker(i):
        async with sem:
            await simulated_fetch(latency)

    tasks = [asyncio.create_task(worker(i)) for i in range(num_tasks)]
    start = time.perf_counter()
    await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - start
    print(f"Completed {num_tasks} tasks with concurrency={concurrency} latency={latency}s in {elapsed:.2f}s")
    print(f"Throughput: {num_tasks/elapsed:.2f} ops/sec")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--num", type=int, default=100, help="total simulated tasks")
    parser.add_argument("--concurrency", type=int, default=4, help="concurrency")
    parser.add_argument("--latency", type=float, default=1.0, help="simulated latency per task (s)")
    args = parser.parse_args()

    asyncio.run(run_benchmark(args.num, args.concurrency, args.latency))


if __name__ == "__main__":
    main()
