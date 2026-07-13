"""Streaming tests: per-adapter stream-event translation (pure), the engine's buffering +
usage reconciliation, and an end-to-end SSE stream with the provider mocked.

The senior-signal assertion mirrors the non-streaming proxy: the client sees an identical,
clean OpenAI-format stream regardless of which provider served it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from decimal import Decimal
from typing import cast

import asyncpg
import httpx
import pytest

from cache import exact, semantic
from cache.guardrails import should_bypass
from core import pipeline, streaming
from core.config import get_settings
from core.request import GatewayRequest
from core.streaming import SSEEvent
from db.models import Model, Provider
from translation.anthropic import AnthropicAdapter
from translation.base import JSON
from translation.openai import OpenAIAdapter

_NOW = datetime.now(timezone.utc)

# Canonical provider stream-event sequences (one tidy "Hello there!" completion each).
_OPENAI_CHUNKS: list[JSON] = [
    {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o-mini",
     "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
    {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o-mini",
     "choices": [{"index": 0, "delta": {"content": "Hello there!"}, "finish_reason": None}]},
    {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o-mini",
     "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o-mini",
     "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}},
]
_ANTHROPIC_EVENTS: list[tuple[str, JSON]] = [
    ("message_start", {"type": "message_start", "message": {
        "id": "msg_1", "model": "claude-3-5-sonnet-latest",
        "usage": {"input_tokens": 10, "output_tokens": 0}}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0,
        "delta": {"type": "text_delta", "text": "Hello there!"}}),
    ("message_delta", {"type": "message_delta",
        "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 3}}),
    ("message_stop", {"type": "message_stop"}),
]

_EXPECTED_USAGE: JSON = {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}


async def _aiter(events: list[SSEEvent]) -> AsyncIterator[SSEEvent]:
    for event in events:
        yield event


def _delta_content(chunk: JSON) -> str:
    """Pull `choices[0].delta.content` from a chunk, or '' if absent."""
    choices = chunk["choices"]
    assert isinstance(choices, list)
    if not choices:
        return ""
    delta = choices[0]["delta"]
    assert isinstance(delta, dict)
    content = delta.get("content")
    return content if isinstance(content, str) else ""


# --- per-adapter stream translation (pure, no network) ---

async def test_openai_stream_is_passthrough() -> None:
    events = [SSEEvent(event=None, data=json.dumps(c)) for c in _OPENAI_CHUNKS]
    out = [c async for c in OpenAIAdapter().from_provider_stream(_aiter(events))]
    assert out == _OPENAI_CHUNKS  # identity transform


async def test_anthropic_stream_maps_to_openai_chunks() -> None:
    events = [SSEEvent(event=name, data=json.dumps(d)) for name, d in _ANTHROPIC_EVENTS]
    out = [c async for c in AnthropicAdapter().from_provider_stream(_aiter(events))]

    # role chunk, one content chunk, final finish chunk, terminal usage chunk.
    assert len(out) == 4
    first_delta = cast("dict[str, object]", cast("list[object]", out[0]["choices"])[0])["delta"]
    assert first_delta == {"role": "assistant"}
    assert "".join(_delta_content(c) for c in out) == "Hello there!"
    final_choice = cast("dict[str, object]", cast("list[object]", out[2]["choices"])[0])
    assert final_choice["finish_reason"] == "stop"
    assert out[3]["choices"] == []
    assert out[3]["usage"] == _EXPECTED_USAGE


# --- engine: buffering + usage reconciliation onto the request ---

class _FakeResponse:
    """Minimal stand-in for httpx.Response exposing just `aiter_lines`."""

    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._raw.decode().split("\n"):
            yield line


async def test_engine_reconciles_usage_and_buffers_content() -> None:
    raw = _sse_bytes_anthropic()
    req = GatewayRequest(body={}, model="claude-3-5-sonnet-latest", stream=True)
    response = cast(httpx.Response, _FakeResponse(raw))

    frames = [f async for f in streaming.stream_openai(req, AnthropicAdapter(), response)]

    assert frames[-1] == b"data: [DONE]\n\n"
    assert req.assembled_content == "Hello there!"
    assert req.usage == _EXPECTED_USAGE


# --- end-to-end through the pipeline with the provider mocked ---

def _sse_bytes_openai() -> bytes:
    out = b""
    for chunk in _OPENAI_CHUNKS:
        out += b"data: " + json.dumps(chunk).encode() + b"\n\n"
    return out + b"data: [DONE]\n\n"


def _sse_bytes_anthropic() -> bytes:
    out = b""
    for name, data in _ANTHROPIC_EVENTS:
        out += f"event: {name}\n".encode() + b"data: " + json.dumps(data).encode() + b"\n\n"
    return out


def _resolve(model: str) -> tuple[Model, Provider]:
    if model == "gpt-4o-mini":
        provider = Provider(1, "openai", "https://api.openai.com/v1", "OPENAI_API_KEY", "openai", _NOW)
        m = Model(1, model, 1, model, Decimal("0.15"), Decimal("0.60"), _NOW)
    else:
        provider = Provider(2, "anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", "anthropic", _NOW)
        m = Model(2, model, 2, model, Decimal("3"), Decimal("15"), _NOW)
    return m, provider


def _handler(request: httpx.Request) -> httpx.Response:
    headers = {"content-type": "text/event-stream"}
    if request.url.path.endswith("/chat/completions"):
        return httpx.Response(200, content=_sse_bytes_openai(), headers=headers)
    if request.url.path.endswith("/messages"):
        return httpx.Response(200, content=_sse_bytes_anthropic(), headers=headers)
    return httpx.Response(404, json={"error": "unexpected path"})


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

    async def fake_update_request_usage(conn: object, **kwargs: object) -> None:
        pass

    monkeypatch.setattr(pipeline, "resolve_chain", fake_resolve_chain)
    monkeypatch.setattr(pipeline, "insert_request", fake_insert_request)
    monkeypatch.setattr(pipeline, "update_request_usage", fake_update_request_usage)
    monkeypatch.setattr(pipeline, "should_bypass", lambda body, temperature_bypass=0.3: "skip_cache")


def _parse_data_chunks(frames: list[bytes]) -> list[JSON]:
    chunks: list[JSON] = []
    for block in b"".join(frames).decode().split("\n\n"):
        block = block.strip()
        if not block.startswith("data: "):
            continue
        data = block[len("data: "):]
        if data != "[DONE]":
            chunks.append(json.loads(data))
    return chunks


async def _stream(model: str) -> list[bytes]:
    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as http:
        conn = cast(asyncpg.Connection, None)
        return [
            frame
            async for frame in pipeline.stream_chat_completion(
                conn, http, None, {"model": model, "messages": [{"role": "user", "content": "Hi"}], "stream": True}  # type: ignore[arg-type]
            )
        ]


async def test_clean_openai_stream_from_both_providers() -> None:
    via_openai = await _stream("gpt-4o-mini")
    via_anthropic = await _stream("claude-3-5-sonnet-latest")

    for frames in (via_openai, via_anthropic):
        assert frames[-1] == b"data: [DONE]\n\n"  # clean OpenAI terminator
        chunks = _parse_data_chunks(frames)
        assert "".join(_delta_content(c) for c in chunks) == "Hello there!"
        # The reconciled usage is visible in-band as a terminal usage chunk.
        usage_chunks = [c for c in chunks if "usage" in c]
        assert usage_chunks and usage_chunks[-1]["usage"] == _EXPECTED_USAGE


# ---------------------------------------------------------------------------
# Cache-check integration for the streaming branch: exact hit / semantic hit /
# cache-write-after-close / bypass reasons. Mirrors test_proxy.py's cache tests
# but asserts synthetic-stream replay + upstream-never-opened for hits, and that
# the cache write happens only after the generator is fully drained.
# ---------------------------------------------------------------------------

class _RecordingInsert:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def __call__(self, conn: object, **kwargs: object) -> int:
        self.calls.append(kwargs)
        return 1


def _cached_response() -> JSON:
    return {
        "id": "chatcmpl-cached",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o-mini",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "Cached!"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }


async def _stream_with_cache(
    monkeypatch: pytest.MonkeyPatch,
    body: JSON,
    *,
    exact_hit: JSON | None = None,
    semantic_hit: JSON | None = None,
    upstream_called: list[bool] | None = None,
) -> tuple[list[bytes], _RecordingInsert, list[JSON], list[object]]:
    recorder = _RecordingInsert()
    monkeypatch.setattr(pipeline, "insert_request", recorder)
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
        headers = {"content-type": "text/event-stream"}
        return httpx.Response(200, content=_sse_bytes_openai(), headers=headers)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        conn = cast(asyncpg.Connection, None)
        frames = [
            frame
            async for frame in pipeline.stream_chat_completion(conn, http, None, body)  # type: ignore[arg-type]
        ]
    return frames, recorder, put_calls, store_calls


def _base_stream_body() -> JSON:
    return {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}], "stream": True}


async def test_stream_exact_hit_replays_synthetic_and_skips_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    cached = _cached_response()
    frames, recorder, put_calls, _ = await _stream_with_cache(
        monkeypatch, _base_stream_body(), exact_hit=cached, upstream_called=called
    )
    assert called == []
    combined = b"".join(frames).decode()
    assert "Cached!" in combined
    assert frames[-1] == b"data: [DONE]\n\n"
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["cache_status"] == "exact_hit"
    assert put_calls == []  # a hit never re-writes the cache


async def test_stream_semantic_hit_after_exact_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    cached = _cached_response()
    frames, recorder, put_calls, _ = await _stream_with_cache(
        monkeypatch, _base_stream_body(), exact_hit=None, semantic_hit=cached, upstream_called=called
    )
    assert called == []
    combined = b"".join(frames).decode()
    assert "Cached!" in combined
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["cache_status"] == "semantic_hit"
    assert put_calls == []


async def test_stream_true_miss_writes_cache_only_after_close(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    frames, recorder, put_calls, store_calls = await _stream_with_cache(
        monkeypatch, _base_stream_body(), exact_hit=None, semantic_hit=None, upstream_called=called
    )
    assert called == [True]
    assert frames[-1] == b"data: [DONE]\n\n"
    # cache_status="miss" is recorded at stream-open, before any content is known.
    assert recorder.calls[0]["cache_status"] == "miss"
    # cache write happens only once the generator (and thus the stream) is drained.
    assert len(put_calls) == 1
    assert put_calls[0]["choices"][0]["message"]["content"] == "Hello there!"  # type: ignore[index]
    assert len(store_calls) == 1


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
async def test_stream_bypass_reason_recorded_as_cache_status(
    monkeypatch: pytest.MonkeyPatch, body_extra: JSON, expected_reason: str
) -> None:
    called: list[bool] = []
    body = {**_base_stream_body(), **body_extra}
    _, recorder, put_calls, store_calls = await _stream_with_cache(monkeypatch, body, upstream_called=called)
    assert called == [True]
    assert recorder.calls[0]["cache_status"] == expected_reason
    assert put_calls == []
    assert store_calls == []
