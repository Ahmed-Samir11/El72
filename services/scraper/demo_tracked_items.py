"""Example usage and demo of the tracked item monitoring system.

This script demonstrates:
1. Creating tracked items
2. Adding store mappings
3. Running a scraping cycle
4. Querying prices and alerts
"""

import asyncio
import asyncpg
from services.common.redis_client import RedisStreamClient
from services.scraper.tracked_item_monitor import TrackedItemMonitor
from services.scraper.browser_pool import BrowserPool
from playwright.async_api import async_playwright


async def setup_example_data(db_pool: asyncpg.Pool):
    """Create example tracked items in the database."""
    async with db_pool.acquire() as conn:
        # Create a test user (if not exists)
        user_id = await conn.fetchval("""
            INSERT INTO users (phone, password_hash, salt, tier)
            VALUES ('+201234567890', 'hash', 'salt', 'free')
            ON CONFLICT (phone) DO UPDATE SET phone = EXCLUDED.phone
            RETURNING id
        """)
        
        print(f"✅ Created/found test user with ID: {user_id}")
        
        # Create tracked item for Logitech Mouse
        tracked_item_id = await conn.fetchval("""
            INSERT INTO tracked_items (
                user_id, canonical_product_id, target_price, is_active
            )
            VALUES ($1, $2, $3, TRUE)
            RETURNING id
        """, user_id, "logitech-m185-wireless-mouse", 250.00)
        
        print(f"✅ Created tracked item ID: {tracked_item_id}")
        
        # Add Amazon Egypt store mapping
        await conn.execute("""
            INSERT INTO tracked_item_stores (
                tracked_item_id, store_id, store_sku, store_url, is_active
            )
            VALUES ($1, $2, $3, $4, TRUE)
            ON CONFLICT (tracked_item_id, store_id, store_sku) DO NOTHING
        """, 
            tracked_item_id,
            "amazon_eg",
            "B0746NKVBN",
            "https://www.amazon.eg/-/en/Logitech-Wireless-Mouse-Battery-Charcoal/dp/B0746NKVBN/"
        )
        
        print("✅ Added Amazon Egypt store mapping")
        
        # Add Noon store mapping (example - URL may not be real)
        await conn.execute("""
            INSERT INTO tracked_item_stores (
                tracked_item_id, store_id, store_sku, store_url, is_active
            )
            VALUES ($1, $2, $3, $4, TRUE)
            ON CONFLICT (tracked_item_id, store_id, store_sku) DO NOTHING
        """,
            tracked_item_id,
            "noon",
            "N12345",
            "https://www.noon.com/egypt-en/logitech-m185-wireless-mouse/N12345/p"
        )
        
        print("✅ Added Noon store mapping")
        
        return user_id, tracked_item_id


