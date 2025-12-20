#!/bin/bash

echo "=================================================="
echo "📱 FLUTTER + BUTTON TEST GUIDE"
echo "=================================================="
echo ""

echo "STEP 1: Start Monitoring (in a new terminal)"
echo "---------------------------------------------------"
echo "Run this in a separate terminal window:"
echo ""
echo "    cd /home/mohammed-hany/Documents/CairoAIHackathon/El72"
echo "    ./monitor_tracker_flow.sh"
echo "    Choose option 1 (Watch Live Logs)"
echo ""
read -p "Press Enter when monitoring is started..."

echo ""
echo "STEP 2: Open Flutter App on Phone"
echo "---------------------------------------------------"
echo "Make sure your Flutter app is running:"
echo ""
echo "    cd /home/mohammed-hany/Documents/CairoAIHackathon/El72/flutter-app"
echo "    flutter run -d K765INSS9PSGEEEQ"
echo ""
read -p "Press Enter when app is open on phone..."

echo ""
echo "STEP 3: Test the + Button"
echo "---------------------------------------------------"
echo "On your phone:"
echo ""
echo "  1. Click the floating '+' button (bottom right)"
echo "  2. Enter this URL:"
echo "     https://www.amazon.eg/-/en/SteelSeries-Aerox-Ultra-Lightweight-Wireless/dp/B0BQYDYL74"
echo ""
echo "  3. Enter target price: 60000"
echo "  4. Click 'Start Tracking'"
echo ""
read -p "Press Enter after clicking 'Start Tracking'..."

echo ""
echo "STEP 4: Check Flutter Logs"
echo "---------------------------------------------------"
echo "In your Flutter terminal, you should see:"
echo ""
echo "  🔘 Add Button Pressed!"
echo "  📤 Sending: URL=https://..., Price=60000.0"
echo "  🎯 AlertsRepository: Creating alert..."
echo "  📥 API Response: 200"
echo "  ✅ Alert created successfully!"
echo ""
echo "Checking last 20 lines of Flutter output..."
echo ""

# Try to find the flutter process
FLUTTER_LOG=$(ps aux | grep "flutter run" | grep -v grep | head -1)
if [ -z "$FLUTTER_LOG" ]; then
    echo "⚠️ Flutter process not found. Check manually in your terminal."
else
    echo "✅ Found Flutter running"
fi

read -p "Press Enter to continue..."

echo ""
echo "STEP 5: Verify API Received Request"
echo "---------------------------------------------------"
docker logs el72-api-1 --tail 10 | grep -E "(POST /alerts|Pushed alert)"
echo ""
read -p "Press Enter to continue..."

echo ""
echo "STEP 6: Check Scraper Picked Up Task"
echo "---------------------------------------------------"
echo "Scraper logs (last 10 lines):"
docker logs el72-scraper-1 --tail 10
echo ""
echo "Waiting 10 seconds for scraper to process..."
sleep 10
echo ""
echo "Updated scraper logs:"
docker logs el72-scraper-1 --tail 5
echo ""
read -p "Press Enter to continue..."

echo ""
echo "STEP 7: Check Redis Streams"
echo "---------------------------------------------------"
echo "Scraper tasks stream:"
docker exec el72-redis-1 redis-cli XREVRANGE scraper_tasks + - COUNT 1
echo ""
echo "Confirmed deals stream:"
docker exec el72-redis-1 redis-cli XREVRANGE stream:confirmed_deals + - COUNT 1
echo ""
read -p "Press Enter to continue..."

echo ""
echo "STEP 8: Check Database"
echo "---------------------------------------------------"
docker exec el72-postgres-1 psql -U elhaq -d elhaq -c "
SELECT u.phone, a.id, a.target_url, a.target_price, a.active_status
FROM alerts a
JOIN users u ON a.user_id = u.id
ORDER BY a.id DESC
LIMIT 3;
"
echo ""

echo "=================================================="
echo "✅ TESTING COMPLETE!"
echo "=================================================="
echo ""
echo "Expected Results:"
echo "  ✅ Flutter logs show button pressed and API called"
echo "  ✅ API logs show alert created and pushed to Redis"
echo "  ✅ Scraper logs show task picked up and processing"
echo "  ✅ Redis has entries in scraper_tasks stream"
echo "  ✅ Database has new alert record"
echo "  ✅ If price scraped <= target, confirmed_deals stream has entry"
echo "  ✅ WhatsApp notification sent to your phone"
echo ""
echo "To check WhatsApp service:"
echo "  docker logs el72-whatsapp-1 --tail 20"
echo ""
