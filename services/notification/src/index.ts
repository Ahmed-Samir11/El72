import Redis from 'ioredis'
import axios from 'axios'

const REDIS_URL = process.env.REDIS_URL || 'redis://127.0.0.1:6379'
const STREAM = 'stream:confirmed_deals'
const GROUP = 'cg_notifier'
const CONSUMER = process.env.NOTIFIER_CONSUMER || 'notifier-1'
const MOCK_WHATSAPP = process.env.MOCK_WHATSAPP === 'true'
const WHATSAPP_API_URL = process.env.WHATSAPP_API_URL || 'https://api.whatsapp.com/send'
const WHATSAPP_TOKEN = process.env.WHATSAPP_TOKEN || 'your-token'

const redis = new Redis(REDIS_URL)

async function ensureGroup() {
  try {
    await redis.xgroup('CREATE', STREAM, GROUP, '$', 'MKSTREAM')
  } catch (e: any) {
    if (!/BUSYGROUP/.test(String(e))) throw e
  }
}

export async function sendWhatsApp(phone: string, message: string) {
  if (process.env.MOCK_WHATSAPP === 'true') {
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

async function loop() {
  await ensureGroup()
  while (true) {
    const res = await redis.xreadgroup('GROUP', GROUP, CONSUMER, 'COUNT', 10, 'BLOCK', 5000, 'STREAMS', STREAM, '>') as any
    if (!res) continue
    for (const [stream, messages] of res) {
      for (const [id, fields] of messages) {
        const payloadStr = fields.payload || fields["payload"]
        const payload = JSON.parse(payloadStr)
        // Assume payload has user_phone, sku, price
        const { user_phone, sku, price } = payload
        const message = `Great news! Your alert for ${sku} has been triggered. Current price: ${price} EGP.`
        try {
          await sendWhatsApp(user_phone, message)
          // Dedupe key
          await redis.set(`alert_sent:${payload.user_id}:${sku}`, '1', 'EX', 86400) // 24h
          await redis.xack(STREAM, GROUP, id)
        } catch (error) {
          console.error('Failed to send notification:', error)
          // Leave unacked for retry
        }
      }
    }
  }
}

loop().catch(err => { console.error(err); process.exit(1) })
