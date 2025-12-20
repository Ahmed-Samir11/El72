#!/bin/bash

# Test the complete tracker flow: Register → Login → Create Alert → Scraper → WhatsApp

API_BASE="http://localhost:8000"
PHONE="+201091095176"
PASSWORD="testpass123"
AMAZON_URL="https://www.amazon.eg/-/en/SteelSeries-Aerox-Ultra-Lightweight-Wireless/dp/B0BQYDYL74"
# Set target price ABOVE actual price (50,000) to trigger notification
TARGET_PRICE=60000

echo "======================================"
echo "🚀 ELHAQ TRACKER FLOW TEST"
echo "======================================"
echo ""

# Step 1: Register/Login
echo "📱 Step 1: Login with phone $PHONE"
RESPONSE=$(curl -s -X POST "$API_BASE/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"phone\": \"$PHONE\", \"password\": \"$PASSWORD\"}")

if echo "$RESPONSE" | grep -q "access_token"; then
  echo "✅ Login successful!"
  TOKEN=$(echo "$RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
  echo "Token: ${TOKEN:0:50}..."
else
  echo "⚠️ Login failed, trying registration..."
  RESPONSE=$(curl -s -X POST "$API_BASE/auth/register" \
    -H "Content-Type: application/json" \
    -d "{\"phone\": \"$PHONE\", \"password\": \"$PASSWORD\"}")
  
  if echo "$RESPONSE" | grep -q "access_token"; then
    echo "✅ Registration successful!"
    TOKEN=$(echo "$RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
  else
    echo "❌ Failed to authenticate: $RESPONSE"
    exit 1
  fi
fi

echo ""
echo "======================================"
echo "🎯 Step 2: Create Price Alert"
echo "======================================"
echo "Product: Amazon Mouse"
echo "URL: $AMAZON_URL"
echo "Target Price: $TARGET_PRICE EGP"
echo ""

ALERT_RESPONSE=$(curl -s -X POST "$API_BASE/alerts" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"target_url\": \"$AMAZON_URL\", \"target_price\": $TARGET_PRICE}")

echo "Response: $ALERT_RESPONSE"
echo ""

if echo "$ALERT_RESPONSE" | grep -q '"id"'; then
  ALERT_ID=$(echo "$ALERT_RESPONSE" | grep -o '"id":[0-9]*' | cut -d':' -f2)
  echo "✅ Alert created successfully! ID: $ALERT_ID"
  echo ""
  echo "======================================"
  echo "⏳ Step 3: Waiting for Scraper"
  echo "======================================"
  echo "The scraper will now:"
  echo "1. Pick up the task from Redis stream"
  echo "2. Open Amazon page with Playwright"
  echo "3. Extract current price (~50,000 EGP)"
  echo "4. Compare with target price ($TARGET_PRICE EGP)"
  echo "5. If price <= target, send WhatsApp notification"
  echo ""
  echo "Waiting 30 seconds..."
  sleep 30
  
  echo ""
  echo "======================================"
  echo "📋 Step 4: Check Redis Streams"
  echo "======================================"
  docker exec -it el72-redis-1 redis-cli XREVRANGE scraper_tasks + - COUNT 3
  echo ""
  echo "Confirmed Deals Stream:"
  docker exec -it el72-redis-1 redis-cli XREVRANGE stream:confirmed_deals + - COUNT 3
  echo ""
  echo "======================================"
  echo "✅ TEST COMPLETE!"
  echo "======================================"
  echo ""
  echo "📱 Check your WhatsApp for the notification!"
  echo "Expected: Price alert for SteelSeries Aerox Mouse"
  echo ""
else
  echo "❌ Failed to create alert: $ALERT_RESPONSE"
  exit 1
fi
