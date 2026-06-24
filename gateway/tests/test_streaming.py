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

from core import pipeline, streaming
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
        provider = Provider(1, "openai", "https://api.openai.com/v1", "OPENAI_API_KEY", _NOW)
        m = Model(1, model, 1, model, Decimal("0.15"), Decimal("0.60"), _NOW)
    else:
        provider = Provider(2, "anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", _NOW)
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

    async def fake_resolve(conn: object, model: str) -> tuple[Model, Provider]:
        return _resolve(model)

    monkeypatch.setattr(pipeline, "resolve_model", fake_resolve)


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
        conn = cast(asyncpg.Connection, None)  # fake_resolve ignores the connection
        return [
            frame
            async for frame in pipeline.stream_chat_completion(
                conn, http, {"model": model, "messages": [{"role": "user", "content": "Hi"}], "stream": True}
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
