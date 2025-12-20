# 🧪 How to Test the + Button and Scraper Flow

## Quick Test (30 seconds)

### Option A: Watch Live Logs
```bash
cd /home/mohammed-hany/Documents/CairoAIHackathon/El72
./monitor_tracker_flow.sh
# Choose option 1 (Watch Live Logs)
```

Then in your Flutter app:
1. **Click the + button** (bottom right)
2. **Enter URL**: `https://www.amazon.eg/-/en/SteelSeries-Aerox-Ultra-Lightweight-Wireless/dp/B0BQYDYL74`
3. **Enter price**: `60000`
4. **Click "Start Tracking"**

### What to Look For in Logs:

#### ✅ Flutter Console (where `flutter run` is running):
```
🔘 Add Button Pressed!
📤 Sending: URL=https://..., Price=60000.0
🎯 AlertsRepository: Creating alert...
📥 API Response: 200
✅ Alert created successfully! ID: 83
```

#### ✅ Monitoring Script Output:
```
[API] ✅ Pushed alert 83 to scraper_tasks
[SCRAPER] INFO:scraper:Pushed B0BQYDYL74 from amazon_eg (price=50000.0)
[SCRAPER] INFO:scraper:🔔 Found 1 alerts triggered for SKU B0BQYDYL74
[SCRAPER] INFO:scraper:🔔 Pushed alert to WhatsApp for user +201091095176
[WHATSAPP] 2025-12-20 | INFO | Sent alert to user (...)
```

---

## Step-by-Step Guided Test

Run this interactive guide:
```bash
cd /home/mohammed-hany/Documents/CairoAIHackathon/El72
./test_button_flow.sh
```

It will walk you through each step and show you what to check.

---

## Manual Verification Commands

### 1. Check if + Button Works (Flutter Logs)
Look at your Flutter terminal where `flutter run` is active. When you press +, you should see:
- `🔘 Add Button Pressed!`
- `📤 Sending: URL=..., Price=...`

### 2. Check if API Received It
```bash
docker logs el72-api-1 --tail 20 | grep "POST /alerts"
```
Should show: `POST /alerts HTTP/1.1" 200 OK`

### 3. Check if Alert Pushed to Redis
```bash
docker exec el72-redis-1 redis-cli XREVRANGE scraper_tasks + - COUNT 3
```
Should show your product URL and SKU

### 4. Check if Scraper Picked It Up
```bash
docker logs el72-scraper-1 --tail 30 | grep "B0BQYDYL74"
```
Should show: `Pushed B0BQYDYL74 from amazon_eg (price=50000.0)`

### 5. Check if Price Alert Triggered
```bash
docker logs el72-scraper-1 --tail 30 | grep "🔔"
```
Should show: `🔔 Found X alerts triggered` (if price <= target)

### 6. Check if WhatsApp Sent
```bash
docker logs el72-whatsapp-1 --tail 30 | grep "Sent"
```
Should show: `Sent alert to user`

### 7. Check Database
```bash
docker exec el72-postgres-1 psql -U elhaq -d elhaq -c "
SELECT id, target_url, target_price, active_status, created_at 
FROM alerts 
ORDER BY created_at DESC 
LIMIT 3;"
```

---

## Common Issues & Solutions

### ❌ "Button does nothing"
- **Check**: Flutter console for errors
- **Fix**: Make sure app is logged in (JWT token exists)

### ❌ "API returns 401 Unauthorized"
- **Check**: `docker logs el72-api-1 --tail 10`
- **Fix**: Re-login in the Flutter app

### ❌ "Scraper returns price=0.0"
- **Check**: `docker logs el72-scraper-1 --tail 50`
- **Reason**: Missing `store` field or wrong URL format
- **Fix**: Already fixed in API - restart services: `docker compose restart api scraper`

### ❌ "No WhatsApp notification"
- **Check 1**: Did alert trigger? Price must be <= target
  ```bash
  docker logs el72-scraper-1 | grep "Found.*alerts triggered"
  ```
- **Check 2**: Is WhatsApp service running?
  ```bash
  docker compose ps whatsapp
  ```
- **Check 3**: Is phone number registered in Facebook Business Manager?
- **Check 4**: WhatsApp access token valid? (expires ~60 days)

---

## Real-Time Monitoring Dashboard

For continuous monitoring while testing:
```bash
./monitor_tracker_flow.sh
# Choose option 5 (Continuous Monitor - refreshes every 10s)
```

This shows:
- Redis stream lengths
- Recent scraper tasks
- Confirmed deals
- Latest database alerts

---

## Expected Complete Flow Timing

1. **Click "Start Tracking"** → Immediate (< 1s)
2. **API creates alert** → Immediate (< 100ms)
3. **Push to Redis** → Immediate (< 50ms)
4. **Scraper picks up task** → 1-5 seconds
5. **Playwright opens browser** → 3-10 seconds
6. **Navigate & extract price** → 5-15 seconds
7. **Check database for alerts** → < 1 second
8. **Publish to confirmed_deals** → < 100ms (if triggered)
9. **WhatsApp sends message** → 1-3 seconds

**Total**: 10-35 seconds from button click to WhatsApp notification

---

## Quick Health Check

Run this to verify all services are working:
```bash
docker compose ps
docker logs el72-api-1 --tail 5
docker logs el72-scraper-1 --tail 5
docker logs el72-whatsapp-1 --tail 5
docker exec el72-redis-1 redis-cli PING
docker exec el72-postgres-1 psql -U elhaq -d elhaq -c "SELECT COUNT(*) FROM alerts;"
```

All should respond without errors.
