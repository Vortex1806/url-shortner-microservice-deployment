import os
import json
from datetime import datetime

import httpx
import redis
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

SHORTENER_SVC_URL = os.getenv("SHORTENER_SVC_URL", "http://shortener-svc:8000")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

app = FastAPI(title="redirect-svc")


@app.get("/health")
def health():
    return {"status": "ok", "service": "redirect-svc"}


@app.get("/{code}")
def redirect(code: str):
    with httpx.Client(timeout=3.0) as client:
        resp = client.get(f"{SHORTENER_SVC_URL}/internal/resolve/{code}")

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="short URL not found")
    resp.raise_for_status()

    original_url = resp.json()["original_url"]

    # publish click event — analytics-svc and notification-svc both consume this
    event = {"code": code, "timestamp": datetime.utcnow().isoformat()}
    r.publish("clicks", json.dumps(event))

    return RedirectResponse(url=original_url)