async def run_single_cycle_demo():
    """Run a single scraping cycle and show results."""
    print("\n" + "="*70)
    print("🚀 TRACKED ITEM MONITORING DEMO")
    print("="*70 + "\n")
    
    # Configuration
    DATABASE_URL = "postgresql://elhaq:elhaq_pass@localhost:5432/elhaq"
    REDIS_URL = "redis://localhost:6379"
    
    # Initialize connections
    print("📡 Connecting to database and Redis...")
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
    redis_client = await RedisStreamClient.create(REDIS_URL)
    
    try:
        # Setup example data
        print("\n📝 Setting up example tracked items...")
        user_id, tracked_item_id = await setup_example_data(db_pool)
        
        # Initialize browser pool
        print("\n🌐 Starting browser pool...")
        async with async_playwright() as playwright:
            browser_pool = BrowserPool(playwright, max_browsers=2)
            await browser_pool.start()
            
            # Create monitor
            monitor = TrackedItemMonitor(
                db_pool=db_pool,
                redis_client=redis_client,
                browser_pool=browser_pool,
                scrape_interval=30,
                max_concurrent_scrapes=5
            )
            
            # Run ONE scrape cycle
            print("\n🔍 Running scrape cycle (this may take 30-60 seconds)...\n")
            await monitor.scrape_cycle()
            
            # Query results
            print("\n📊 RESULTS:")
            print("-" * 70)
            
            # Get current prices
            async with db_pool.acquire() as conn:
                prices = await conn.fetch("""
                    SELECT
                        ti.canonical_product_id,
                        cp.store_id,
                        cp.price_local,
                        cp.currency,
                        cp.in_stock,
                        cp.last_updated
                    FROM current_prices cp
                    JOIN tracked_items ti ON cp.tracked_item_id = ti.id
                    WHERE ti.id = $1
                    ORDER BY cp.price_usd ASC
                """, tracked_item_id)
                
                if prices:
                    print("\n💰 Current Prices:")
                    for price in prices:
                        stock_icon = "✅" if price["in_stock"] else "❌"
                        print(f"  {stock_icon} {price['store_id']}: "
                              f"{price['price_local']} {price['currency']} "
                              f"(Updated: {price['last_updated']})")
                else:
                    print("\n⚠️  No prices found (scraping may have failed)")
                
                # Get lowest price
                lowest = await conn.fetchrow("""
                    SELECT
                        store_id,
                        price_local,
                        currency,
                        url
                    FROM lowest_prices
                    WHERE tracked_item_id = $1
                """, tracked_item_id)
                
                if lowest:
                    print(f"\n🏆 Best Deal:")
                    print(f"  Store: {lowest['store_id']}")
                    print(f"  Price: {lowest['price_local']} {lowest['currency']}")
                    print(f"  URL: {lowest['url']}")
                else:
                    print("\n⚠️  No lowest price available")
            
            # Check alerts stream
            print("\n🔔 Recent Alerts:")
            raw_redis = redis_client.redis
            messages = await raw_redis.xrevrange("stream:alerts", count=5)
            
            if messages:
                for msg_id, fields in messages:
                    import json
                    payload = json.loads(fields[b"payload"])
                    print(f"  - {payload['alert_type']}: "
                          f"Item {payload['tracked_item_id']}, "
                          f"Store {payload['store_id']}, "
                          f"Price: {payload['new_price_local']} {payload['currency']}")
            else:
                print("  (No alerts emitted)")
            
            # Cleanup
            await browser_pool.close()
        
        print("\n" + "="*70)
        print("✅ Demo completed successfully!")
        print("="*70)
        
        print("\n💡 Tips:")
        print("  - Run the monitor continuously: python -m services.scraper.tracked_item_monitor")
        print("  - Check stream:alerts for real-time price change notifications")
        print("  - Query lowest_prices table for current best deals")
        print("  - Add more stores by implementing BaseScraper")
        
    finally:
        await redis_client.close()
        await db_pool.close()


async def query_tracked_items_demo():
    """Demo: Query tracked items and their prices."""
    DATABASE_URL = "postgresql://elhaq:elhaq_pass@localhost:5432/elhaq"
    
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    
    try:
        async with db_pool.acquire() as conn:
            # Get all tracked items with their best prices
            items = await conn.fetch("""
                SELECT
                    ti.id,
                    ti.canonical_product_id,
                    ti.target_price,
                    lp.store_id AS best_store,
                    lp.price_local AS best_price,
                    lp.currency,
                    lp.url AS best_url,
                    COUNT(tis.id) AS store_count
                FROM tracked_items ti
                LEFT JOIN lowest_prices lp ON ti.id = lp.tracked_item_id
                LEFT JOIN tracked_item_stores tis ON ti.id = tis.tracked_item_id
                WHERE ti.is_active = TRUE
                GROUP BY ti.id, lp.store_id, lp.price_local, lp.currency, lp.url
            """)
            
            print("\n📋 All Tracked Items:")
            print("-" * 70)
            
            for item in items:
                print(f"\n  Product: {item['canonical_product_id']}")
                print(f"  Tracking {item['store_count']} stores")
                if item['best_price']:
                    print(f"  🏆 Best Deal: {item['best_price']} {item['currency']} "
                          f"at {item['best_store']}")
                else:
                    print(f"  ⚠️  No prices available yet")
                if item['target_price']:
                    print(f"  🎯 Target Price: {item['target_price']}")
    
    finally:
        await db_pool.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "query":
        # Just query existing data
        asyncio.run(query_tracked_items_demo())
    else:
        # Run full demo with scraping
        print("\n⚠️  WARNING: This demo will scrape live websites!")
        print("Make sure your database and Redis are running.")
        print("Press Ctrl+C to cancel...\n")
        
        try:
            import time
            time.sleep(3)
            asyncio.run(run_single_cycle_demo())
        except KeyboardInterrupt:
            print("\n\n❌ Demo cancelled by user")
