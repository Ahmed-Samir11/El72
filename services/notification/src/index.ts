import Redis from 'ioredis'
import axios from 'axios'
import http from 'http'
import client from 'prom-client'

const REDIS_URL = process.env.REDIS_URL || 'redis://127.0.0.1:6379'
const STREAM = 'stream:confirmed_deals'
const GROUP = 'cg_notifier'
const CONSUMER = process.env.NOTIFIER_CONSUMER || 'notifier-1'
const WHATSAPP_API_URL = process.env.WHATSAPP_API_URL || 'https://api.whatsapp.com/send'
const WHATSAPP_TOKEN = process.env.WHATSAPP_TOKEN || 'your-token'

const METRICS_PORT = Number(process.env.METRICS_PORT || '8000')

const register = new client.Registry()
client.collectDefaultMetrics({ register })

const messagesReceivedTotal = new client.Counter({
  name: 'el72_notifier_messages_received_total',
  help: 'Total Redis stream notification messages received.',
})

const messagesSentTotal = new client.Counter({
  name: 'el72_notifier_messages_sent_total',
  help: 'Total WhatsApp notifications sent successfully.',
})

const messagesFailedTotal = new client.Counter({
  name: 'el72_notifier_messages_failed_total',
  help: 'Total WhatsApp notification sends that failed.',
})

const messagesSkippedTotal = new client.Counter({
  name: 'el72_notifier_messages_skipped_total',
  help: 'Total notification messages skipped because required fields were missing.',
})

const sendDurationSeconds = new client.Histogram({
  name: 'el72_notifier_send_duration_seconds',
  help: 'Time spent sending one WhatsApp notification.',
  buckets: [0.1, 0.25, 0.5, 1, 2, 5, 10],
})

const processingDurationSeconds = new client.Histogram({
  name: 'el72_notifier_processing_duration_seconds',
  help: 'Time spent processing one Redis notification message.',
  buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10],
})

const redisReadErrorsTotal = new client.Counter({
  name: 'el72_notifier_redis_read_errors_total',
  help: 'Total Redis XREADGROUP errors.',
})

const ackErrorsTotal = new client.Counter({
  name: 'el72_notifier_ack_errors_total',
  help: 'Total Redis XACK errors.',
})

register.registerMetric(messagesReceivedTotal)
register.registerMetric(messagesSentTotal)
register.registerMetric(messagesFailedTotal)
register.registerMetric(messagesSkippedTotal)
register.registerMetric(sendDurationSeconds)
register.registerMetric(processingDurationSeconds)
register.registerMetric(redisReadErrorsTotal)
register.registerMetric(ackErrorsTotal)

function isMockWhatsApp() {
  return process.env.MOCK_WHATSAPP === 'true'
}

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
  if (isMockWhatsApp()) {
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

function startMetricsServer() {
  const server = http.createServer(async (req, res) => {
    if (req.url !== '/metrics') {
      res.statusCode = 404
      res.end('Not Found')
      return
    }

    try {
      res.setHeader('Content-Type', register.contentType)
      res.end(await register.metrics())
    } catch (error) {
      res.statusCode = 500
      res.end(String(error))
    }
  })

  server.listen(METRICS_PORT, '0.0.0.0', () => {
    console.log(`Prometheus metrics server listening on :${METRICS_PORT}`)
  })

  return server
}

async function processMessage(id: string, fields: Record<string, any>) {
  const processingStart = process.hrtime.bigint()
  messagesReceivedTotal.inc()

  const client = getRedis()

  try {
    const payload = parsePayload(fields)
    const { user_phone, sku, price } = payload

    if (!sku) {
      messagesSkippedTotal.inc()
      console.warn(`Skipping message ${id}: missing sku`)

      try {
        await client.xack(STREAM, GROUP, id)
      } catch (error) {
        ackErrorsTotal.inc()
        throw error
      }

      return
    }

    if (!user_phone) {
      messagesSkippedTotal.inc()
      console.warn(`Skipping message ${id}: missing user_phone`)

      try {
        await client.xack(STREAM, GROUP, id)
      } catch (error) {
        ackErrorsTotal.inc()
        throw error
      }

      return
    }

    const message = `Great news! Your alert for ${sku} has been triggered. Current price: ${price} EGP.`

    const sendStart = process.hrtime.bigint()

    try {
      await sendWhatsApp(user_phone, message)
      messagesSentTotal.inc()
    } catch (error) {
      messagesFailedTotal.inc()
      console.error('Failed to send notification:', error)
      return
    } finally {
      const sendDuration =
        Number(process.hrtime.bigint() - sendStart) / 1_000_000_000

      sendDurationSeconds.observe(sendDuration)
    }

    await client.set(
      `alert_sent:${payload.user_id || user_phone}:${sku}`,
      '1',
      'EX',
      86400
    )

    try {
      await client.xack(STREAM, GROUP, id)
    } catch (error) {
      ackErrorsTotal.inc()
      throw error
    }
  } finally {
    const processingDuration =
      Number(process.hrtime.bigint() - processingStart) / 1_000_000_000

    processingDurationSeconds.observe(processingDuration)
  }
}

async function loop() {
  await ensureGroup()
  const client = getRedis()

  while (true) {
    let res: any

    try {
      res = await client.xreadgroup(
        'GROUP',
        GROUP,
        CONSUMER,
        'COUNT',
        10,
        'BLOCK',
        5000,
        'STREAMS',
        STREAM,
        '>'
      ) as any
    } catch (error) {
      redisReadErrorsTotal.inc()
      console.error('Redis XREADGROUP failed:', error)
      continue
    }

    if (!res) continue
    for (const [stream, messages] of res) {
      for (const [id, fields] of messages) {
        await processMessage(id, fields)
      }
    }
  }
}

async function main() {
  const metricsServer = startMetricsServer()

  try {
    await loop()
  } finally {
    metricsServer.close()

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
