import re, requests

h = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
u = "https://www.compumarts.com/collections/monitors/products/lenovo-legion-r27qe-gaming-monitor-27-inch-2560x1440-displayhdr-400-ips-panel-technology-200hz-refresh-rate-0-5ms-response-time"
html = requests.get(u, headers=h, timeout=30).text
open("search_debug/compumarts_price.html", "w", encoding="utf-8").write(html)
print("saved", len(html))

print("=== JSON-LD price occurrences ===")
for m in re.finditer(r'"price"\s*:\s*"?([\d,]+(?:\.\d+)?)"?', html):
    s = max(0, m.start() - 80)
    print("PRICE:", repr(html[s:m.end() + 30]))

print("=== meta price tags ===")
for m in re.finditer(r'<meta[^>]+(?:property|name)=["\'][^"\']*price[^"\']*["\'][^>]*>', html, re.IGNORECASE):
    print("META:", m.group(0)[:200])

print("=== visible-text EGP matches (first 10) ===")
text = re.sub(r"<[^>]+>", " ", html)
for m in list(re.finditer(r"([\d][\d,]{2,}(?:\.\d{1,2})?)\s*(?:EGP|ج\.م|جنيه|£|pound)", text, re.IGNORECASE))[:10]:
    print("TXT:", m.group(0))
