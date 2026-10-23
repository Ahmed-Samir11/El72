import sys
sys.path.insert(0, "e:/repos/El72")
from playwright.sync_api import sync_playwright
from services.api.price_fetcher import (
    _extract_price_from_html,
    _jsonld_title,
    _jsonld_image,
    _extract_meta,
)

url = "https://alfrensia.com/en/product/asus-a23-micro-atx-support-hatsune-miku-white-edition-micro-tower-case/"
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    page = ctx.new_page()
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    try:
        page.wait_for_timeout(2000)
    except Exception:
        pass
    html = page.content()
    ctx.close()
    browser.close()

print("html len:", len(html))
print("price:", _extract_price_from_html(html))
print("title:", _jsonld_title(html))
print("image:", _jsonld_image(html))
print("og:title:", _extract_meta(html, "og:title"))
print("og:image:", _extract_meta(html, "og:image"))
