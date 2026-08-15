import os
import random
import string
from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/shortener")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class URLMap(Base):
    __tablename__ = "urls"
    code = Column(String, primary_key=True)
    original_url = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)

app = FastAPI(title="shortener-svc")


class ShortenRequest(BaseModel):
    url: str


def generate_code(length: int = 6) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


@app.get("/health")
def health():
    return {"status": "ok", "service": "shortener-svc"}


@app.post("/shorten")
def shorten(req: ShortenRequest):
    db = SessionLocal()
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
    db = SessionLocal()
    try:
        entry = db.query(URLMap).filter(URLMap.code == code).first()
        if not entry:
            raise HTTPException(status_code=404, detail="code not found")
        return {"code": entry.code, "original_url": entry.original_url}
    finally:
        db.close()
