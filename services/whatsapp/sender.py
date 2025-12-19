"""
WhatsApp Notification Service for El72

Consumes notifications from Redis Streams and sends WhatsApp messages via Facebook Graph API.
Listens to: stream:confirmed_deals
Consumer Group: cg_whatsapp
Queries database for all users with alerts for the SKU and sends to all of them.
"""

import asyncio
import json
import os
import sys
from typing import Dict, Any, List, Tuple

import redis.asyncio as aioredis
import httpx
import psycopg2
from psycopg2.extras import RealDictCursor
from loguru import logger

# Configuration from environment
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379")
STREAM_NAME = os.getenv("STREAM_NAME", "stream:confirmed_deals")
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "cg_whatsapp")
CONSUMER_NAME = os.getenv("CONSUMER_NAME", "whatsapp-1")

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://elhaq:elhaq_pass@postgres:5432/elhaq")

# WhatsApp Business API Configuration
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "EAAMDRapIJBIBQEVaz8vkFSEGZAuLksuHY6lbOsD86eRRYIpZBzASnpnzCFjLGIeQyhJCzSvnmCqDE1cKcG0pAiYgYjKE5I3K4hx7sXcl0JmyDZCUSLrrIQ8erjdvyXupZB4vhs7DIZBnU1GfLXCsk2mn34TaZBt4YDNzC0MeEGJlKXa5TYFvyx6WZBt097eEdd07E6yJajZCCMjm8ZAed0bZAvJVBMJkpppxf5AFZBd5lmWuOh9ykY2nK0p5zJAcaD1sCyc3EYwpFUDXMrRnpxMUZCtZA")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "966490223206963")
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v18.0")

# Feature Flags
MOCK_MODE = os.getenv("MOCK_WHATSAPP", "false").lower() == "true"

# Redis client and DB connection
redis_client: aioredis.Redis = None
db_conn = None


def get_db_connection():
    """Get PostgreSQL database connection."""
    global db_conn
    if db_conn is None or db_conn.closed:
        db_conn = psycopg2.connect(DATABASE_URL)
    return db_conn


def get_subscribers_for_sku(sku: str) -> List[Tuple[int, str]]:
    """Query database for all users who have active alerts for this SKU.
    
    Returns:
        List of tuples (user_id, phone_number) for all subscribers
    """
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Join alerts with users to get phone numbers
            # Assumes alerts table has 'target_url' containing SKU and users table has 'phone'
            query = """
                SELECT DISTINCT u.id, u.phone
                FROM alerts a
                JOIN users u ON a.user_id = u.id
                WHERE a.active_status = TRUE
                  AND a.target_url LIKE %s
            """
            cursor.execute(query, (f'%{sku}%',))
            results = cursor.fetchall()
            
            # Convert to list of tuples
            subscribers = [(row['id'], row['phone']) for row in results]
            logger.info(f"Found {len(subscribers)} subscribers for SKU: {sku}")
            return subscribers
            
    except Exception as e:
        logger.error(f"Failed to query subscribers for SKU {sku}: {e}", exc_info=True)
        return []


async def ensure_consumer_group():
    """Create consumer group idempotently."""
    try:
        await redis_client.xgroup_create(
            name=STREAM_NAME, groupname=CONSUMER_GROUP, id="0", mkstream=True
        )
        logger.info(f"Created consumer group '{CONSUMER_GROUP}' on stream '{STREAM_NAME}'")
    except aioredis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            logger.info(f"Consumer group '{CONSUMER_GROUP}' already exists")
        else:
            raise


async def send_whatsapp_message(phone: str, message_body: str) -> bool:
    """Send WhatsApp message via Facebook Graph API.
    
    Args:
        phone: Recipient phone number with country code (e.g., "201102526446")
        message_body: Text message to send
        
    Returns:
        True if message sent successfully, False otherwise
    """
    if MOCK_MODE:
        logger.info(f"[MOCK] WhatsApp to {phone}: {message_body}")
        return True

    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        logger.error("WhatsApp credentials not configured. Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID")
        return False

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Use text message type for custom messages
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message_body
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            
            if response.status_code == 200:
                logger.info(f"WhatsApp message sent to {phone}: {response.json()}")
                return True
            else:
                logger.error(f"WhatsApp API error [{response.status_code}]: {response.text}")
                return False
                
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}", exc_info=True)
        return False


def format_price_alert(payload: Dict[str, Any]) -> str:
    """Format price alert message.
    
    Expected payload fields:
    - sku: Product identifier
    - price: Current price
    - original_price: Original price (optional)
    - discount_percent: Discount percentage (optional)
    """
    sku = payload.get("sku", "Product")
    price = payload.get("price", 0)
    original_price = payload.get("original_price")
    discount = payload.get("discount_percent")
    
    message = f"🎯 *El72 Price Alert*\n\n"
    message += f"Product: {sku}\n"
    message += f"Current Price: {price} EGP\n"
    
    if original_price and discount:
        message += f"Original Price: {original_price} EGP\n"
        message += f"Discount: {discount}%\n"
        message += f"You save: {original_price - price} EGP!\n"
    
    message += f"\n✅ Your alert has been triggered!"
    
    return message


