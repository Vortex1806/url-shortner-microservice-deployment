import os

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse

SHORTENER_SVC_URL = os.getenv("SHORTENER_SVC_URL", "http://shortener-svc:8000")
REDIRECT_SVC_URL = os.getenv("REDIRECT_SVC_URL", "http://redirect-svc:8000")
ANALYTICS_SVC_URL = os.getenv("ANALYTICS_SVC_URL", "http://analytics-svc:8000")
NOTIFICATION_SVC_URL = os.getenv("NOTIFICATION_SVC_URL", "http://notification-svc:8000")

app = FastAPI(title="api-gateway")


@app.get("/health")
def health():
    return {"status": "ok", "service": "api-gateway"}


@app.post("/api/shorten")
async def shorten(request: Request):
    body = await request.json()
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(f"{SHORTENER_SVC_URL}/shorten", json=body)
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@app.get("/api/stats/{code}")
async def stats(code: str):
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{ANALYTICS_SVC_URL}/stats/{code}")
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@app.get("/api/notifications")
async def notifications():
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{NOTIFICATION_SVC_URL}/notifications")
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@app.get("/{code}")
async def redirect(code: str):
    async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
        resp = await client.get(f"{REDIRECT_SVC_URL}/{code}")
    if resp.status_code in (301, 302, 307, 308):
        return RedirectResponse(url=resp.headers["location"])
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
