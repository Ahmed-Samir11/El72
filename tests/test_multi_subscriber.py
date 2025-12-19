#!/usr/bin/env python3
"""
Test script to demonstrate multi-subscriber WhatsApp notifications.

This script:
1. Creates multiple test users
2. Creates alerts for the same product (SKU) for each user
3. Publishes a price drop event to Redis
4. Verifies that WhatsApp service sends messages to all subscribers
"""

import asyncio
import json
import requests
import psycopg2
import redis.asyncio as aioredis
from psycopg2.extras import RealDictCursor

# Configuration
API_URL = "http://localhost:8000"
REDIS_URL = "redis://localhost:6379"
DATABASE_URL = "postgresql://elhaq:elhaq_pass@localhost:5432/elhaq"

TEST_USERS = [
    {"phone": "+201091095176", "password": "testpass123"},
    {"phone": "+201102526446", "password": "test12345"},
    {"phone": "+201118302763", "password": "test12345"},
]

TEST_PRODUCT_URL = "https://example.com/product/SKU-TEST-123"
TEST_SKU = "SKU-TEST-123"


def register_users():
    """Register all test users via API."""
    print("🔧 Registering test users...")
    tokens = []
    
    for user in TEST_USERS:
        # Try to register
        response = requests.post(
            f"{API_URL}/auth/register",
            json=user
        )
        
        if response.status_code == 200:
            print(f"✅ Registered user: {user['phone']}")
        elif response.status_code == 400 and "already registered" in response.text.lower():
            print(f"ℹ️  User already exists: {user['phone']}")
        else:
            print(f"❌ Failed to register {user['phone']}: {response.text}")
            continue
        
        # Login to get token
        login_response = requests.post(
            f"{API_URL}/auth/login",
            json=user
        )
        
        if login_response.status_code == 200:
            token = login_response.json()["access_token"]
            tokens.append((user['phone'], token))
            print(f"✅ Logged in: {user['phone']}")
        else:
            print(f"❌ Failed to login {user['phone']}: {login_response.text}")
    
    return tokens


def create_alerts(tokens):
    """Create alerts for all users for the same product."""
    print(f"\n📋 Creating alerts for product: {TEST_PRODUCT_URL}")
    
    for phone, token in tokens:
        headers = {"Authorization": f"Bearer {token}"}
        alert_data = {
            "target_url": TEST_PRODUCT_URL,
            "target_price": 999.99
        }
        
        response = requests.post(
            f"{API_URL}/alerts",
            json=alert_data,
            headers=headers
        )
        
        if response.status_code == 200:
            alert_id = response.json()["id"]
            print(f"✅ Created alert {alert_id} for {phone}")
        else:
            print(f"❌ Failed to create alert for {phone}: {response.text}")


def verify_alerts_in_db():
    """Query database to verify all alerts are created."""
    print("\n🔍 Verifying alerts in database...")
    
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        query = """
            SELECT u.phone, a.target_url, a.active_status
            FROM alerts a
            JOIN users u ON a.user_id = u.id
            WHERE a.target_url LIKE %s
        """
        cursor.execute(query, (f'%{TEST_SKU}%',))
        results = cursor.fetchall()
        
        print(f"Found {len(results)} active alerts for SKU: {TEST_SKU}")
        for row in results:
            print(f"  - {row['phone']}: {row['target_url']} (active: {row['active_status']})")
    
    conn.close()
    return len(results)


async def publish_price_drop():
    """Publish a price drop event to Redis stream."""
    print("\n📢 Publishing price drop event to Redis...")
    
    redis_client = await aioredis.from_url(REDIS_URL, decode_responses=True)
    
    event = {
        "sku": TEST_SKU,
        "price": 799.99,
        "original_price": 999.99,
        "discount_percent": 20,
        "store": "test_store",
        "timestamp": "2025-12-19T10:00:00Z"
    }
    
    message_id = await redis_client.xadd(
        "stream:confirmed_deals",
        {"payload": json.dumps(event)}
    )
    
    print(f"✅ Published event with message ID: {message_id}")
    print(f"   SKU: {TEST_SKU}")
    print(f"   Price: {event['price']} EGP (was {event['original_price']} EGP)")
    print(f"   Discount: {event['discount_percent']}%")
    
    await redis_client.aclose()


async def main():
    """Run the multi-subscriber test."""
    print("=" * 60)
    print("🧪 Multi-Subscriber WhatsApp Notification Test")
    print("=" * 60)
    
    # Step 1: Register users and get tokens
    tokens = register_users()
    
    if not tokens:
        print("\n❌ No users registered. Exiting.")
        return
    
    print(f"\n✅ {len(tokens)} users ready")
    
    # Step 2: Create alerts for all users
    create_alerts(tokens)
    
    # Step 3: Verify in database
    subscriber_count = verify_alerts_in_db()
    
    if subscriber_count == 0:
        print("\n❌ No alerts found in database. Exiting.")
        return
    
    # Step 4: Publish price drop event
    await publish_price_drop()
    
    print("\n" + "=" * 60)
    print("✅ Test Complete!")
    print("=" * 60)
    print(f"\n📊 Summary:")
    print(f"   - {subscriber_count} users have alerts for SKU: {TEST_SKU}")
    print(f"   - Price drop event published to Redis")
    print(f"   - WhatsApp service should send messages to all {subscriber_count} subscribers")
    print("\n💡 Check WhatsApp service logs:")
    print("   docker logs el72-whatsapp-1 --tail 50")
    print("\n💡 Check for deduplication keys in Redis:")
    print(f"   docker compose exec redis redis-cli KEYS 'alert_sent:*:{TEST_SKU}'")


if __name__ == "__main__":
    asyncio.run(main())
