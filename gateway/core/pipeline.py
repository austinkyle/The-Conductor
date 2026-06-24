"""The single request path. Two branches share the same setup:

    parse -> resolve model to provider -> translate out -> call -> translate in -> respond

`proxy_chat_completion` walks the non-streaming branch; `stream_chat_completion` walks the
SSE branch (core/streaming.py). Routing is a direct model lookup (no aliases/fallback yet —
Phase 3) and provider errors are surfaced as-is (no retryable-vs-terminal classification yet
— Phase 3). Mid-stream failover is intentionally unsupported (ADR-002): a streaming error
can only surface cleanly before the first token, which is where the status check below sits.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import asyncpg
import httpx
from fastapi import HTTPException

from core import streaming
from core.request import GatewayRequest
from db.models import Provider
from db.queries import resolve_model
from translation.anthropic import AnthropicAdapter
from translation.base import JSON, Adapter
from translation.openai import OpenAIAdapter

# One adapter per provider, selected by providers.name.
_ADAPTERS: dict[str, Adapter] = {
    "openai": OpenAIAdapter(),
    "anthropic": AnthropicAdapter(),
}


async def _prepare(
    conn: asyncpg.Connection, body: JSON
) -> tuple[GatewayRequest, Adapter, Provider, str, JSON]:
    """Shared setup for both branches: parse, resolve, pick adapter, resolve key, build
    the outbound body with the concrete provider model. Raises HTTPException on any failure
    that should reach the caller before forwarding."""
    try:
        req = GatewayRequest.from_body(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    resolved = await resolve_model(conn, req.model)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"unknown model: {req.model}")
    model, provider = resolved

    adapter = _ADAPTERS.get(provider.name)
    if adapter is None:
        raise HTTPException(status_code=500, detail=f"no adapter for provider: {provider.name}")

    key = os.environ.get(provider.auth_ref)
    if not key:
        raise HTTPException(status_code=500, detail=f"missing provider secret: {provider.auth_ref}")

    req.served_provider = provider.name
    req.served_model = model.provider_model
    # Forward the concrete provider model, not the requested alias.
    out_body: JSON = {**body, "model": model.provider_model}
    return req, adapter, provider, key, out_body


async def proxy_chat_completion(
    conn: asyncpg.Connection, http: httpx.AsyncClient, body: JSON
) -> JSON:
    req, adapter, provider, key, out_body = await _prepare(conn, body)
    provider_request = adapter.to_provider_request(out_body)

    headers = adapter.auth_headers(key)
    headers["content-type"] = "application/json"
    response = await http.post(
        provider.base_url + adapter.path, json=provider_request, headers=headers
    )
    if response.status_code >= 400:
        # Phase 3 classifies these and may fail over; Phase 1 surfaces them verbatim.
        raise HTTPException(status_code=response.status_code, detail=response.text)

    return adapter.from_provider_response(response.json())


async def stream_chat_completion(
    conn: asyncpg.Connection, http: httpx.AsyncClient, body: JSON
) -> AsyncIterator[bytes]:
    """Open an upstream SSE stream and forward it as a clean OpenAI-format stream. The
    response is buffered and usage reconciled at close (core/streaming.py)."""
    req, adapter, provider, key, out_body = await _prepare(conn, body)
    provider_request = adapter.to_provider_stream_request(out_body)

    headers = adapter.auth_headers(key)
    headers["content-type"] = "application/json"
    async with http.stream(
        "POST", provider.base_url + adapter.path, json=provider_request, headers=headers
    ) as response:
        if response.status_code >= 400:
            # Pre-first-token, so a clean error to the client (no mid-stream failover — ADR-002).
            detail = (await response.aread()).decode()
            raise HTTPException(status_code=response.status_code, detail=detail)
        async for chunk in streaming.stream_openai(req, adapter, response):
            yield chunk
