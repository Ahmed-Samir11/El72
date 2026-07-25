import Redis from 'ioredis'
import axios from 'axios'

const REDIS_URL = process.env.REDIS_URL || 'redis://127.0.0.1:6379'
const STREAM = 'stream:confirmed_deals'
const GROUP = 'cg_notifier'
const CONSUMER = process.env.NOTIFIER_CONSUMER || 'notifier-1'
const MOCK_WHATSAPP = process.env.MOCK_WHATSAPP === 'true'
const WHATSAPP_API_URL = process.env.WHATSAPP_API_URL || 'https://api.whatsapp.com/send'
const WHATSAPP_TOKEN = process.env.WHATSAPP_TOKEN || 'your-token'

let redis: Redis | null = null

function getRedis() {
  if (!redis) {
    redis = new Redis(REDIS_URL)
  }

  return redis
}

async function ensureGroup() {
  const client = getRedis()

  try {
    await client.xgroup('CREATE', STREAM, GROUP, '$', 'MKSTREAM')
  } catch (e: any) {
    if (!/BUSYGROUP/.test(String(e))) throw e
  }
}

export async function sendWhatsApp(phone: string, message: string) {
  if (MOCK_WHATSAPP) {
    console.log(`MOCK WhatsApp to ${phone}: ${message}`)
    return
  }
  // Real implementation: call WhatsApp API
  try {
    await axios.post(WHATSAPP_API_URL, {
      to: phone,
      message: message
    }, {
      headers: { Authorization: `Bearer ${WHATSAPP_TOKEN}` }
    })
  } catch (error) {
    console.error('WhatsApp send failed:', error)
    throw error
  }
}

function parsePayload(fields: Record<string, any>) {
  const payloadValue = fields.payload || fields['payload']

  if (typeof payloadValue === 'string') {
    return JSON.parse(payloadValue)
  }

  if (payloadValue instanceof Buffer) {
    return JSON.parse(payloadValue.toString('utf-8'))
  }

  if (payloadValue && typeof payloadValue === 'object') {
    return payloadValue
  }

  const payload: Record<string, any> = {}
  for (const [key, value] of Object.entries(fields)) {
    payload[key] = typeof value === 'string' ? value : String(value)
  }
  return payload
}

async function processMessage(id: string, fields: Record<string, any>) {
  const client = getRedis()
  const payload = parsePayload(fields)
  const { user_phone, sku, price } = payload

  if (!sku) {
    console.warn(`Skipping message ${id}: missing sku`)
    await redis.xack(STREAM, GROUP, id)
    return
  }

  if (!user_phone) {
    console.warn(`Skipping message ${id}: missing user_phone`)
    await redis.xack(STREAM, GROUP, id)
    return
  }

  const message = `Great news! Your alert for ${sku} has been triggered. Current price: ${price} EGP.`

  try {
    await sendWhatsApp(user_phone, message)
    await client.set(`alert_sent:${payload.user_id || user_phone}:${sku}`, '1', 'EX', 86400)
    await client.xack(STREAM, GROUP, id)
  } catch (error) {
    console.error('Failed to send notification:', error)
  }
}

async function loop() {
  await ensureGroup()
  const client = getRedis()

  while (true) {
    const res = await client.xreadgroup('GROUP', GROUP, CONSUMER, 'COUNT', 10, 'BLOCK', 5000, 'STREAMS', STREAM, '>') as any
    if (!res) continue
    for (const [stream, messages] of res) {
      for (const [id, fields] of messages) {
        await processMessage(id, fields)
      }
    }
  }
}

async function main() {
  try {
    await loop()
  } finally {
    if (redis) {
      await redis.quit()
      redis = null
    }
  }
}

if (require.main === module) {
  void main().catch(err => { console.error(err); process.exit(1) })
}

export { parsePayload, processMessage, main }