async def process_message(message_id: str, fields: Dict[bytes, bytes]):
    """Process a single notification message from Redis Stream.
    
    Queries database for all users with alerts for this SKU and sends to all of them.
    """
    try:
        # Parse payload
        payload_bytes = fields.get(b"payload") or fields.get("payload")
        if not payload_bytes:
            logger.warning(f"Message {message_id} has no payload field")
            await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
            return
            
        payload = json.loads(payload_bytes)
        logger.debug(f"Processing message {message_id}: {payload}")
        
        # Extract SKU from payload
        sku = payload.get("sku")
        if not sku:
            logger.warning(f"Message {message_id} has no SKU")
            await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
            return
        
        # Get all subscribers for this SKU from database
        subscribers = get_subscribers_for_sku(sku)
        
        if not subscribers:
            logger.info(f"No subscribers found for SKU: {sku}")
            await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
            return
        
        # Format message once
        message_text = format_price_alert(payload)
        
        # Prepare tasks for concurrent sending
        async def send_to_subscriber(user_id: int, phone: str):
            """Send message to a single subscriber with deduplication check"""
            # Check deduplication key (prevent duplicate alerts within 24h)
            dedup_key = f"alert_sent:{user_id}:{sku}"
            
            if await redis_client.exists(dedup_key):
                logger.info(f"Duplicate alert suppressed for user {user_id}:{sku}")
                return None
            
            # Strip '+' from phone number for WhatsApp API
            phone_clean = phone.lstrip('+')
            
            # Send WhatsApp message
            success = await send_whatsapp_message(phone_clean, message_text)
            
            if success:
                # Set deduplication key (expires in 24 hours)
                await redis_client.setex(dedup_key, 86400, "1")
                logger.info(f"Sent alert to user {user_id} ({phone})")
                return True
            else:
                logger.error(f"Failed to send alert to user {user_id} ({phone})")
                return False
        
        # Send to all subscribers concurrently
        tasks = [send_to_subscriber(user_id, phone) for user_id, phone in subscribers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count results
        success_count = sum(1 for r in results if r is True)
        failed_count = sum(1 for r in results if r is False)
        skipped_count = sum(1 for r in results if r is None)
        
        # Log summary
        logger.info(f"Message {message_id} processed: {success_count} sent, {failed_count} failed, {skipped_count} skipped (duplicates), {len(subscribers)} total subscribers")
        
        # Always ACK the message after processing all subscribers
        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
            
    except Exception as e:
        logger.error(f"Error processing message {message_id}: {e}", exc_info=True)
        # Do not ACK on error - allow retry


async def consume_loop():
    """Main consumer loop - reads from Redis Stream and processes notifications."""
    logger.info(f"Starting WhatsApp consumer: {CONSUMER_NAME} in group {CONSUMER_GROUP}")
    logger.info(f"Listening to stream: {STREAM_NAME}")
    logger.info(f"Mock mode: {MOCK_MODE}")
    
    await ensure_consumer_group()
    
    while True:
        try:
            # Read up to 10 messages, block for 5 seconds
            messages = await redis_client.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM_NAME: ">"},
                count=10,
                block=5000,
            )
            
            if not messages:
                continue
            
            for stream_name, message_list in messages:
                for message_id, fields in message_list:
                    await process_message(message_id, fields)
                    
        except asyncio.CancelledError:
            logger.info("Consumer loop cancelled, shutting down...")
            break
        except Exception as e:
            logger.error(f"Error in consumer loop: {e}", exc_info=True)
            await asyncio.sleep(5)  # Back off on error


async def main():
    """Initialize Redis connection, test database, and start consumer loop."""
    global redis_client, db_conn
    
    logger.info("Initializing WhatsApp Notification Service...")
    
    # Test database connection
    try:
        db_conn = get_db_connection()
        logger.info(f"Connected to database at {DATABASE_URL.split('@')[1]}")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        sys.exit(1)
    
    # Connect to Redis
    redis_client = await aioredis.from_url(
        REDIS_URL, 
        encoding="utf-8", 
        decode_responses=True
    )
    
    try:
        await redis_client.ping()
        logger.info(f"Connected to Redis at {REDIS_URL}")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        sys.exit(1)
    
    try:
        await consume_loop()
    finally:
        await redis_client.aclose()
        if db_conn and not db_conn.closed:
            db_conn.close()
        logger.info("Connections closed")


if __name__ == "__main__":
    logger.add(sys.stderr, format="{time} {level} {message}", level="INFO")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
