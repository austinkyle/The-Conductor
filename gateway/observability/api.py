"""Read-only observability endpoints mounted at /v1/observability/*.

All endpoints are GET, read from the requests spine, and return shaped JSON.

Query parameters:
  window  — time window: 24h | 7d | 30d  (default 7d)
  bucket  — spend granularity: hour | day  (default day, spend endpoint only)
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from core.config import get_settings
from observability import queries


def require_dashboard_token(authorization: str | None = Header(default=None)) -> None:
    """Static bearer-token gate. Unset token (dev default) allows all requests
    through — a warning is logged once at startup in that case (see app/main.py)."""
    token = get_settings().dashboard_auth_token
    if token is None:
        return
    if authorization != f"Bearer {token}":
        raise HTTPException(401, "Unauthorized")


router = APIRouter(
    prefix="/v1/observability", dependencies=[Depends(require_dashboard_token)]
)

_VALID_WINDOWS = frozenset({"24h", "7d", "30d"})
_VALID_BUCKETS = frozenset({"hour", "day"})


def _check_window(w: str) -> None:
    if w not in _VALID_WINDOWS:
        raise HTTPException(422, f"window must be one of {sorted(_VALID_WINDOWS)}")


def _check_bucket(b: str) -> None:
    if b not in _VALID_BUCKETS:
        raise HTTPException(422, f"bucket must be one of {sorted(_VALID_BUCKETS)}")


# --- Response models ---


class SpendBucket(BaseModel):
    ts: datetime
    cost_cents: Decimal


class CacheStats(BaseModel):
    total: int
    exact_hit: int
    semantic_hit: int
    miss: int
    hit_rate: float


class LatencyStats(BaseModel):
    p50: float | None
    p95: float | None
    p99: float | None


class SavingsStats(BaseModel):
    cost_saved_cents: Decimal


class FailoverEvent(BaseModel):
    ts: datetime
    requested_model: str | None
    served_model: str | None
    fallback_depth: int


class KeyUsage(BaseModel):
    name: str
    requests: int
    total_tokens: int
    cost_cents: Decimal


# --- Endpoints ---


@router.get("/spend", response_model=list[SpendBucket])
async def obs_spend(
    request: Request, window: str = "7d", bucket: str = "day"
) -> list[SpendBucket]:
    _check_window(window)
    _check_bucket(bucket)
    async with request.app.state.pool.acquire() as conn:
        rows = await queries.spend(conn, window, bucket)
    return [
        SpendBucket(ts=row["ts"], cost_cents=Decimal(str(row["cost_cents"])))
        for row in rows
    ]


@router.get("/cache", response_model=CacheStats)
async def obs_cache(request: Request, window: str = "7d") -> CacheStats:
    _check_window(window)
    async with request.app.state.pool.acquire() as conn:
        row = await queries.cache_stats(conn, window)
    total = int(row["total"])
    exact_hit = int(row["exact_hit"])
    semantic_hit = int(row["semantic_hit"])
    miss = int(row["miss"])
    hit_rate = (exact_hit + semantic_hit) / total if total > 0 else 0.0
    return CacheStats(
        total=total,
        exact_hit=exact_hit,
        semantic_hit=semantic_hit,
        miss=miss,
        hit_rate=hit_rate,
    )


@router.get("/latency", response_model=LatencyStats)
async def obs_latency(request: Request, window: str = "7d") -> LatencyStats:
    _check_window(window)
    async with request.app.state.pool.acquire() as conn:
        row = await queries.latency_stats(conn, window)
    return LatencyStats(
        p50=float(row["p50"]) if row["p50"] is not None else None,
        p95=float(row["p95"]) if row["p95"] is not None else None,
        p99=float(row["p99"]) if row["p99"] is not None else None,
    )


@router.get("/savings", response_model=SavingsStats)
async def obs_savings(request: Request, window: str = "7d") -> SavingsStats:
    _check_window(window)
    async with request.app.state.pool.acquire() as conn:
        row = await queries.savings(conn, window)
    return SavingsStats(cost_saved_cents=Decimal(str(row["cost_saved_cents"])))


@router.get("/failovers", response_model=list[FailoverEvent])
async def obs_failovers(request: Request, window: str = "7d") -> list[FailoverEvent]:
    _check_window(window)
    async with request.app.state.pool.acquire() as conn:
        rows = await queries.failovers(conn, window)
    return [
        FailoverEvent(
            ts=row["ts"],
            requested_model=row["requested_model"],
            served_model=row["served_model"],
            fallback_depth=int(row["fallback_depth"]),
        )
        for row in rows
    ]


@router.get("/keys", response_model=list[KeyUsage])
async def obs_keys(request: Request, window: str = "7d") -> list[KeyUsage]:
    _check_window(window)
    async with request.app.state.pool.acquire() as conn:
        rows = await queries.key_usage(conn, window)
    return [
        KeyUsage(
            name=str(row["name"]),
            requests=int(row["requests"]),
            total_tokens=int(row["total_tokens"]),
            cost_cents=Decimal(str(row["cost_cents"])),
        )
        for row in rows
    ]
