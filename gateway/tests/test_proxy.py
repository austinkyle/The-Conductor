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

from cache import exact, semantic
from cache.guardrails import should_bypass
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


# ---------------------------------------------------------------------------
# Cache-check integration: exact hit / semantic hit / true miss / bypass reasons
#
# Unlike the fixture above, these tests do NOT force a blanket bypass — they
# drive should_bypass for real and stub the cache submodules directly on
# `pipeline` so the cache-check path inside proxy_chat_completion is actually
# exercised end to end.
# ---------------------------------------------------------------------------

class _RecordingInsert:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def __call__(self, conn: object, **kwargs: object) -> int:
        self.calls.append(kwargs)
        return 1


async def _proxy_with_cache(
    monkeypatch: pytest.MonkeyPatch,
    body: JSON,
    *,
    exact_hit: JSON | None = None,
    semantic_hit: JSON | None = None,
    upstream_called: list[bool] | None = None,
) -> tuple[JSON, _RecordingInsert]:
    recorder = _RecordingInsert()
    monkeypatch.setattr(pipeline, "insert_request", recorder)
    # The module-level autouse fixture forces a blanket bypass; undo that here so
    # these tests exercise the real cache-check path.
    monkeypatch.setattr(pipeline, "should_bypass", should_bypass)

    async def fake_exact_get(r: object, h: str) -> JSON | None:
        return exact_hit

    put_calls: list[JSON] = []

    async def fake_exact_put(r: object, h: str, response: JSON, ttl: int) -> None:
        put_calls.append(response)

    monkeypatch.setattr(exact, "get", fake_exact_get)
    monkeypatch.setattr(exact, "put", fake_exact_put)

    async def fake_embed(http: object, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    async def fake_lookup(conn: object, embedding: object, *, requested_model: str, threshold: float) -> JSON | None:
        return semantic_hit

    store_calls: list[object] = []

    async def fake_store(conn: object, **kwargs: object) -> None:
        store_calls.append(kwargs)

    monkeypatch.setattr(semantic, "embed", fake_embed)
    monkeypatch.setattr(semantic, "lookup", fake_lookup)
    monkeypatch.setattr(semantic, "store", fake_store)

    def handler(request: httpx.Request) -> httpx.Response:
        if upstream_called is not None:
            upstream_called.append(True)
        return httpx.Response(200, json=_OPENAI_UPSTREAM)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        conn = cast(asyncpg.Connection, None)
        r = cast(object, None)
        result = await pipeline.proxy_chat_completion(conn, http, r, body)  # type: ignore[arg-type]

    result_with_extras = cast(JSON, {**result, "_put_calls": put_calls, "_store_calls": store_calls})
    return result_with_extras, recorder


def _base_body() -> JSON:
    return {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]}


async def test_exact_hit_skips_upstream_and_records_exact_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    result, recorder = await _proxy_with_cache(
        monkeypatch, _base_body(), exact_hit=_OPENAI_UPSTREAM, upstream_called=called
    )
    assert called == []
    assert result["choices"] == _OPENAI_UPSTREAM["choices"]
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["cache_status"] == "exact_hit"


async def test_semantic_hit_after_exact_miss_records_semantic_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    result, recorder = await _proxy_with_cache(
        monkeypatch, _base_body(), exact_hit=None, semantic_hit=_OPENAI_UPSTREAM, upstream_called=called
    )
    assert called == []
    assert result["choices"] == _OPENAI_UPSTREAM["choices"]
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["cache_status"] == "semantic_hit"


async def test_true_miss_calls_upstream_and_writes_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    result, recorder = await _proxy_with_cache(
        monkeypatch, _base_body(), exact_hit=None, semantic_hit=None, upstream_called=called
    )
    assert called == [True]
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["cache_status"] == "miss"
    put_calls = cast(list[JSON], result["_put_calls"])
    assert len(put_calls) == 1


@pytest.mark.parametrize(
    ("body_extra", "expected_reason"),
    [
        ({"temperature": 0.9}, "temperature"),
        ({"cache": False}, "no_cache"),
        ({"cache": {"no_cache": True}}, "no_cache"),
        ({"cache": {"recent_context": True}}, "recent_context"),
        ({"tools": [{"type": "function", "function": {"name": "f"}}]}, "tool_use"),
    ],
)
async def test_bypass_reason_recorded_as_cache_status(
    monkeypatch: pytest.MonkeyPatch, body_extra: JSON, expected_reason: str
) -> None:
    called: list[bool] = []
    body = {**_base_body(), **body_extra}
    result, recorder = await _proxy_with_cache(monkeypatch, body, upstream_called=called)
    assert called == [True]
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["cache_status"] == expected_reason
    # bypassed requests never touch the cache.
    assert cast(list[JSON], result["_put_calls"]) == []
    assert cast(list[object], result["_store_calls"]) == []


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
