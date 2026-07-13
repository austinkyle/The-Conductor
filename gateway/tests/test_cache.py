"""Tests for the two-layer cache: guardrails, exact match, semantic, and synthetic replay.

Fake helpers replace Redis and asyncpg so tests run without external services:
  _FakeRedis  — in-memory dict with the get/setex interface
  _FakeConn   — captures fetchrow/execute calls; fetchrow returns a preset _FakeRow
  _FakeRow    — dict-like, used for semantic_cache lookup results
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import cast

import asyncpg
import pytest

from cache import exact, semantic
from cache.guardrails import should_bypass
from cache.replay import assembled_to_response, synthetic_stream
from core.request import GatewayRequest
from translation.base import JSON

# ---------------------------------------------------------------------------
# Fake infrastructure
# ---------------------------------------------------------------------------

class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value.encode()


class _FakeRow:
    def __init__(self, similarity: float, response_body: JSON) -> None:
        self._data: dict[str, object] = {
            "similarity": similarity,
            "response_body": response_body,
        }

    def __getitem__(self, key: str) -> object:
        return self._data[key]


class _FakeConn:
    def __init__(self, row: _FakeRow | None = None) -> None:
        self._row = row
        self.stored: list[tuple[object, ...]] = []

    async def fetchrow(self, query: str, *args: object) -> _FakeRow | None:
        return self._row

    async def execute(self, query: str, *args: object) -> None:
        self.stored.append(args)


_CACHED_RESPONSE: JSON = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-4o-mini",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
}

# ---------------------------------------------------------------------------
# guardrails.should_bypass — pure function tests
# ---------------------------------------------------------------------------

def test_bypass_high_temperature() -> None:
    body: JSON = {"model": "gpt-4", "temperature": 0.9, "messages": []}
    assert should_bypass(body) == "temperature"


def test_no_bypass_at_exact_threshold() -> None:
    # temperature == threshold is NOT a bypass (> not >=)
    body: JSON = {"model": "gpt-4", "temperature": 0.3, "messages": []}
    assert should_bypass(body) is None


def test_no_bypass_below_threshold() -> None:
    body: JSON = {"model": "gpt-4", "temperature": 0.1, "messages": []}
    assert should_bypass(body) is None


def test_bypass_custom_threshold() -> None:
    body: JSON = {"model": "gpt-4", "temperature": 0.5, "messages": []}
    assert should_bypass(body, temperature_bypass=0.4) == "temperature"
    assert should_bypass(body, temperature_bypass=0.6) is None


def test_bypass_cache_false() -> None:
    body: JSON = {"model": "gpt-4", "cache": False, "messages": []}
    assert should_bypass(body) == "no_cache"


def test_bypass_cache_no_cache_dict() -> None:
    body: JSON = {"model": "gpt-4", "cache": {"no_cache": True}, "messages": []}
    assert should_bypass(body) == "no_cache"


def test_bypass_cache_recent_context_dict() -> None:
    body: JSON = {"model": "gpt-4", "cache": {"recent_context": True}, "messages": []}
    assert should_bypass(body) == "recent_context"


def test_bypass_tools_non_empty() -> None:
    body: JSON = {"model": "gpt-4", "tools": [{"type": "function", "function": {"name": "get_weather"}}], "messages": []}
    assert should_bypass(body) == "tool_use"


def test_no_bypass_tools_empty() -> None:
    body: JSON = {"model": "gpt-4", "tools": [], "messages": []}
    assert should_bypass(body) is None


def test_bypass_functions_non_empty() -> None:
    body: JSON = {"model": "gpt-4", "functions": [{"name": "f"}], "messages": []}
    assert should_bypass(body) == "tool_use"


def test_bypass_tool_choice_auto() -> None:
    body: JSON = {"model": "gpt-4", "tool_choice": "auto", "messages": []}
    assert should_bypass(body) == "tool_use"


def test_bypass_tool_choice_required() -> None:
    body: JSON = {"model": "gpt-4", "tool_choice": "required", "messages": []}
    assert should_bypass(body) == "tool_use"


def test_bypass_tool_choice_dict() -> None:
    body: JSON = {"model": "gpt-4", "tool_choice": {"type": "function", "function": {"name": "f"}}, "messages": []}
    assert should_bypass(body) == "tool_use"


def test_no_bypass_tool_choice_none_string() -> None:
    body: JSON = {"model": "gpt-4", "tool_choice": "none", "messages": []}
    assert should_bypass(body) is None


def test_no_bypass_plain_request() -> None:
    body: JSON = {"model": "gpt-4", "messages": [{"role": "user", "content": "Hi"}]}
    assert should_bypass(body) is None


# Temperature bypass takes priority over tool_choice check (temperature checked first).
def test_temperature_checked_before_tool_choice() -> None:
    body: JSON = {"model": "gpt-4", "temperature": 1.0, "tool_choice": "auto", "messages": []}
    assert should_bypass(body) == "temperature"


def test_no_bypass_cache_no_cache_false() -> None:
    # cache: {no_cache: False} is falsy — should NOT trigger bypass
    body: JSON = {"model": "gpt-4", "cache": {"no_cache": False}, "messages": []}
    assert should_bypass(body) is None


def test_no_bypass_cache_unrelated_key() -> None:
    # cache: {ttl: 60} has no recognized bypass key
    body: JSON = {"model": "gpt-4", "cache": {"ttl": 60}, "messages": []}
    assert should_bypass(body) is None


def test_bypass_tool_choice_empty_dict() -> None:
    # tool_choice: {} is isinstance(dict) — triggers bypass regardless of contents
    body: JSON = {"model": "gpt-4", "tool_choice": {}, "messages": []}
    assert should_bypass(body) == "tool_use"


# ---------------------------------------------------------------------------
# exact cache
# ---------------------------------------------------------------------------

def test_normalize_drops_stream_key() -> None:
    a = exact.normalize({"model": "gpt-4", "stream": True, "messages": []})
    b = exact.normalize({"model": "gpt-4", "messages": []})
    assert a == b


def test_normalize_drops_stream_options_key() -> None:
    a = exact.normalize({"model": "gpt-4", "stream_options": {"include_usage": True}, "messages": []})
    b = exact.normalize({"model": "gpt-4", "messages": []})
    assert a == b


def test_normalize_drops_cache_key() -> None:
    a = exact.normalize({"model": "gpt-4", "cache": {"no_cache": True}, "messages": []})
    b = exact.normalize({"model": "gpt-4", "messages": []})
    assert a == b


def test_hash_is_deterministic() -> None:
    body: JSON = {"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}]}
    assert exact.request_hash(body) == exact.request_hash(body)


def test_hash_differs_for_different_body() -> None:
    a: JSON = {"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}]}
    b: JSON = {"model": "gpt-4", "messages": [{"role": "user", "content": "Hi"}]}
    assert exact.request_hash(a) != exact.request_hash(b)


def test_hash_stream_flag_ignored() -> None:
    a: JSON = {"model": "gpt-4", "messages": [], "stream": True}
    b: JSON = {"model": "gpt-4", "messages": []}
    assert exact.request_hash(a) == exact.request_hash(b)


async def test_exact_get_miss() -> None:
    r = cast(object, _FakeRedis())
    result = await exact.get(r, "missing")  # type: ignore[arg-type]
    assert result is None


async def test_exact_get_hit() -> None:
    r = _FakeRedis()
    r._store["key1"] = json.dumps(_CACHED_RESPONSE).encode()
    result = await exact.get(r, "key1")  # type: ignore[arg-type]
    assert result == _CACHED_RESPONSE


async def test_exact_put_and_get_roundtrip() -> None:
    r = _FakeRedis()
    await exact.put(r, "k", _CACHED_RESPONSE, 3600)  # type: ignore[arg-type]
    result = await exact.get(r, "k")  # type: ignore[arg-type]
    assert result == _CACHED_RESPONSE


# ---------------------------------------------------------------------------
# semantic.embed_text
# ---------------------------------------------------------------------------

def test_embed_text_single_user_message() -> None:
    body: JSON = {"messages": [{"role": "user", "content": "What is the capital of France?"}]}
    text = semantic.embed_text(body)
    assert text == "What is the capital of France?"


def test_embed_text_with_prior_context_adds_digest() -> None:
    body: JSON = {
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "What's 2+2?"},
        ]
    }
    text = semantic.embed_text(body)
    assert text.startswith("[ctx:")
    assert "What's 2+2?" in text


def test_embed_text_digest_differs_for_different_history() -> None:
    body_a: JSON = {
        "messages": [
            {"role": "user", "content": "Session A context"},
            {"role": "assistant", "content": "Response A"},
            {"role": "user", "content": "Same question"},
        ]
    }
    body_b: JSON = {
        "messages": [
            {"role": "user", "content": "Session B context"},
            {"role": "assistant", "content": "Response B"},
            {"role": "user", "content": "Same question"},
        ]
    }
    assert semantic.embed_text(body_a) != semantic.embed_text(body_b)


def test_embed_text_no_user_messages_returns_empty() -> None:
    body: JSON = {"messages": [{"role": "system", "content": "You are a helpful assistant."}]}
    assert semantic.embed_text(body) == ""


def test_embed_text_empty_messages_returns_empty() -> None:
    body: JSON = {"messages": []}
    assert semantic.embed_text(body) == ""


def test_embed_text_missing_messages_returns_empty() -> None:
    body: JSON = {"model": "gpt-4"}
    assert semantic.embed_text(body) == ""


# ---------------------------------------------------------------------------
# semantic.lookup
# ---------------------------------------------------------------------------

async def test_lookup_above_threshold_returns_response() -> None:
    row = _FakeRow(similarity=0.95, response_body=_CACHED_RESPONSE)
    conn = cast(asyncpg.Connection, _FakeConn(row))
    result = await semantic.lookup(conn, [0.1] * 3, requested_model="gpt-4o-mini", threshold=0.92)
    assert result == _CACHED_RESPONSE


async def test_lookup_below_threshold_returns_none() -> None:
    row = _FakeRow(similarity=0.85, response_body=_CACHED_RESPONSE)
    conn = cast(asyncpg.Connection, _FakeConn(row))
    result = await semantic.lookup(conn, [0.1] * 3, requested_model="gpt-4o-mini", threshold=0.92)
    assert result is None


async def test_lookup_no_row_returns_none() -> None:
    conn = cast(asyncpg.Connection, _FakeConn(row=None))
    result = await semantic.lookup(conn, [0.1] * 3, requested_model="gpt-4o-mini", threshold=0.92)
    assert result is None


async def test_lookup_exactly_at_threshold_returns_response() -> None:
    row = _FakeRow(similarity=0.92, response_body=_CACHED_RESPONSE)
    conn = cast(asyncpg.Connection, _FakeConn(row))
    result = await semantic.lookup(conn, [0.1] * 3, requested_model="gpt-4o-mini", threshold=0.92)
    assert result == _CACHED_RESPONSE


# ---------------------------------------------------------------------------
# semantic.store
# ---------------------------------------------------------------------------

async def test_store_passes_correct_args() -> None:
    fake_conn = _FakeConn()
    conn = cast(asyncpg.Connection, fake_conn)
    embedding = [0.1, 0.2, 0.3]
    await semantic.store(
        conn,
        request_hash="deadbeef",
        embedding=embedding,
        response=_CACHED_RESPONSE,
        requested_model="gpt-4o-mini",
    )
    assert len(fake_conn.stored) == 1
    args = fake_conn.stored[0]
    assert args[0] == "deadbeef"
    assert args[1] == embedding
    assert args[3] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# synthetic stream replay
# ---------------------------------------------------------------------------

async def _collect_stream(gen: AsyncIterator[bytes]) -> list[bytes]:
    return [chunk async for chunk in gen]


async def test_synthetic_stream_ends_with_done() -> None:
    chunks = await _collect_stream(synthetic_stream(_CACHED_RESPONSE))
    assert chunks[-1] == b"data: [DONE]\n\n"


async def test_synthetic_stream_contains_content() -> None:
    chunks = await _collect_stream(synthetic_stream(_CACHED_RESPONSE))
    combined = b"".join(chunks).decode()
    assert "Hello!" in combined


async def test_synthetic_stream_chunk_sequence() -> None:
    chunks = await _collect_stream(synthetic_stream(_CACHED_RESPONSE))
    # [role chunk, content chunk, finish chunk, usage chunk, DONE]
    assert len(chunks) == 5
    assert chunks[-1] == b"data: [DONE]\n\n"


async def test_synthetic_stream_role_first() -> None:
    chunks = await _collect_stream(synthetic_stream(_CACHED_RESPONSE))
    first = json.loads(chunks[0][len(b"data: "):])
    assert isinstance(first["choices"], list)
    delta = first["choices"][0]["delta"]
    assert delta == {"role": "assistant"}


async def test_synthetic_stream_content_second() -> None:
    chunks = await _collect_stream(synthetic_stream(_CACHED_RESPONSE))
    second = json.loads(chunks[1][len(b"data: "):])
    delta = second["choices"][0]["delta"]
    assert delta == {"content": "Hello!"}


async def test_synthetic_stream_finish_third() -> None:
    chunks = await _collect_stream(synthetic_stream(_CACHED_RESPONSE))
    third = json.loads(chunks[2][len(b"data: "):])
    assert third["choices"][0]["finish_reason"] == "stop"


async def test_synthetic_stream_usage_fourth() -> None:
    chunks = await _collect_stream(synthetic_stream(_CACHED_RESPONSE))
    fourth = json.loads(chunks[3][len(b"data: "):])
    assert fourth["usage"] == {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}


# ---------------------------------------------------------------------------
# assembled_to_response
# ---------------------------------------------------------------------------

def test_assembled_to_response_content() -> None:
    req = GatewayRequest(body={}, model="gpt-4o-mini", stream=True)
    req.assembled_content = "The answer is 42."
    req.usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    resp = assembled_to_response(req, "gpt-4o-mini")

    assert isinstance(resp["choices"], list)
    choices = cast(list[object], resp["choices"])
    first = cast(dict[str, object], choices[0])
    msg = cast(dict[str, object], first["message"])
    assert msg["content"] == "The answer is 42."
    assert resp["model"] == "gpt-4o-mini"
    assert resp["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def test_assembled_to_response_none_content_becomes_empty_string() -> None:
    req = GatewayRequest(body={}, model="gpt-4o-mini", stream=True)
    req.assembled_content = None
    resp = assembled_to_response(req, "gpt-4o-mini")
    choices = cast(list[object], resp["choices"])
    msg = cast(dict[str, object], cast(dict[str, object], choices[0])["message"])
    assert msg["content"] == ""
