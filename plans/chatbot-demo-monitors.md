# Chatbot Demo: 2K Monitors Under 12,000 EGP

## Test Prompt (Egyptian Arabic)
> **User types:** `عايز شاشات 2k بسعر أقل من 12 ألف`

## What Happens (End-to-End)

### Step 1: LLM Intent Extraction
The chatbot's LLM (Nemotron 74B via llama-server) parses the Arabic message:

| Field | Value |
|-------|-------|
| **query** | `2K monitor` |
| **max_price** | `12000` |
| **language** | `ar` |

### Step 2: Store Search
The chatbot searches across stores with the English query "2K monitor" and price filter ≤12,000 EGP:

| Store | Status |
|-------|--------|
| Amazon Egypt | ✅ Accessible |
| Sigma Computer | ✅ Accessible |
| 2B Egypt | ✅ Accessible |
| Noon | ⚠️ Anti-bot (HTTP2) |
| Jumia | ⚠️ Cloudflare challenge |
| ElBadrGroup | ⚠️ Connection refused |
| EgyPrice | ⚠️ DNS resolution |

### Step 3: Bot Response (Egyptian Arabic)

**Message text:**
```
لقيت 4 منتج لـ "2K monitor" بأقل من 12000 جنيه:
```

**Search results (displayed as cards below the message):**

| # | Product | Price | Store | Add to Feed |
|---|---------|-------|-------|-------------|
| 1 | LG 27 Inch 2K QHD IPS Monitor | 8,999 EGP | Amazon Egypt | [Add to Feed] |
| 2 | Samsung 27 Inch 2K QHD Monitor | 9,499 EGP | Sigma Computer | [Add to Feed] |
| 3 | Philips 24 Inch 2K Monitor | 7,599 EGP | 2B Egypt | [Add to Feed] |
| 4 | Dell 24 Inch 2K Monitor | 11,299 EGP | Amazon Egypt | [Add to Feed] |

### Step 4: User Taps "Add to Feed"

**Bot responds (Arabic):**
```
تمام! أضفت "LG 27 Inch 2K QHD IPS Monitor" للمتابعة. هنبلغك لما السعر يتغير 👍
```

**SnackBar appears:**
```
Tracker created for "LG 27 Inch 2K QHD IPS Monitor". You will be notified on price changes.
```

## How to Test on Your Device

1. **Open the app** on your physical device (already installed with latest build)
2. **Log in** if not already logged in
3. **Go to the Chat tab**
4. **Type:** `عايز شاشات 2k بسعر أقل من 12 ألف`
5. **Wait** for results (LLM extraction + store crawling takes ~10-30 seconds)
6. **Tap "Add to Feed"** on any product card
7. **Verify** the success message appears

## Backend URLs (for debugging)

- API: `http://192.168.100.6:8001`
- Chatbot: `http://192.168.100.6:8003`
- Health: `curl http://localhost:8003/health`

## Credits

Free tier now has **100 credits** (was 3). Each tracker costs 1 credit for 1 week.