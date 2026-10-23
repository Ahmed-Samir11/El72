import re, json

html = open("search_debug/compumarts_price.html", encoding="utf-8").read()

# Find all ld+json script blocks
blocks = re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.DOTALL)
print("num ld+json blocks:", len(blocks))
for i, b in enumerate(blocks):
    b = b.strip()
    print(f"--- block {i} (len {len(b)}) ---")
    print(b[:600])
    print()
