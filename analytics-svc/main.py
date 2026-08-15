import os
import json
import threading

import redis
from fastapi import FastAPI

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

app = FastAPI(title="analytics-svc")


def consume_clicks():
    pubsub = r.pubsub()
    pubsub.subscribe("clicks")
    for message in pubsub.listen():
        if message["type"] != "message":
            continue
        event = json.loads(message["data"])
        code = event["code"]
        r.hincrby("click_counts", code, 1)


@app.on_event("startup")
def start_consumer():
    thread = threading.Thread(target=consume_clicks, daemon=True)
    thread.start()


@app.get("/health")
def health():
    return {"status": "ok", "service": "analytics-svc"}


@app.get("/stats/{code}")
def stats(code: str):
    count = r.hget("click_counts", code)
    return {"code": code, "clicks": int(count) if count else 0}


@app.get("/stats")
def all_stats():
    counts = r.hgetall("click_counts")
    return {code: int(count) for code, count in counts.items()}
