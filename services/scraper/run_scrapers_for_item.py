"""Run store scrapers for a single product and print results.

Usage examples:

# By product name (searches each store automatically)
python -m services.scraper.run_scrapers_for_item \
  --product "ASUS PRIME RTX 5070 Ti" \
  --store elbadrgroup \
  --store amazon_eg

# By exact product URL (legacy mode)
python -m services.scraper.run_scrapers_for_item \
  --canonical-id "asus-prime-rtx-5070-ti" \
  --store elbadrgroup=https://elbadrgroupeg.store/asus-prime-geforce-rtx-5070-ti \
  --store amazon_eg=https://www.amazon.eg/-/en/ASUS-Prime-GeForce-GDDR7-Graphics/dp/B0DVGVZZYY

# Optional: save screenshots to a folder for debugging
python -m services.scraper.run_scrapers_for_item \
  --product "ASUS PRIME RTX 5070 Ti" \
  --screenshot-dir screenshots \
  --store elbadrgroup \
  --store amazon_eg

Notes:
- You can either provide --product (for auto-search) OR store=url pairs (for exact URLs)
- Headless Chromium is used; ensure Playwright browsers are installed:
    python -m playwright install chromium
"""

import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import Dict, Optional

from playwright.async_api import async_playwright

from services.scraper.store_scrapers import ScraperFactory


@dataclass
class RunResult:
    store_id: str
    ok: bool
    error: Optional[str]
    payload: Optional[dict]
    screenshot_path: Optional[str]


async def run_for_store(playwright, store_id: str, url_or_query: str, canonical_id: str, screenshot_dir: Optional[str]) -> RunResult:
    scraper = ScraperFactory.get_scraper(store_id)
    if not scraper:
        return RunResult(store_id, False, f"Unsupported store_id: {store_id}", None, None)

    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context()
    page = await context.new_page()
    screenshot_path = None

    try:
        # url_or_query can be either a URL or a product name/query
        result = await scraper.scrape(page, url_or_query, canonical_id)
        if not result:
            # Try screenshot if requested
            if screenshot_dir:
                os.makedirs(screenshot_dir, exist_ok=True)
                screenshot_path = os.path.join(screenshot_dir, f"{store_id}.png")
                try:
                    await page.screenshot(path=screenshot_path, full_page=True)
                except Exception:
                    screenshot_path = None
            return RunResult(store_id, False, "Scrape returned no result", None, screenshot_path)

        data = result.to_dict()
        return RunResult(store_id, True, None, data, screenshot_path)

    except Exception as e:
        if screenshot_dir:
            os.makedirs(screenshot_dir, exist_ok=True)
            screenshot_path = os.path.join(screenshot_dir, f"{store_id}.png")
            try:
                await page.screenshot(path=screenshot_path, full_page=True)
            except Exception:
                screenshot_path = None
        return RunResult(store_id, False, str(e), None, screenshot_path)
    finally:
        try:
            await page.close()
        finally:
            await context.close()
            await browser.close()


async def main():
    p = argparse.ArgumentParser(description="Run store scrapers for a product")
    p.add_argument("--product", help="Product name/query to search for (auto-searches all stores)")
    p.add_argument("--canonical-id", help="Canonical product identifier; auto-generated from product name if not provided")
    p.add_argument("--store", action="append", default=[], help="Store to scrape from. Either just store_id (for search mode) or store_id=url (for direct URL). Repeatable.")
    p.add_argument("--screenshot-dir", help="Directory to save screenshots for failed scrapes")
    args = p.parse_args()

    # Determine mode: search vs. direct URL
    if args.product:
        # Search mode: --product "product name" --store store1 --store store2
        if not args.store:
            raise SystemExit("Provide at least one --store argument")
        
        # Validate stores (should not have = in search mode)
        store_ids = []
        for store in args.store:
            if "=" in store:
                raise SystemExit(f"In search mode, use --store store_id (not store_id=url): {store}")
            store_ids.append(store)
        
        canonical_id = args.canonical_id or args.product.lower().replace(" ", "-")
        product_query = args.product
        
        print("Running scrapers in SEARCH mode:")
        print(f"  Product: {product_query}")
        print(f"  Canonical ID: {canonical_id}")
        for sid in store_ids:
            print(f"  - {sid}")

        async with async_playwright() as playwright:
            tasks = [
                run_for_store(playwright, sid, product_query, canonical_id, args.screenshot_dir)
                for sid in store_ids
            ]
            results = await asyncio.gather(*tasks)
    
    elif args.store:
        # Direct URL mode: --canonical-id "id" --store store_id=url --store store_id=url
        store_map: Dict[str, str] = {}
        for entry in args.store:
            if "=" not in entry:
                raise SystemExit(f"In direct URL mode, use --store store_id=url (not just store_id): {entry}")
            sid, url = entry.split("=", 1)
            sid = sid.strip()
            url = url.strip()
            if not sid or not url:
                raise SystemExit(f"Invalid --store value: {entry} (empty id or url)")
            store_map[sid] = url

        canonical_id = args.canonical_id or "unknown-product"
        
        print("Running scrapers in DIRECT URL mode:")
        print(f"  Canonical ID: {canonical_id}")
        for sid, url in store_map.items():
            print(f"  - {sid}: {url}")

        async with async_playwright() as playwright:
            tasks = [
                run_for_store(playwright, sid, url, canonical_id, args.screenshot_dir)
                for sid, url in store_map.items()
            ]
            results = await asyncio.gather(*tasks)
    
    else:
        raise SystemExit("Provide either --product or --store arguments")

    print("\nResults:\n--------")
    any_ok = False
    for r in results:
        if r.ok:
            any_ok = True
            print(f"[{r.store_id}] OK")
            payload = r.payload or {}
            print(f"  Price:    {payload.get('price')} {payload.get('currency')}")
            print(f"  In stock: {payload.get('in_stock')}")
            print(f"  Title:    {payload.get('title')}")
            print(f"  URL:      {payload.get('url')}")
            print(f"  Time:     {payload.get('timestamp')}")
        else:
            print(f"[{r.store_id}] FAILED: {r.error}")
            if r.screenshot_path:
                print(f"  Saved screenshot: {r.screenshot_path}")

    if not any_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
