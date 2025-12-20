#!/bin/bash

# Monitor the complete tracker flow in real-time

echo "=================================================="
echo "🔍 EL72 TRACKER FLOW MONITOR"
echo "=================================================="
echo ""

# Check if services are running
echo "1️⃣ Checking Service Status..."
docker compose ps | grep -E "(scraper|api|whatsapp|postgres|redis)" | awk '{print $1 " - " $7}'
echo ""

# Function to watch logs in background
watch_logs() {
    echo "=================================================="
    echo "📺 LIVE LOG MONITORING"
    echo "Press Ctrl+C to stop"
    echo "=================================================="
    echo ""
    
    # Create a named pipe for synchronized output
    tmpfile=$(mktemp)
    
    # Watch API logs for alert creation
    (docker logs -f el72-api-1 2>&1 | grep --line-buffered -E "(Pushed alert|POST /alerts|❌)" | while read line; do
        echo "[API] $line"
    done) &
    
    # Watch Scraper logs for scraping activity
    (docker logs -f el72-scraper-1 2>&1 | grep --line-buffered -E "(Pushed|triggered|Found|Playwright|ERROR)" | while read line; do
        echo "[SCRAPER] $line"
    done) &
    
    # Watch WhatsApp logs for notifications
    (docker logs -f el72-whatsapp-1 2>&1 | grep --line-buffered -E "(WhatsApp|sent|Sent|Processing)" | while read line; do
        echo "[WHATSAPP] $line"
    done) &
    
    # Keep running
    wait
}

# Function to check Redis streams
check_streams() {
    echo "=================================================="
    echo "📊 REDIS STREAMS STATUS"
    echo "=================================================="
    echo ""
    
    echo "🔹 Scraper Tasks (Last 3):"
    docker exec -it el72-redis-1 redis-cli XREVRANGE scraper_tasks + - COUNT 3 2>/dev/null | grep -A1 "payload" | tail -3
    echo ""
    
    echo "🔹 Confirmed Deals (Last 3):"
    docker exec -it el72-redis-1 redis-cli XREVRANGE stream:confirmed_deals + - COUNT 3 2>/dev/null | head -20
    echo ""
    
    echo "🔹 Stream Lengths:"
    echo -n "   scraper_tasks: "
    docker exec -it el72-redis-1 redis-cli XLEN scraper_tasks 2>/dev/null
    echo -n "   stream:confirmed_deals: "
    docker exec -it el72-redis-1 redis-cli XLEN stream:confirmed_deals 2>/dev/null
    echo ""
}

# Function to check database
check_database() {
    echo "=================================================="
    echo "💾 DATABASE STATUS"
    echo "=================================================="
    echo ""
    
    echo "🔹 Recent Alerts:"
    docker exec -it el72-postgres-1 psql -U elhaq -d elhaq -c "
        SELECT *
        FROM alerts a
        JOIN users u ON a.user_id = u.id
        ORDER BY a.created_at DESC
        LIMIT 5;
    " 2>/dev/null
    echo ""
}

# Show menu
echo "Choose monitoring option:"
echo ""
echo "  1) Watch Live Logs (API + Scraper + WhatsApp)"
echo "  2) Check Redis Streams"
echo "  3) Check Database Alerts"
echo "  4) Full Status Check (All of the above)"
echo "  5) Continuous Monitor (refreshes every 10s)"
echo ""
read -p "Enter choice [1-5]: " choice

case $choice in
    1)
        watch_logs
        ;;
    2)
        check_streams
        ;;
    3)
        check_database
        ;;
    4)
        check_streams
        echo ""
        check_database
        ;;
    5)
        while true; do
            clear
            echo "🔄 Auto-refreshing every 10 seconds... (Ctrl+C to stop)"
            echo ""
            check_streams
            check_database
            echo ""
            echo "Last updated: $(date '+%H:%M:%S')"
            sleep 10
        done
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac
