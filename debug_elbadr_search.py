from playwright.async_api import async_playwright
import asyncio

async def debug():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        search_url = 'https://elbadrgroupeg.store/search?search=ASUS+Prime+GeForce+RTX+5070+Ti'
        await page.goto(search_url, timeout=20000)
        
        # Try different wait times
        for wait_time in [1000, 2000, 3000, 5000]:
            print(f"\n--- Waiting {wait_time}ms ---")
            await page.wait_for_timeout(wait_time)
            
            # Check for product results with different selectors
            selectors_to_try = [
                ".name a[href]",
                ".name a",
                "a.product-name",
                ".product-item a",
                "div.product",
                ".product-box a"
            ]
            
            for selector in selectors_to_try:
                try:
                    results = await page.query_selector_all(selector)
                    if results:
                        first = results[0]
                        text = await first.inner_text()
                        href = await first.get_attribute('href')
                        print(f"  {selector}: Found {len(results)} - First: '{text[:50]}...'")
                except Exception as e:
                    pass
        
        # Save HTML for manual inspection
        with open('elbadr_search_debug.html', 'w', encoding='utf-8') as f:
            f.write(await page.content())
        
        await browser.close()
        print("\nHTML saved to elbadr_search_debug.html")

asyncio.run(debug())
