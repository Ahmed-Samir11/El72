"""Debug search selectors - simplified version."""

import asyncio
import os
from playwright.async_api import async_playwright

async def debug_search_selectors():
    stores = {
        "amazon_eg": "https://www.amazon.eg/s?k=ASUS+PRIME+RTX+5070+Ti",
        "elbadrgroup": "https://elbadrgroupeg.store/search?search=ASUS+PRIME+RTX+5070+Ti",
        "noon": "https://www.noon.com/egypt-en/search?q=ASUS+PRIME+RTX+5070+Ti",
        "jumia": "https://www.jumia.com.eg/catalog/?q=ASUS+PRIME+RTX+5070+Ti",
    }
    
    os.makedirs("search_debug", exist_ok=True)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        for store_id, search_url in stores.items():
            print(f"\nDEBUGGING: {store_id}")
            print(f"URL: {search_url}")
            
            page = await browser.new_page()
            try:
                await page.goto(search_url, timeout=30000)
                await page.wait_for_timeout(3000)
                
                # Save HTML for inspection
                html = await page.content()
                with open(f"search_debug/{store_id}_search.html", "w", encoding="utf-8") as f:
                    f.write(html)
                
                # Test selectors
                test_selectors = {
                    "amazon_eg": [
                        "a[data-component-type='s-search-result']",
                        ".s-asin a",
                        "h2 a",
                        "a[href*='/dp/']",
                    ],
                    "elbadrgroup": [
                        "a.product-name",
                        ".product-item a",
                        "h2 a",
                        "a[href*='/asus']",
                    ],
                    "noon": [
                        "a[data-qa='product-link']",
                        ".productCard a",
                        "a[href*='/p/']",
                        "h2 a",
                    ],
                    "jumia": [
                        "a.core",
                        ".product a",
                        "a[href*='/p/']",
                        "h2 a",
                    ],
                }
                
                selectors = test_selectors.get(store_id, ["a", "h2", "h3"])
                print(f"Testing selectors:")
                for selector in selectors:
                    try:
                        element = await page.query_selector(selector)
                        if element:
                            href = await element.get_attribute("href")
                            text = (await element.inner_text())[:50]
                            print(f"  OK: {selector}")
                            print(f"    Text: {text}")
                            print(f"    Href: {href[:60]}")
                        else:
                            print(f"  NO: {selector}")
                    except Exception as e:
                        print(f"  ERR: {selector}")
                        
            except Exception as e:
                print(f"ERROR: {e}")
            finally:
                await page.close()
        
        await browser.close()
    
    print("\nHTML files saved to search_debug/")

asyncio.run(debug_search_selectors())
