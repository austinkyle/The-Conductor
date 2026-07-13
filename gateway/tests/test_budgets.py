"""Tests for Phase 5A: cost accounting, budget enforcement, and anonymous passthrough.

No live DB or Redis — all external calls are mocked. Tests verify:
  1. cost_cents math is correct for a known token count.
  2. A None-price model side contributes 0.
  3. A key over hard_limit_cents is blocked pre-forward (upstream not called).
  4. A key over soft_limit_cents is served (not blocked) and a warning is logged.
  5. An anonymous request (no/unknown key) is served, api_key_id NULL, no spend recorded.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import httpx
import pytest

from budgets.accounting import cost_cents
from budgets.enforce import check_budget
from core import pipeline
from core.config import get_settings
from db.models import ApiKey, Model, Provider
from translation.base import JSON

_NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# cost_cents unit tests
# ---------------------------------------------------------------------------


def _model(
    input_price: str | None,
    output_price: str | None,
) -> Model:
    return Model(
        id=1,
        alias="test",
        provider_id=1,
        provider_model="test",
        input_price_per_mtok=Decimal(input_price) if input_price else None,
        output_price_per_mtok=Decimal(output_price) if output_price else None,
        created_at=_NOW,
    )


def test_cost_cents_known_values() -> None:
    # gpt-4o-mini pricing: $0.15 / 1M input, $0.60 / 1M output
    m = _model("0.15", "0.60")
    # 10 prompt tokens, 3 completion tokens:
    # input:  10 * 0.15 / 1_000_000 USD = 0.0000015 USD → 0.00015 cents
    # output:  3 * 0.60 / 1_000_000 USD = 0.0000018 USD → 0.00018 cents
    # total: 0.00033 cents → quantize(0.0001) = 0.0003 cents
    result = cost_cents(m, 10, 3)
    assert result == Decimal("0.0003")
    # 1_000_000 prompt tokens, 1_000_000 completion tokens:
    # input: 1_000_000 * 0.15 / 1_000_000 * 100 = 15 cents
    # output: 1_000_000 * 0.60 / 1_000_000 * 100 = 60 cents
    result_large = cost_cents(m, 1_000_000, 1_000_000)
    assert result_large == Decimal("75.0000")


def test_cost_cents_none_input_price() -> None:
    m = _model(None, "1.00")
    # Only output contributes: 1000 * 1.00 / 1_000_000 * 100 = 0.1000 cents
    result = cost_cents(m, 1000, 1000)
    assert result == Decimal("0.1000")


def test_cost_cents_none_output_price() -> None:
    m = _model("1.00", None)
    # Only input contributes: 1000 * 1.00 / 1_000_000 * 100 = 0.1000 cents
    result = cost_cents(m, 1000, 1000)
    assert result == Decimal("0.1000")


def test_cost_cents_both_none() -> None:
    m = _model(None, None)
    result = cost_cents(m, 9999, 9999)
    assert result == Decimal("0.0000")


# ---------------------------------------------------------------------------
# Budget enforcement unit tests
# ---------------------------------------------------------------------------


def _api_key(
    *,
    soft_limit: int | None = None,
    hard_limit: int | None = None,
) -> ApiKey:
    return ApiKey(
        id=42,
        key_hash="abc123",
        name="test-key",
        soft_limit_cents=soft_limit,
        hard_limit_cents=hard_limit,
        created_at=_NOW,
    )


@pytest.mark.asyncio
async def test_hard_limit_raises_402() -> None:
    key = _api_key(hard_limit=100)
    conn = cast(asyncpg.Connection, None)

    r = MagicMock()
    r.get = AsyncMock(return_value=b"150.0000")  # spend > hard_limit

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await check_budget(conn, r, key)

    assert exc_info.value.status_code == 402


@pytest.mark.asyncio
async def test_soft_limit_allows_request_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    key = _api_key(soft_limit=10, hard_limit=100)
    conn = cast(asyncpg.Connection, None)

    r = MagicMock()
    r.get = AsyncMock(return_value=b"50.0000")  # spend > soft_limit, < hard_limit

    with caplog.at_level(logging.WARNING, logger="budgets.enforce"):
        await check_budget(conn, r, key)  # should not raise

    assert any("soft budget warning" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_no_limits_skips_redis() -> None:
    key = _api_key()  # no soft or hard limit
    conn = cast(asyncpg.Connection, None)
    r = MagicMock()
    r.get = AsyncMock()

    await check_budget(conn, r, key)

    r.get.assert_not_called()


# ---------------------------------------------------------------------------
# Integration smoke: anonymous request flows through pipeline (api_key_id NULL)
# ---------------------------------------------------------------------------


_OPENAI_UPSTREAM: JSON = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hi"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_anonymous_request_served_no_enforcement() -> None:
    """Anonymous call (key=None) still served; no budget functions called."""
    inserted_kwargs: dict[str, object] = {}

    async def fake_insert_request(conn: object, **kwargs: object) -> int:
        inserted_kwargs.update(kwargs)
        return 1

    def fake_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_OPENAI_UPSTREAM)

    async def fake_resolve_chain(conn: object, model: str) -> list[tuple[Model, Provider]]:
        provider = Provider(1, "openai", "https://api.openai.com/v1", "OPENAI_API_KEY", "openai", _NOW)
        m = Model(1, model, 1, model, Decimal("0.15"), Decimal("0.60"), _NOW)
        return [(m, provider)]

    transport = httpx.MockTransport(fake_handler)
    r = cast(object, None)

    with (
        patch.object(pipeline, "resolve_chain", fake_resolve_chain),
        patch.object(pipeline, "insert_request", fake_insert_request),
        patch.object(pipeline, "should_bypass", lambda body, temperature_bypass=0.3: "skip_cache"),
    ):
        async with httpx.AsyncClient(transport=transport) as http:
            conn = cast(asyncpg.Connection, None)
            result = await pipeline.proxy_chat_completion(
                conn,
                http,
                r,  # type: ignore[arg-type]
                {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
                key=None,
            )

    assert result["object"] == "chat.completion"
    assert inserted_kwargs.get("api_key_id") is None


@pytest.mark.asyncio
async def test_hard_blocked_key_does_not_call_upstream() -> None:
    """A key over its hard_limit_cents raises 402 before the upstream is called."""
    key = _api_key(hard_limit=100)

    upstream_called = False

    def fake_handler(request: httpx.Request) -> httpx.Response:
        nonlocal upstream_called
        upstream_called = True
        return httpx.Response(200, json=_OPENAI_UPSTREAM)

    r = MagicMock()
    r.get = AsyncMock(return_value=b"200.0000")  # way over hard limit

    from fastapi import HTTPException

    transport = httpx.MockTransport(fake_handler)
    with patch.object(pipeline, "should_bypass", lambda body, temperature_bypass=0.3: "skip_cache"):
        async with httpx.AsyncClient(transport=transport) as http:
            conn = cast(asyncpg.Connection, None)
            with pytest.raises(HTTPException) as exc_info:
                await pipeline.proxy_chat_completion(
                    conn,
                    http,
                    r,
                    {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
                    key=key,
                )

    assert exc_info.value.status_code == 402
    assert not upstream_called
