"""Debug ElBadrGroup page structure to identify correct selectors."""

import asyncio
from playwright.async_api import async_playwright

url = "http://elbadrgroupeg.store/asus-prime-geforce-rtx-5070-ti?search=asus%20prime%205070%20ti"

async def debug_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await page.goto(url)
        await page.wait_for_timeout(2000)  # Wait for JS to load
        
        # Get all text containing "EGP" or "Price" or numbers
        print("=== Page Title ===")
        title = await page.title()
        print(title)
        
        print("\n=== Looking for price elements ===")
        # Try to find anything with prices
        price_elements = await page.query_selector_all("[data-price], .price, #price, [class*='price'], [class*='Price']")
        print(f"Found {len(price_elements)} elements with price-like class/id")
        
        # Print page content (limited) and search for price patterns
        print("\n=== Full page HTML ===")
        content = await page.content()
        # Look for price-related text
        if "EGP" in content:
            idx = content.find("EGP")
            print(f"...{content[max(0, idx-500):min(len(content), idx+500)]}...")
        # Also search for currency formatting
        import re
        prices = re.findall(r'[\d,]+(?:\.\d+)?\s*(?:EGP|egp|£|$)', content)
        print(f"\nFound prices: {prices[:5]}")
        
        # Dump structure around price
        print("\n=== Looking for price data attributes ===")
        all_html = await page.content()
        # Find lines with price-like attributes
        lines = all_html.split('\n')
        for i, line in enumerate(lines):
            if 'price' in line.lower() or 'egp' in line.lower():
                print(f"Line {i}: {line[:200]}")
        
        # Try each selector from the scraper
        selectors = [
            "meta[itemprop='price']",
            "span.price-item.price-item--regular",
            "div.price__regular .price-item--regular",
            ".price .price-item",
            "span.money",
            "[data-product-price]",
            "span.price",
            ".product__price .price",
            "#price",
        ]
        
        print("\n=== Testing selectors ===")
        for sel in selectors:
            el = await page.query_selector(sel)
            if el:
                try:
                    txt = await el.inner_text() if await page.query_selector(sel) else "N/A"
                except:
                    txt = "error"
                print(f"  {sel}: FOUND - text='{txt}'")
            else:
                print(f"  {sel}: NOT FOUND")
        
        await browser.close()

asyncio.run(debug_page())
