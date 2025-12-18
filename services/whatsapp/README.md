# WhatsApp Notification Service

This service consumes price alert notifications from Redis Streams and sends WhatsApp messages to users via the Facebook Graph API (WhatsApp Business API).

## Architecture

- **Input**: Redis Stream `stream:confirmed_deals`
- **Consumer Group**: `cg_whatsapp`
- **Output**: WhatsApp messages via Facebook Graph API
- **Features**: Deduplication (24h), mock mode for testing

## Setup

### 1. WhatsApp Business API Setup

To send real WhatsApp messages, you need to set up the WhatsApp Business API:

1. Go to [Facebook Business Manager](https://business.facebook.com/)
2. Create a Business App or use an existing one
3. Add WhatsApp product to your app
4. Get your credentials:
   - **Access Token**: From App Dashboard > WhatsApp > API Setup
   - **Phone Number ID**: From WhatsApp > API Setup > Phone Number

### 2. Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Required variables:
- `WHATSAPP_ACCESS_TOKEN`: Your Facebook Graph API access token
- `WHATSAPP_PHONE_NUMBER_ID`: Your WhatsApp Business phone number ID
- `MOCK_WHATSAPP`: Set to `"true"` for testing without sending real messages

### 3. Running with Docker

The service is included in the main `docker-compose.yml`:

```bash
# Build and start all services
docker-compose up --build

# Start only WhatsApp service
docker-compose up whatsapp

# View logs
docker-compose logs -f whatsapp
```

### 4. Running Standalone (Development)

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export REDIS_URL="redis://localhost:6379"
export MOCK_WHATSAPP="true"

# Run the service
python sender.py
```

## Message Format

The service expects messages on the Redis stream with the following payload:

```json
{
  "user_phone": "201102526446",
  "user_id": "user123",
  "sku": "PROD-12345",
  "price": 1500,
  "original_price": 2000,
  "discount_percent": 25
}
```

### Generated WhatsApp Message

```
🎯 *Elhaq Price Alert*

Product: PROD-12345
Current Price: 1500 EGP
Original Price: 2000 EGP
Discount: 25%
You save: 500 EGP!

✅ Your alert has been triggered!
```

## Testing

### Send Test Message to Redis Stream

You can test the service by manually adding a message to the Redis stream:

```bash
# Connect to Redis
docker-compose exec redis redis-cli

# Add a test message
XADD stream:confirmed_deals * payload '{"user_phone":"201102526446","user_id":"test123","sku":"TEST-PRODUCT","price":100,"original_price":150,"discount_percent":33}'
```

With `MOCK_WHATSAPP=true`, you'll see the message logged without actually sending to WhatsApp.

## Features

### Deduplication

The service prevents duplicate alerts within 24 hours using Redis keys:
- Key pattern: `alert_sent:{user_id}:{sku}`
- TTL: 86400 seconds (24 hours)

### Automatic Retry

If a message fails to send:
- The message is NOT acknowledged (XACK)
- Redis will redeliver it to another consumer
- Failed messages can be inspected using `XPENDING`

### Mock Mode

For development and testing:
- Set `MOCK_WHATSAPP=true`
- Messages are logged but not sent to WhatsApp
- No API credentials required

## Integration with Other Services

### Analyzer Service

The analyzer service should publish messages to the stream when price conditions are met:

```python
import redis.asyncio as aioredis
import json

redis_client = await aioredis.from_url("redis://redis:6379")

payload = {
    "user_phone": user.phone,
    "user_id": str(user.id),
    "sku": product.sku,
    "price": current_price,
    "original_price": alert.target_price,
    "discount_percent": discount
}

await redis_client.xadd(
    "stream:confirmed_deals",
    {"payload": json.dumps(payload)}
)
```

### API Service

The API can trigger manual notifications:

```python
# Trigger alert for a specific user
await redis_client.xadd(
    "stream:confirmed_deals",
    {"payload": json.dumps({
        "user_phone": "201102526446",
        "user_id": "user123",
        "sku": "PROD-001",
        "price": 500
    })}
)
```

## Monitoring

### Check Consumer Group Status

```bash
# Connect to Redis
docker-compose exec redis redis-cli

# Check stream info
XINFO STREAM stream:confirmed_deals

# Check consumer group info
XINFO GROUPS stream:confirmed_deals

# Check pending messages
XPENDING stream:confirmed_deals cg_whatsapp
```

### View Logs

```bash
docker-compose logs -f whatsapp
```

## Production Checklist

- [ ] Set up WhatsApp Business API account
- [ ] Configure valid `WHATSAPP_ACCESS_TOKEN`
- [ ] Configure valid `WHATSAPP_PHONE_NUMBER_ID`
- [ ] Set `MOCK_WHATSAPP=false`
- [ ] Test with real phone numbers (add test numbers in Facebook Business Manager)
- [ ] Monitor Redis stream for backlogs
- [ ] Set up alerting for failed messages
- [ ] Configure log aggregation

## Troubleshooting

### Messages not being processed

1. Check if the consumer group exists:
   ```bash
   redis-cli XINFO GROUPS stream:confirmed_deals
   ```

2. Check for pending messages:
   ```bash
   redis-cli XPENDING stream:confirmed_deals cg_whatsapp
   ```

3. Check service logs:
   ```bash
   docker-compose logs whatsapp
   ```

### WhatsApp API errors

Common errors:
- **401 Unauthorized**: Invalid access token
- **403 Forbidden**: Phone number not verified or user not opted in
- **404 Not Found**: Invalid phone number ID

Check the [WhatsApp Business API documentation](https://developers.facebook.com/docs/whatsapp/cloud-api/) for details.

## License

Part of the Elhaq project.
