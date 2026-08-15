import os
import random
import string
import time
from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, DateTime, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/shortener")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class URLMap(Base):
    __tablename__ = "urls"
    code = Column(String, primary_key=True)
    original_url = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db_with_retry(max_retries: int = 5, delay: float = 2.0):
    for attempt in range(max_retries):
        try:
            Base.metadata.create_all(bind=engine)
            print("[shortener-svc] database schema ready")
            return
        except OperationalError as e:
            if attempt == max_retries - 1:
                raise
            print(f"[shortener-svc] db not ready yet ({e}), retrying in {delay}s")
            time.sleep(delay)


init_db_with_retry()

app = FastAPI(title="shortener-svc")


class ShortenRequest(BaseModel):
    url: str


def generate_code(length: int = 6) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def get_db_with_retry(max_retries: int = 3, delay: float = 1.0):
    last_error = None
    for attempt in range(max_retries):
        try:
            db = SessionLocal()
            db.execute(text("SELECT 1"))
            return db
        except OperationalError as e:
            last_error = e
            if attempt == max_retries - 1:
                break
            time.sleep(delay)
    raise HTTPException(status_code=503, detail=f"database unavailable: {last_error}")


@app.get("/health")
def health():
    return {"status": "ok", "service": "shortener-svc"}


@app.post("/shorten")
def shorten(req: ShortenRequest):
    db = get_db_with_retry()
    try:
        code = generate_code()
        while db.query(URLMap).filter(URLMap.code == code).first():
            code = generate_code()

        entry = URLMap(code=code, original_url=req.url)
        db.add(entry)
        db.commit()
        return {"code": code, "short_url": f"/{code}", "original_url": req.url}
    finally:
        db.close()


@app.get("/internal/resolve/{code}")
def resolve(code: str):
    """Internal endpoint — called by redirect-svc, not exposed via gateway."""
    db = get_db_with_retry()
    try:
        entry = db.query(URLMap).filter(URLMap.code == code).first()
        if not entry:
            raise HTTPException(status_code=404, detail="code not found")
        return {"code": entry.code, "original_url": entry.original_url}
    finally:
        db.close()