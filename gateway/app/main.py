"""FastAPI entrypoint: /health plus the OpenAI-shaped chat-completions proxy."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import httpx
import redis.asyncio as redis
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from core.auth import resolve_api_key
from core.config import get_settings
from core.pipeline import proxy_chat_completion, stream_chat_completion
from observability.api import router as obs_router
from translation.base import JSON


async def _init_pool_conn(conn: asyncpg.Connection) -> None:
    """Register pgvector + jsonb codecs on each new pool connection so list[float] <-> vector
    and dict <-> jsonb round-trip without call-site (de)serialization."""
    import pgvector.asyncpg
    await pgvector.asyncpg.register_vector(conn)
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog", format="text"
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.environment != "production" and settings.dashboard_auth_token is None:
        logging.getLogger(__name__).warning(
            "DASHBOARD_AUTH_TOKEN is unset — /v1/observability/* endpoints are "
            "unauthenticated. Set DASHBOARD_AUTH_TOKEN before exposing this instance."
        )
    app.state.pool = await asyncpg.create_pool(settings.database_url, init=_init_pool_conn)
    app.state.redis = redis.from_url(settings.redis_url)
    app.state.http = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
    try:
        yield
    finally:
        await app.state.pool.close()
        await app.state.redis.aclose()
        await app.state.http.aclose()


app = FastAPI(title="The Conductor", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(obs_router)


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
    authorization = request.headers.get("authorization")

    if bool(body.get("stream")):
        async def gen() -> AsyncIterator[bytes]:
            # Hold a pooled connection for the stream's lifetime (write at open + close).
            async with app.state.pool.acquire() as conn:
                api_key = await resolve_api_key(conn, authorization)
                async for chunk in stream_chat_completion(
                    conn, app.state.http, app.state.redis, body, key=api_key
                ):
                    yield chunk

        return StreamingResponse(gen(), media_type="text/event-stream")

    async with app.state.pool.acquire() as conn:
        api_key = await resolve_api_key(conn, authorization)
        result = await proxy_chat_completion(
            conn, app.state.http, app.state.redis, body, key=api_key
        )
    return JSONResponse(content=result)
