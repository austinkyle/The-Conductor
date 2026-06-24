"""FastAPI entrypoint: /health plus the OpenAI-shaped chat-completions proxy."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import httpx
import redis.asyncio as redis
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from core.config import get_settings
from core.pipeline import proxy_chat_completion, stream_chat_completion
from translation.base import JSON


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.pool = await asyncpg.create_pool(settings.database_url)
    app.state.redis = redis.from_url(settings.redis_url)
    app.state.http = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
    try:
        yield
    finally:
        await app.state.pool.close()
        await app.state.redis.aclose()
        await app.state.http.aclose()


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


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    """OpenAI-compatible chat completions. Forwards to the resolved provider and returns
    the OpenAI-shaped response — a JSON body, or an SSE stream when `stream` is set —
    regardless of which provider served it."""
    body: JSON = await request.json()

    if bool(body.get("stream")):
        async def gen() -> AsyncIterator[bytes]:
            # Hold a pooled connection for the stream's lifetime (Phase 4/5 write at close).
            async with app.state.pool.acquire() as conn:
                async for chunk in stream_chat_completion(conn, app.state.http, body):
                    yield chunk

        return StreamingResponse(gen(), media_type="text/event-stream")

    async with app.state.pool.acquire() as conn:
        result = await proxy_chat_completion(conn, app.state.http, body)
    return JSONResponse(content=result)
