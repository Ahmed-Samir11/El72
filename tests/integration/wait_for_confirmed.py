"""
Simple helper that blocks until a message appears in `stream:confirmed_deals` and prints it.

Usage: python tests/integration/wait_for_confirmed.py
"""
import time
import json
import redis

REDIS_URL = "redis://localhost:6379/0"
STREAM = "stream:confirmed_deals"


def main():
    r = redis.from_url(REDIS_URL)
    print("Waiting for a confirmed deal on stream: confirmed_deals...")
    while True:
        res = r.xrange(STREAM, min='-', max='+', count=10)
        if res:
            for msg_id, fields in res:
                payload_b = fields.get(b'payload') or fields.get('payload')
                try:
                    payload = json.loads(payload_b.decode() if isinstance(payload_b, (bytes, bytearray)) else payload_b)
                except Exception:
                    payload = payload_b
                print("Found:", msg_id, payload)
            break
        time.sleep(1)


if __name__ == '__main__':
    main()
