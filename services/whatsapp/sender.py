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
from typing import Dict, Any, List, Tuple, Union

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
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v18.0")
# El72 deal alerts should use an El72-specific approved template. The old order/shipping
# template is semantically incorrect for investor deal notifications.
EGYPTIAN_WHATSAPP_USER_IDS = {16, 17, 18}

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


Subscriber = Union[
    Tuple[int, str],
    Tuple[int, str, str],
    Tuple[int, str, str, str],
]


def get_subscribers_for_sku(sku: str) -> List[Subscriber]:
    """Query database for all users who have active alerts for this SKU.

    Returns tuples with the subscriber's id, phone, preferred language, and name
    when available. Older rows without a name column remain compatible.
    """
    try:
        conn = get_db_connection()

        try:
            conn.cursor().execute("SELECT 1")
        except Exception:
            logger.info("Database connection lost, reconnecting...")
            global db_conn
            db_conn = None
            conn = get_db_connection()

        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            query_with_name = """
                SELECT DISTINCT
                    u.id,
                    u.phone,
                    COALESCE(u.preferred_language, 'en') AS preferred_language,
                    COALESCE(u.name, 'Customer') AS name
                FROM alerts a
                JOIN users u ON a.user_id = u.id
                WHERE a.active_status = TRUE
                                    AND u.id IN (16, 17, 18)
                  AND a.target_url LIKE %s
            """
            try:
                cursor.execute(query_with_name, (f'%{sku}%',))
                results = cursor.fetchall()
                subscribers = [
                    (
                        row["id"],
                        row["phone"],
                        row.get("preferred_language", "en"),
                        row.get("name", "Customer"),
                    )
                    for row in results
                ]
            except Exception:
                query_without_name = """
                    SELECT DISTINCT u.id, u.phone, COALESCE(u.preferred_language, 'en') AS preferred_language
                    FROM alerts a
                    JOIN users u ON a.user_id = u.id
                    WHERE a.active_status = TRUE
                                            AND u.id IN (16, 17, 18)
                      AND a.target_url LIKE %s
                """
                cursor.execute(query_without_name, (f'%{sku}%',))
                results = cursor.fetchall()
                subscribers = [
                    (row["id"], row["phone"], row.get("preferred_language", "en"))
                    for row in results
                ]

            logger.info(f"Found {len(subscribers)} subscribers for SKU: {sku}")
            return subscribers

    except Exception as e:
        logger.error(f"Failed to query subscribers for SKU {sku}: {e}")
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


def normalize_phone(phone: str) -> str:
    """Normalize to E.164 with leading '+' (required for reliable Cloud API delivery)."""
    phone = (phone or "").strip().replace(" ", "").replace("-", "")
    if not phone:
        return phone
    if not phone.startswith("+"):
        phone = f"+{phone}"
    return phone


def mask_phone(phone: str) -> str:
    """Keep logs useful without exposing a subscriber's full number."""
    normalized = normalize_phone(phone)
    if len(normalized) <= 4:
        return "****"
    return f"{normalized[:3]}{'*' * max(0, len(normalized) - 7)}{normalized[-4:]}"


async def send_whatsapp_message(phone: str, message_body: str) -> bool:
    """Send WhatsApp message via Facebook Graph API (legacy free-form text).
    
    Prefer send_whatsapp_price_alert for real delivery on the Cloud API test number.
    """
    if MOCK_MODE:
        logger.info(f"[MOCK] WhatsApp to {mask_phone(phone)}: {message_body}")
        return True

    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        logger.error("WhatsApp credentials not configured. Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID")
        return False

    phone = normalize_phone(phone)
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
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
                logger.info(f"WhatsApp message sent to {mask_phone(phone)}: {response.json()}")
                return True
            else:
                logger.error(f"WhatsApp API error [{response.status_code}]: {response.text}")
                return False
                
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}", exc_info=True)
        return False


async def send_whatsapp_price_alert(
    phone: str, payload: Dict[str, Any], language: str = "en"
) -> bool:
    """Send an El72 price alert as plain text when Meta permits free-form messaging."""
    message_preview = format_price_alert(payload, language=language)

    if MOCK_MODE:
        logger.info(f"[MOCK] WhatsApp text to {mask_phone(phone)}: {message_preview}")
        return True

    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        logger.error("WhatsApp credentials not configured. Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID")
        return False

    phone = normalize_phone(phone)
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    api_payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {
            "preview_url": True,
            "body": message_preview,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers, json=api_payload)

            if response.status_code == 200:
                logger.info(
                    f"WhatsApp text sent to {mask_phone(phone)}: {response.json()}"
                )
                return True

            logger.error(
                f"WhatsApp text API error [{response.status_code}]: {response.text}"
            )
            return False
    except Exception as e:
        logger.error(f"Failed to send WhatsApp text message: {e}", exc_info=True)
        return False


