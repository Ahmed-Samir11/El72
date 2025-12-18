"""
WhatsApp Notification Service for El72

Consumes notifications from Redis Streams and sends WhatsApp messages via Facebook Graph API.
Listens to: stream:confirmed_deals
Consumer Group: cg_whatsapp
"""

import asyncio
import json
import os
import sys
from typing import Dict, Any

import redis.asyncio as aioredis
import httpx
from loguru import logger

# Configuration from environment
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379")
STREAM_NAME = os.getenv("STREAM_NAME", "stream:confirmed_deals")
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "cg_whatsapp")
CONSUMER_NAME = os.getenv("CONSUMER_NAME", "whatsapp-1")

# WhatsApp Business API Configuration
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "EAAMDRapIJBIBQAtLaaKxDUJJ5CFRsQwvvucrqTmAN5FlgMEcFfooyPmZCtcqTBxezCJaNaKAKMWoiOdp30DTe13AiSYUfezbH1v9r63pzBiWsTw5nZC27ZAsEbRtOZCFoj4lcM7kknXRXcREP5W6m1NaVIpTSNZByRS5v92NkRsRZB96fNx160vaj0TjkqX4lVPDH5oNogDdTJQVcejRO3oNx1v9hZC1BGC3zVVkFTzTTGXAbbFwGWNwbSG6KzoGaHZAQ26ujKTbmbr6KxZCcnXVr")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "966490223206963")
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v18.0")

# Feature Flags
MOCK_MODE = os.getenv("MOCK_WHATSAPP", "false").lower() == "true"

# Redis client
redis_client: aioredis.Redis = None


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
    """Process a single notification message from Redis Stream."""
    try:
        # Parse payload
        payload_bytes = fields.get(b"payload") or fields.get("payload")
        if not payload_bytes:
            logger.warning(f"Message {message_id} has no payload field")
            await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
            return
            
        payload = json.loads(payload_bytes)
        logger.debug(f"Processing message {message_id}: {payload}")
        
        # Extract phone number
        phone = payload.get("user_phone") or payload.get("phone")
        if not phone:
            logger.warning(f"Message {message_id} has no phone number")
            await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
            return
        
        # Format message
        message_text = format_price_alert(payload)
        
        # Check deduplication key (prevent duplicate alerts within 24h)
        user_id = payload.get("user_id", "unknown")
        sku = payload.get("sku", "unknown")
        dedup_key = f"alert_sent:{user_id}:{sku}"
        
        if await redis_client.exists(dedup_key):
            logger.info(f"Duplicate alert suppressed for {user_id}:{sku}")
            await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
            return
        
        # Send WhatsApp message
        success = await send_whatsapp_message(phone, message_text)
        
        if success:
            # Set deduplication key (expires in 24 hours)
            await redis_client.setex(dedup_key, 86400, "1")
            # Acknowledge message
            await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, message_id)
            logger.info(f"Successfully processed message {message_id}")
        else:
            logger.error(f"Failed to send WhatsApp for message {message_id}, will retry")
            # Do not ACK - message will be retried
            
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
    """Initialize Redis connection and start consumer loop."""
    global redis_client
    
    logger.info("Initializing WhatsApp Notification Service...")
    
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
        await redis_client.close()
        logger.info("Redis connection closed")


if __name__ == "__main__":
    logger.add(sys.stderr, format="{time} {level} {message}", level="INFO")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
