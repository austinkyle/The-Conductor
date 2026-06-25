"""Tests for error classification, fallback chain walk, and terminal-error non-cascade.

Three layers:
  1. Pure classification (is_retryable_status, label_for_status, label_for_exception).
  2. Failover: chain [anthropic, openai]; A returns 503; B returns 200; assert depth==1.
  3. Terminal: A returns 400; assert B never called, row status=="error", depth==0.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import cast

import asyncpg
import httpx
import pytest

from core import pipeline
from core.config import get_settings
from db.models import Model, Provider
from routing import errors
from routing.errors import ProviderError
from translation.base import JSON

_NOW = datetime.now(timezone.utc)


def _provider(pid: int, name: str) -> Provider:
    if name == "openai":
        return Provider(pid, "openai", "https://api.openai.com/v1", "OPENAI_API_KEY", _NOW)
    return Provider(pid, "anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", _NOW)


def _model(mid: int, pid: int, provider_model: str) -> Model:
    if "gpt" in provider_model:
        return Model(mid, provider_model, pid, provider_model, Decimal("0.15"), Decimal("0.60"), _NOW)
    return Model(mid, provider_model, pid, provider_model, Decimal("3"), Decimal("15"), _NOW)


# --- 1. Pure classification ---

@pytest.mark.parametrize("status, label, retryable", [
    (429, "rate_limit", True),
    (500, "server_error", True),
    (503, "server_error", True),
])
def test_retryable_status(status: int, label: str, retryable: bool) -> None:
    assert errors.is_retryable_status(status) is retryable
    assert errors.label_for_status(status) == label


@pytest.mark.parametrize("status, label, retryable", [
    (400, "client_error", False),
    (401, "client_error", False),
    (404, "client_error", False),
])
def test_terminal_status(status: int, label: str, retryable: bool) -> None:
    assert errors.is_retryable_status(status) is retryable
    assert errors.label_for_status(status) == label


def test_timeout_exception_label() -> None:
    exc = httpx.ReadTimeout("timed out")
    assert errors.label_for_exception(exc) == "timeout"


def test_connection_exception_label() -> None:
    exc = httpx.ConnectError("connection refused")
    assert errors.label_for_exception(exc) == "connection"


def test_unknown_exception_reraises() -> None:
    exc = ValueError("something unexpected")
    with pytest.raises(ValueError, match="something unexpected"):
        errors.from_exception(exc, depth=0, provider_id=1, served_model="gpt-4o")


# --- shared fixtures ---

_OPENAI_RESPONSE: JSON = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-4o",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "Hi"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
}


def _two_provider_chain() -> list[tuple[Model, Provider]]:
    """Anthropic first (priority 0), OpenAI second (priority 1)."""
    anthropic = _provider(2, "anthropic")
    openai = _provider(1, "openai")
    return [
        (_model(2, 2, "claude-3-5-sonnet-latest"), anthropic),
        (_model(1, 1, "gpt-4o"), openai),
    ]


@pytest.fixture(autouse=True)
def _env_and_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost")
    get_settings.cache_clear()
    monkeypatch.setattr(pipeline, "_backoff", lambda d: 0.0)
    monkeypatch.setattr(pipeline, "should_bypass", lambda body, temperature_bypass=0.3: "skip_cache")


# --- 2. Failover: A returns 503, B returns 200 ---

def _failover_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/messages"):
        return httpx.Response(503, json={"error": "service unavailable"})
    if request.url.path.endswith("/chat/completions"):
        return httpx.Response(200, json=_OPENAI_RESPONSE)
    return httpx.Response(404, json={"error": "unexpected path"})


async def test_failover_to_second_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    chain = _two_provider_chain()
    insert_calls: list[dict[str, object]] = []

    async def fake_resolve_chain(conn: object, model: str) -> list[tuple[Model, Provider]]:
        return chain

    async def fake_insert_request(conn: object, **kwargs: object) -> None:
        insert_calls.append(kwargs)

    monkeypatch.setattr(pipeline, "resolve_chain", fake_resolve_chain)
    monkeypatch.setattr(pipeline, "insert_request", fake_insert_request)

    transport = httpx.MockTransport(_failover_handler)
    async with httpx.AsyncClient(transport=transport) as http:
        conn = cast(asyncpg.Connection, None)
        result = await pipeline.proxy_chat_completion(
            conn, http, None, {"model": "smart", "messages": [{"role": "user", "content": "Hi"}]}  # type: ignore[arg-type]
        )

    choices = result.get("choices")
    assert isinstance(choices, list)
    msg = choices[0].get("message")
    assert isinstance(msg, dict)
    assert msg["content"] == "Hi"

    assert len(insert_calls) == 1
    row = insert_calls[0]
    assert row["fallback_depth"] == 1
    assert row["status"] == "success"
    openai_provider_id = _two_provider_chain()[1][1].id
    assert row["served_provider_id"] == openai_provider_id


# --- 3. Terminal error does not cascade ---

async def test_terminal_error_does_not_cascade(monkeypatch: pytest.MonkeyPatch) -> None:
    contacted: list[str] = []

    def _terminal_handler(request: httpx.Request) -> httpx.Response:
        contacted.append(request.url.host)
        if request.url.path.endswith("/messages"):
            return httpx.Response(400, json={"error": "bad request"})
        return httpx.Response(200, json=_OPENAI_RESPONSE)

    chain = _two_provider_chain()
    insert_calls: list[dict[str, object]] = []

    async def fake_resolve_chain(conn: object, model: str) -> list[tuple[Model, Provider]]:
        return chain

    async def fake_insert_request(conn: object, **kwargs: object) -> None:
        insert_calls.append(kwargs)

    monkeypatch.setattr(pipeline, "resolve_chain", fake_resolve_chain)
    monkeypatch.setattr(pipeline, "insert_request", fake_insert_request)

    from fastapi import HTTPException

    transport = httpx.MockTransport(_terminal_handler)
    async with httpx.AsyncClient(transport=transport) as http:
        conn = cast(asyncpg.Connection, None)
        with pytest.raises(HTTPException) as exc_info:
            await pipeline.proxy_chat_completion(
                conn, http, None, {"model": "smart", "messages": [{"role": "user", "content": "Hi"}]}  # type: ignore[arg-type]
            )

    assert exc_info.value.status_code == 400
    # Only anthropic was contacted — terminal error must not cascade to OpenAI.
    assert len(contacted) == 1
    assert "anthropic" in contacted[0]
    # The request row records the failure at depth 0.
    assert len(insert_calls) == 1
    row = insert_calls[0]
    assert row["status"] == "error"
    assert row["error_class"] == "client_error"
    assert row["fallback_depth"] == 0
