"""FastAPI entrypoint. Phase 0: app wiring + a real /health check only."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.pool = await asyncpg.create_pool(settings.database_url)
    app.state.redis = redis.from_url(settings.redis_url)
    try:
        yield
    finally:
        await app.state.pool.close()
        await app.state.redis.aclose()


app = FastAPI(title="LLM Gateway", lifespan=lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    """200 only if both Postgres and Redis are reachable, else 503."""
    try:
        async with app.state.pool.acquire() as conn:
            await conn.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False

    try:
        db_redis = await app.state.redis.ping()
        redis_ok = bool(db_redis)
    except Exception:
        redis_ok = False

    ok = db_ok and redis_ok
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "unhealthy", "db": db_ok, "redis": redis_ok},
    )
