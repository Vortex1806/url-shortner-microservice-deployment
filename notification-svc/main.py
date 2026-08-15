import os
import json
import threading
import time
from datetime import datetime

import redis
from fastapi import FastAPI

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
MILESTONE = int(os.getenv("MILESTONE_EVERY", "10"))

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

app = FastAPI(title="notification-svc")

notifications = []
notified_milestones = {}  # code -> last milestone already notified for


def consume_clicks():
    while True:
        try:
            pubsub = r.pubsub()
            pubsub.subscribe("clicks")
            print("[notification-svc] connected to redis, listening on 'clicks'")
            for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                event = json.loads(message["data"])
                code = event["code"]

                # read the shared count analytics-svc maintains, don't keep our own
                count = int(r.hget("click_counts", code) or 0)

                last_notified = notified_milestones.get(code, 0)
                if count // MILESTONE > last_notified // MILESTONE and count > 0:
                    note = {
                        "code": code,
                        "clicks": count,
                        "message": f"{code} just hit {count} clicks",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    notifications.append(note)
                    notified_milestones[code] = count
                    print(f"[notification-svc] {note['message']}")
        except Exception as e:
            print(f"[notification-svc] redis connection lost/failed: {e}, retrying in 3s")
            time.sleep(3)


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