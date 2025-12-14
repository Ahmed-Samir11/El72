import Redis from 'ioredis'
import axios from 'axios'

const REDIS_URL = process.env.REDIS_URL || 'redis://127.0.0.1:6379'
const STREAM = 'stream:confirmed_deals'
const GROUP = 'cg_notifier'
const CONSUMER = process.env.NOTIFIER_CONSUMER || 'notifier-1'

const redis = new Redis(REDIS_URL)

async function ensureGroup() {
  try {
    await redis.xgroup('CREATE', STREAM, GROUP, '$', 'MKSTREAM')
  } catch (e: any) {
    if (!/BUSYGROUP/.test(String(e))) throw e
  }
}

async function loop() {
  await ensureGroup()
  while (true) {
    const res = await redis.xreadgroup('GROUP', GROUP, CONSUMER, 'COUNT', 10, 'BLOCK', 5000, 'STREAMS', STREAM, '>')
    if (!res) continue
    for (const [stream, messages] of res) {
      for (const [id, fields] of messages) {
        const payload = fields.payload || fields["payload"]
        // TODO: parse payload, dedupe via key `alert_sent:{user_id}:{sku}`
        // Send via WhatsApp Business API (360dialog)
        // After success, XACK
        await redis.xack(STREAM, GROUP, id)
      }
    }
  }
}

loop().catch(err => { console.error(err); process.exit(1) })
