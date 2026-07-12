"""The single request path. Two branches share the same setup:

    parse -> cache check -> resolve chain -> walk candidates -> translate -> call -> respond -> cache write

`proxy_chat_completion` walks the non-streaming branch; `stream_chat_completion` walks the
SSE branch (core/streaming.py). Phase 4 adds: exact Redis cache, semantic pgvector cache,
bypass guardrails, and `cache_status` on every request row.
Phase 5A adds: per-key budget enforcement, token/cost/latency columns on every request row.

Mid-stream failover is intentionally unsupported (ADR-002): the status peek sits at stream
open inside `_stream_attempt`, which runs inside `walk_chain` before any token is yielded.
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from decimal import Decimal

import asyncpg
import httpx
import redis.asyncio as aioredis
from fastapi import HTTPException

from budgets.accounting import cost_cents
from budgets.enforce import check_budget, record_spend
from cache import exact, semantic
from cache.exact import _VOLATILE_KEYS
from cache.guardrails import should_bypass
from cache.replay import assembled_to_response, synthetic_stream
from core import streaming
from core.config import get_settings
from core.request import GatewayRequest
from db.models import ApiKey, Model, Provider
from db.queries import insert_request, update_request_usage
from routing.aliases import resolve_chain
from routing.errors import ProviderError, from_exception, from_status
from routing.fallback import Attempt, walk_chain
from translation.anthropic import AnthropicAdapter
from translation.base import JSON, Adapter
from translation.openai import OpenAIAdapter

_ADAPTERS: dict[str, Adapter] = {
    "openai": OpenAIAdapter(),
    "anthropic": AnthropicAdapter(),
}


def _usage_tokens(body: JSON) -> tuple[int, int, int]:
    """Extract (prompt, completion, total) token counts from an OpenAI response body.

    Returns (0, 0, 0) when the usage block is absent or not a dict — safe for cache
    hit rows where the stored body might not carry usage in all edge cases.
    """
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return 0, 0, 0
    return (
        int(usage.get("prompt_tokens", 0)),
        int(usage.get("completion_tokens", 0)),
        int(usage.get("total_tokens", 0)),
    )


def _parse(body: JSON) -> GatewayRequest:
    try:
        return GatewayRequest.from_body(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _resolve(conn: asyncpg.Connection, req: GatewayRequest) -> list[tuple[Model, Provider]]:
    chain = await resolve_chain(conn, req.model)
    if not chain:
        raise HTTPException(status_code=404, detail=f"unknown model: {req.model}")
    return chain


def _candidate_setup(a: Attempt, body: JSON) -> tuple[Adapter, str, JSON]:
    """Per-candidate adapter + key + outbound body. Raises terminal ProviderError on misconfig."""
    adapter = _ADAPTERS.get(a.provider.api_format)
    if adapter is None:
        raise ProviderError(
            label="config",
            retryable=False,
            status=500,
            detail=f"no adapter for api_format: {a.provider.api_format}",
            depth=a.depth,
            provider_id=a.provider.id,
            served_model=a.model.provider_model,
        )
    key = os.environ.get(a.provider.auth_ref)
    if not key:
        raise ProviderError(
            label="config",
            retryable=False,
            status=500,
            detail=f"missing provider secret: {a.provider.auth_ref}",
            depth=a.depth,
            provider_id=a.provider.id,
            served_model=a.model.provider_model,
        )
    out_body: JSON = {k: v for k, v in body.items() if k not in _VOLATILE_KEYS} | {
        "model": a.model.provider_model
    }
    return adapter, key, out_body


def _backoff(depth: int) -> float:
    s = get_settings()
    ms = min(
        s.fallback_backoff_max_ms,
        s.fallback_backoff_base_ms * (s.fallback_backoff_factor**depth),
    )
    return ms / 1000.0


async def _attempt_once(http: httpx.AsyncClient, a: Attempt, body: JSON) -> JSON:
    adapter, key, out_body = _candidate_setup(a, body)
    headers = adapter.auth_headers(key)
    headers["content-type"] = "application/json"
    try:
        response = await http.post(
            a.provider.base_url + adapter.path,
            json=adapter.to_provider_request(out_body),
            headers=headers,
        )
    except httpx.TransportError as exc:
        raise from_exception(
            exc,
            depth=a.depth,
            provider_id=a.provider.id,
            served_model=a.model.provider_model,
        )
    if response.status_code >= 400:
        raise from_status(
            response.status_code,
            response.text,
            depth=a.depth,
            provider_id=a.provider.id,
            served_model=a.model.provider_model,
        )
    return adapter.from_provider_response(response.json())


async def _stream_attempt(
    http: httpx.AsyncClient, req: GatewayRequest, a: Attempt, body: JSON
) -> AsyncIterator[bytes]:
    """Open the upstream SSE stream and return a forward generator.

    The status peek happens here — inside walk_chain — so the failover decision is made
    before any token is yielded (ADR-002). On success the returned generator owns the
    AsyncExitStack that holds the HTTP stream open.
    """
    adapter, key, out_body = _candidate_setup(a, body)
    headers = adapter.auth_headers(key)
    headers["content-type"] = "application/json"
    stack = AsyncExitStack()
    try:
        response = await stack.enter_async_context(
            http.stream(
                "POST",
                a.provider.base_url + adapter.path,
                json=adapter.to_provider_stream_request(out_body),
                headers=headers,
            )
        )
    except httpx.TransportError as exc:
        await stack.aclose()
        raise from_exception(
            exc,
            depth=a.depth,
            provider_id=a.provider.id,
            served_model=a.model.provider_model,
        )
    if response.status_code >= 400:
        detail = (await response.aread()).decode()
        await stack.aclose()
        raise from_status(
            response.status_code,
            detail,
            depth=a.depth,
            provider_id=a.provider.id,
            served_model=a.model.provider_model,
        )

    async def forward() -> AsyncIterator[bytes]:
        async with stack:
            async for chunk in streaming.stream_openai(req, adapter, response):
                yield chunk

    return forward()


async def proxy_chat_completion(
    conn: asyncpg.Connection,
    http: httpx.AsyncClient,
    r: aioredis.Redis[str],  # type: ignore[type-arg]
    body: JSON,
    key: ApiKey | None = None,
) -> JSON:
    req = _parse(body)
    s = get_settings()
    bypass = should_bypass(body, temperature_bypass=s.semantic_temperature_bypass)
    t0 = time.monotonic()

    # Budget pre-check (hard-block before any upstream call).
    if key is not None:
        await check_budget(conn, r, key)

    h: str = ""
    embedding: list[float] | None = None

    if not bypass:
        h = exact.request_hash(body)
        cached = await exact.get(r, h)
        if cached is not None:
            latency_ms = int((time.monotonic() - t0) * 1000)
            pt, ct, tt = _usage_tokens(cached)
            await insert_request(
                conn,
                requested_model=req.model,
                served_provider_id=None,
                served_model=None,
                status="success",
                error_class=None,
                fallback_depth=0,
                cache_status="exact_hit",
                api_key_id=key.id if key else None,
                prompt_tokens=pt,
                completion_tokens=ct,
                total_tokens=tt,
                cost_cents=Decimal("0"),
                latency_ms=latency_ms,
            )
            return cached

        text = semantic.embed_text(body)
        if len(text) >= s.semantic_cache_min_chars:
            try:
                embedding = await semantic.embed(http, text)
            except Exception:
                pass  # embedding service unavailable — treat as miss, proceed
        if embedding is not None:
            cached_sem = await semantic.lookup(
                conn,
                embedding,
                requested_model=req.model,
                threshold=s.semantic_similarity_threshold,
            )
            if cached_sem is not None:
                latency_ms = int((time.monotonic() - t0) * 1000)
                pt, ct, tt = _usage_tokens(cached_sem)
                await insert_request(
                    conn,
                    requested_model=req.model,
                    served_provider_id=None,
                    served_model=None,
                    status="success",
                    error_class=None,
                    fallback_depth=0,
                    cache_status="semantic_hit",
                    api_key_id=key.id if key else None,
                    prompt_tokens=pt,
                    completion_tokens=ct,
                    total_tokens=tt,
                    cost_cents=Decimal("0"),
                    latency_ms=latency_ms,
                )
                return cached_sem

    chain = await _resolve(conn, req)

    async def attempt(a: Attempt) -> JSON:
        return await _attempt_once(http, a, body)

    try:
        result, won = await walk_chain(chain, attempt, backoff=_backoff)
    except ProviderError as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        await insert_request(
            conn,
            requested_model=req.model,
            served_provider_id=exc.provider_id,
            served_model=exc.served_model,
            status="error",
            error_class=exc.label,
            fallback_depth=exc.depth,
            cache_status="miss",
            api_key_id=key.id if key else None,
            latency_ms=latency_ms,
        )
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc

    latency_ms = int((time.monotonic() - t0) * 1000)
    pt, ct, tt = _usage_tokens(result)
    cents = cost_cents(won.model, pt, ct)

    await insert_request(
        conn,
        requested_model=req.model,
        served_provider_id=won.provider.id,
        served_model=won.model.provider_model,
        status="success",
        error_class=None,
        fallback_depth=won.depth,
        cache_status="miss",
        api_key_id=key.id if key else None,
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=tt,
        cost_cents=cents,
        latency_ms=latency_ms,
    )

    if key is not None:
        await record_spend(r, key.id, cents)

    if not bypass:
        await exact.put(r, h, result, s.exact_cache_ttl_seconds)
        if embedding is not None:
            try:
                await semantic.store(
                    conn,
                    request_hash=h,
                    embedding=embedding,
                    response=result,
                    requested_model=req.model,
                )
            except Exception:
                pass  # cache write is best-effort — must never fail an already-billed response

    return result


async def stream_chat_completion(
    conn: asyncpg.Connection,
    http: httpx.AsyncClient,
    r: aioredis.Redis[str],  # type: ignore[type-arg]
    body: JSON,
    key: ApiKey | None = None,
) -> AsyncIterator[bytes]:
    """Open an upstream SSE stream and forward it as a clean OpenAI-format stream.

    On a cache hit, replay the cached response as a synthetic chunk stream so the client
    sees the same SSE shape regardless of whether the reply came from the cache or a provider.
    Cache is written at stream close, after req.assembled_content is set by the engine.
    Token/cost columns are filled at stream close (Phase 5A). Latency is measured wall-clock
    from entry to first-byte (for the non-cache path, end of stream-open chain resolution).
    """
    req = _parse(body)
    s = get_settings()
    bypass = should_bypass(body, temperature_bypass=s.semantic_temperature_bypass)
    t0 = time.monotonic()

    # Budget pre-check (hard-block before any upstream call).
    if key is not None:
        await check_budget(conn, r, key)

    h: str = ""
    embedding: list[float] | None = None

    if not bypass:
        h = exact.request_hash(body)
        cached = await exact.get(r, h)
        if cached is not None:
            latency_ms = int((time.monotonic() - t0) * 1000)
            pt, ct, tt = _usage_tokens(cached)
            await insert_request(
                conn,
                requested_model=req.model,
                served_provider_id=None,
                served_model=None,
                status="success",
                error_class=None,
                fallback_depth=0,
                cache_status="exact_hit",
                api_key_id=key.id if key else None,
                prompt_tokens=pt,
                completion_tokens=ct,
                total_tokens=tt,
                cost_cents=Decimal("0"),
                latency_ms=latency_ms,
            )
            async for chunk in synthetic_stream(cached):
                yield chunk
            return

        text = semantic.embed_text(body)
        if len(text) >= s.semantic_cache_min_chars:
            try:
                embedding = await semantic.embed(http, text)
            except Exception:
                pass  # embedding service unavailable — treat as miss, proceed
        if embedding is not None:
            cached_sem = await semantic.lookup(
                conn,
                embedding,
                requested_model=req.model,
                threshold=s.semantic_similarity_threshold,
            )
            if cached_sem is not None:
                latency_ms = int((time.monotonic() - t0) * 1000)
                pt, ct, tt = _usage_tokens(cached_sem)
                await insert_request(
                    conn,
                    requested_model=req.model,
                    served_provider_id=None,
                    served_model=None,
                    status="success",
                    error_class=None,
                    fallback_depth=0,
                    cache_status="semantic_hit",
                    api_key_id=key.id if key else None,
                    prompt_tokens=pt,
                    completion_tokens=ct,
                    total_tokens=tt,
                    cost_cents=Decimal("0"),
                    latency_ms=latency_ms,
                )
                async for chunk in synthetic_stream(cached_sem):
                    yield chunk
                return

    chain = await _resolve(conn, req)

    async def attempt(a: Attempt) -> AsyncIterator[bytes]:
        return await _stream_attempt(http, req, a, body)

    try:
        gen, won = await walk_chain(chain, attempt, backoff=_backoff)
    except ProviderError as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        await insert_request(
            conn,
            requested_model=req.model,
            served_provider_id=exc.provider_id,
            served_model=exc.served_model,
            status="error",
            error_class=exc.label,
            fallback_depth=exc.depth,
            cache_status="miss",
            api_key_id=key.id if key else None,
            latency_ms=latency_ms,
        )
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc

    latency_ms = int((time.monotonic() - t0) * 1000)

    # Persist at stream-open — all chain info is known pre-first-token.
    # Token/cost columns are filled after stream close via update_request_usage.
    request_id = await insert_request(
        conn,
        requested_model=req.model,
        served_provider_id=won.provider.id,
        served_model=won.model.provider_model,
        status="success",
        error_class=None,
        fallback_depth=won.depth,
        cache_status="miss",
        api_key_id=key.id if key else None,
        latency_ms=latency_ms,
    )

    async for chunk in gen:
        yield chunk

    # Stream closed — req.usage is populated by the streaming engine.
    # GeneratorExit (client disconnect) skips this block; incomplete streams are not costed.
    if req.usage:
        pt = int(req.usage.get("prompt_tokens", 0))
        ct = int(req.usage.get("completion_tokens", 0))
        tt = int(req.usage.get("total_tokens", 0))
        cents = cost_cents(won.model, pt, ct)
        await update_request_usage(
            conn,
            request_id=request_id,
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=tt,
            cost_cents=cents,
        )
        if key is not None:
            await record_spend(r, key.id, cents)

    # Write cache after stream close — req.assembled_content is set by the engine once
    # the async for loop above exhausts the generator. GeneratorExit (client disconnect)
    # skips this block, so incomplete streams are never cached.
    if not bypass:
        response = assembled_to_response(req, req.model)
        await exact.put(r, h, response, s.exact_cache_ttl_seconds)
        if embedding is not None:
            try:
                await semantic.store(
                    conn,
                    request_hash=h,
                    embedding=embedding,
                    response=response,
                    requested_model=req.model,
                )
            except Exception:
                pass  # cache write is best-effort — must never fail an already-billed response
