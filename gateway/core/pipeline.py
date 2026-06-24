"""The single request path. Phase 1, non-streaming:

    parse -> resolve model to provider -> translate out -> call -> translate in -> respond

Routing is a direct model lookup (no aliases/fallback yet — Phase 3) and provider
errors are surfaced as-is (no retryable-vs-terminal classification yet — Phase 3).
The `stream` branch lands in Phase 2; for now a streaming request is refused honestly.
"""

from __future__ import annotations

import os

import asyncpg
import httpx
from fastapi import HTTPException

from core.request import GatewayRequest
from db.queries import resolve_model
from translation.anthropic import AnthropicAdapter
from translation.base import JSON, Adapter
from translation.openai import OpenAIAdapter

# One adapter per provider, selected by providers.name.
_ADAPTERS: dict[str, Adapter] = {
    "openai": OpenAIAdapter(),
    "anthropic": AnthropicAdapter(),
}


async def proxy_chat_completion(
    conn: asyncpg.Connection, http: httpx.AsyncClient, body: JSON
) -> JSON:
    try:
        req = GatewayRequest.from_body(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if req.stream:
        raise HTTPException(status_code=501, detail="streaming not implemented until Phase 2")

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

    # Forward the concrete provider model, not the requested alias.
    out_body: JSON = {**body, "model": model.provider_model}
    provider_request = adapter.to_provider_request(out_body)

    headers = adapter.auth_headers(key)
    headers["content-type"] = "application/json"
    response = await http.post(
        provider.base_url + adapter.path, json=provider_request, headers=headers
    )
    if response.status_code >= 400:
        # Phase 3 classifies these and may fail over; Phase 1 surfaces them verbatim.
        raise HTTPException(status_code=response.status_code, detail=response.text)

    req.served_provider = provider.name
    req.served_model = model.provider_model
    return adapter.from_provider_response(response.json())
