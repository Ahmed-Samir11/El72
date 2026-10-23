import sys
sys.path.insert(0, "e:/repos/El72")
from playwright.sync_api import sync_playwright

url = "https://alfrensia.com/en/product/asus-a23-micro-atx-support-hatsune-miku-white-edition-micro-tower-case/"
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    page = ctx.new_page()
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    try:
        page.wait_for_timeout(3000)
    except Exception:
        pass
    html = page.content()
    ctx.close()
    browser.close()

open("search_debug/alfrensia_real.html", "w", encoding="utf-8").write(html)
print("len:", len(html))
print(html[:1500])
