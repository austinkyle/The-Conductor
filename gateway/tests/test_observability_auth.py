"""Bearer-token auth on the observability read API.

Mounts only observability.api.router on a bare FastAPI app (no lifespan, no real
DB/redis) — same isolation spirit as test_proxy.py. queries.cache_stats is
monkeypatched so /cache never touches a database.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Iterator

import httpx
import pytest
from fastapi import FastAPI

from app.main import app as full_app
from core.config import get_settings
from observability import api as obs_api
from observability import queries


class _FakePool:
    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        yield None


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(obs_api.router)
    app.state.pool = _FakePool()
    return app


@pytest.fixture(autouse=True)
def _stub_query(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_cache_stats(conn: object, window: str) -> dict[str, int]:
        return {
            "total": 0,
            "exact_hit": 0,
            "semantic_hit": 0,
            "miss": 0,
            "temperature": 0,
            "no_cache": 0,
            "recent_context": 0,
            "tool_use": 0,
        }

    monkeypatch.setattr(queries, "cache_stats", fake_cache_stats)


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _get(app: FastAPI, headers: dict[str, str] | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/v1/observability/cache", headers=headers)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-y")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


async def test_401_without_token_when_token_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "s3cret")
    resp = await _get(_build_app())
    assert resp.status_code == 401


async def test_401_with_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "s3cret")
    resp = await _get(_build_app(), headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


async def test_200_with_correct_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "s3cret")
    resp = await _get(_build_app(), headers={"Authorization": "Bearer s3cret"})
    assert resp.status_code == 200


async def test_200_with_no_header_when_token_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("DASHBOARD_AUTH_TOKEN", raising=False)
    resp = await _get(_build_app())
    assert resp.status_code == 200


def test_proxy_route_has_no_dashboard_token_dependency() -> None:
    """Guard against the auth dependency ever being accidentally applied to the
    per-key-authenticated /v1/chat/completions proxy route."""
    proxy_route = next(
        r for r in full_app.routes if getattr(r, "path", None) == "/v1/chat/completions"
    )
    dependant = proxy_route.dependant  # type: ignore[attr-defined]
    assert obs_api.require_dashboard_token not in {
        dep.call for dep in dependant.dependencies
    }
