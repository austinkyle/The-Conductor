"""Integration test for the proxy path with the provider mocked.

The senior-signal assertion: the client gets an identical OpenAI-shaped response
regardless of which provider served the request. Uses httpx's built-in MockTransport
(no new dependency) and stubs model resolution so the test needs no database.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import cast

import asyncpg
import httpx
import pytest

from core import pipeline
from core.config import get_settings
from db.models import Model, Provider
from translation.base import JSON

_NOW = datetime.now(timezone.utc)

# What each upstream returns. The OpenAI body is already in the public shape (the
# OpenAI adapter is pass-through); the Anthropic body is in Anthropic's native shape.
_OPENAI_UPSTREAM: JSON = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-4o-mini",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "Hello there!"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
}
_ANTHROPIC_UPSTREAM: JSON = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-3-5-sonnet-latest",
    "content": [{"type": "text", "text": "Hello there!"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 10, "output_tokens": 3},
}


def _resolve(model: str) -> tuple[Model, Provider]:
    if model == "gpt-4o-mini":
        provider = Provider(1, "openai", "https://api.openai.com/v1", "OPENAI_API_KEY", "openai", _NOW)
        m = Model(1, model, 1, model, Decimal("0.15"), Decimal("0.60"), _NOW)
    else:
        provider = Provider(2, "anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", "anthropic", _NOW)
        m = Model(2, model, 2, model, Decimal("3"), Decimal("15"), _NOW)
    return m, provider


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/chat/completions"):
        return httpx.Response(200, json=_OPENAI_UPSTREAM)
    if request.url.path.endswith("/messages"):
        return httpx.Response(200, json=_ANTHROPIC_UPSTREAM)
    return httpx.Response(404, json={"error": "unexpected path"})


def _content(resp: JSON) -> str:
    choices = resp["choices"]
    assert isinstance(choices, list)
    choice = choices[0]
    assert isinstance(choice, dict)
    message = choice["message"]
    assert isinstance(message, dict)
    text = message["content"]
    assert isinstance(text, str)
    return text


async def _proxy(model: str) -> JSON:
    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as http:
        conn = cast(asyncpg.Connection, None)
        r = cast(object, None)  # bypass forced; redis never accessed
        return await pipeline.proxy_chat_completion(
            conn, http, r, {"model": model, "messages": [{"role": "user", "content": "Hi"}]}  # type: ignore[arg-type]
        )


@pytest.fixture(autouse=True)
def _env_and_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost")
    get_settings.cache_clear()

    async def fake_resolve_chain(conn: object, model: str) -> list[tuple[Model, Provider]]:
        return [_resolve(model)]

    async def fake_insert_request(conn: object, **kwargs: object) -> int:
        return 1

    monkeypatch.setattr(pipeline, "resolve_chain", fake_resolve_chain)
    monkeypatch.setattr(pipeline, "insert_request", fake_insert_request)
    # Force bypass so existing tests need no redis/embed infrastructure.
    monkeypatch.setattr(pipeline, "should_bypass", lambda body, temperature_bypass=0.3: "skip_cache")


async def test_identical_openai_response_from_both_providers() -> None:
    via_openai = await _proxy("gpt-4o-mini")
    via_anthropic = await _proxy("claude-3-5-sonnet-latest")

    # Same content and usage regardless of which provider served it.
    assert _content(via_openai) == "Hello there!"
    assert _content(via_anthropic) == "Hello there!"
    assert via_openai["object"] == "chat.completion"
    assert via_anthropic["object"] == "chat.completion"
    assert via_openai["usage"] == via_anthropic["usage"]
    assert via_openai["choices"] == via_anthropic["choices"]


async def test_cache_control_key_not_forwarded_upstream() -> None:
    """The `cache` control field is for the gateway only — it must never reach the
    upstream provider. The OpenAI adapter is a pass-through, so this is the one path
    where a leak would actually be visible on the wire."""
    captured: list[JSON] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(cast(JSON, json.loads(request.content)))
        return httpx.Response(200, json=_OPENAI_UPSTREAM)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        conn = cast(asyncpg.Connection, None)
        r = cast(object, None)  # bypass forced; redis never accessed
        await pipeline.proxy_chat_completion(
            conn,
            http,
            r,  # type: ignore[arg-type]
            {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Hi"}],
                "cache": {"no_cache": True},
            },
        )

    assert len(captured) == 1
    assert "cache" not in captured[0]
