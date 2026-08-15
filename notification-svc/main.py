import os
import json
import threading
from datetime import datetime
from collections import defaultdict

import redis
from fastapi import FastAPI

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
MILESTONE = int(os.getenv("MILESTONE_EVERY", "10"))

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

app = FastAPI(title="notification-svc")

local_counts = defaultdict(int)
notifications = []


def consume_clicks():
    pubsub = r.pubsub()
    pubsub.subscribe("clicks")
    for message in pubsub.listen():
        if message["type"] != "message":
            continue
        event = json.loads(message["data"])
        code = event["code"]
        local_counts[code] += 1
        if local_counts[code] % MILESTONE == 0:
            note = {
                "code": code,
                "clicks": local_counts[code],
                "message": f"{code} just hit {local_counts[code]} clicks",
                "timestamp": datetime.utcnow().isoformat(),
            }
            notifications.append(note)
            print(f"[notification-svc] {note['message']}")


@app.on_event("startup")
def start_consumer():
    thread = threading.Thread(target=consume_clicks, daemon=True)
    thread.start()


@app.get("/health")
def health():
    return {"status": "ok", "service": "notification-svc"}


@app.get("/notifications")
def get_notifications():
    return notifications[-20:]
