import sys
print("=== playwright import ===")
try:
    from playwright.sync_api import sync_playwright
    print("playwright importable")
except Exception as e:
    print("playwright NOT importable:", e)
    sys.exit(0)

print("=== try browser fetch of alfrensia ===")
try:
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
            print("chromium launched OK")
        except Exception as e:
            print("chromium launch FAILED:", str(e)[:300])
            sys.exit(0)
        ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = ctx.new_page()
        page.goto("https://alfrensia.com/en/product/asus-tuf-gaming-f15-rtx-4060-laptop/", timeout=30000, wait_until="domcontentloaded")
        try:
            page.wait_for_timeout(2000)
        except Exception:
            pass
        html = page.content()
        print("browser html len:", len(html))
        open("search_debug/alfrensia_browser.html", "w", encoding="utf-8").write(html)
        ctx.close()
        browser.close()
except Exception as e:
    print("browser fetch error:", str(e)[:300])