def format_price_alert(payload: Dict[str, Any], language: str = "en") -> str:
    """Format price alert message.
    
    Expected payload fields:
    - sku: Product identifier
    - product_title: Product name (optional)
    - price: Current price
    - original_price: Original price (optional)
    - discount_percent: Discount percentage (optional)
    - url: Product URL (optional)
    - store: Store name (optional)
    """
    sku = payload.get("sku", "Product")
    product_title = payload.get("product_title", "")
    price = payload.get("price", 0)
    original_price = payload.get("original_price")
    discount = payload.get("discount_percent")
    url = payload.get("url")
    store = payload.get("store", "")
    
    product_label = product_title or sku
    def format_price(value: Any) -> str:
        try:
            return f"{float(value):,.2f} جنيه"
        except (TypeError, ValueError):
            return "غير متاح"

    previous_text = format_price(original_price)
    current_text = format_price(price)
    discount_text = f"{discount}%" if discount is not None else "غير متاح"

    if language == "ar":
        name = payload.get("name") or payload.get("subscriber_name") or "عميل"
        return (
            f"مرحباً {name} 👋\n\n"
            f"وجدنا عرضاً جيداً على {product_label}.\n\n"
            f"السعر السابق: {previous_text}\n"
            f"السعر الحالي: {current_text}\n"
            f"الخصم: {discount_text}\n\n"
            f"🔗 {url or 'رابط غير متاح'}"
        )

    return (
        f"El72 Price Alert\n\n{product_label}\n\n"
        f"Previous price: {previous_text}\n"
        f"Current price: {current_text}\n"
        f"Discount: {discount_text}\n\n"
        f"🔗 {url or 'URL unavailable'}"
    )


async def process_message(message_id: str, fields: Dict[bytes, bytes]):
    """Process a single notification message from Redis Stream.
    
    Queries database for all users with alerts for this SKU and sends to all of them.
    """
    try:
        # Parse payload - handle both wrapped and unwrapped formats
        payload_bytes = fields.get(b"payload") or fields.get("payload")
        
        if payload_bytes:
            # Wrapped format: {"payload": json_string}
            payload = json.loads(payload_bytes)
            logger.debug(
                f"Processing wrapped message {message_id} for SKU {payload.get('sku')}"
            )
        else:
            # Unwrapped format: fields are direct keys (sku, store, price, etc.)
            logger.info(f"Processing unwrapped message {message_id}")
            payload = {}
            for key, value in fields.items():
                key_str = key.decode('utf-8') if isinstance(key, bytes) else key
                value_str = value.decode('utf-8') if isinstance(value, bytes) else value
                payload[key_str] = value_str
            logger.debug(
                f"Unwrapped message {message_id} fields: {sorted(payload.keys())}"
            )
        
        # Extract SKU from payload
        sku = payload.get("sku")
        if not sku:
            logger.warning(f"Message {message_id} has no SKU")
            await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
            return
            return
        
        # Check if user_phone is directly in payload (from scraper)
        user_phone = payload.get("user_phone")
        
        if user_phone:
            logger.info(f"Using user_phone from payload: {mask_phone(user_phone)}")
            user_id = payload.get("user_id", 0)
            try:
                user_id = int(user_id)
            except (TypeError, ValueError):
                user_id = 0
            subscribers = [
                (
                    user_id,
                    user_phone,
                    payload.get("preferred_language", "en"),
                    payload.get("name") or "Customer",
                )
            ] if user_id in EGYPTIAN_WHATSAPP_USER_IDS else []
        else:
            subscribers = get_subscribers_for_sku(sku)
        
        if not subscribers:
            logger.info(f"No subscribers found for SKU: {sku}")
            await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
            return
        
        # Prepare tasks for concurrent sending
        async def send_to_subscriber(subscriber: Subscriber):
            """Send message to a single subscriber with deduplication check."""
            user_id, phone, *rest = subscriber
            language = rest[0] if len(rest) >= 1 else "en"
            subscriber_name = rest[1] if len(rest) >= 2 else payload.get("name") or "Customer"
            dedup_key = f"alert_sent:{user_id}:{sku}"

            if await redis_client.exists(dedup_key):
                logger.info(f"Duplicate alert suppressed for user {user_id}:{sku}")
                return None

            phone_clean = normalize_phone(phone)
            recipient_payload = dict(payload)
            recipient_payload["name"] = subscriber_name
            recipient_payload["preferred_language"] = language

            success = await send_whatsapp_price_alert(phone_clean, recipient_payload, language)

            if success:
                await redis_client.setex(dedup_key, 86400, "1")
                logger.info(f"Sent alert to user {user_id} ({mask_phone(phone_clean)})")
                return True
            logger.error(f"Failed to send alert to user {user_id} ({mask_phone(phone_clean)})")
            return False
        
        # Send to all subscribers concurrently
        tasks = [send_to_subscriber(subscriber) for subscriber in subscribers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for subscriber, result in zip(subscribers, results):
            if isinstance(result, Exception):
                user_id = subscriber[0]
                logger.opt(exception=(type(result), result, result.__traceback__)).error(
                    f"Subscriber send task raised exception for user {user_id}: {result}"
                )
        # Count results
        success_count = sum(1 for r in results if r is True)
        failed_count = sum(
            1 for r in results if r is False or isinstance(r, Exception)
        )
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
    redis_client = aioredis.from_url(
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
