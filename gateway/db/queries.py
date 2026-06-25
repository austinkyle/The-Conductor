"""Write queries against the data model. Raw asyncpg, keyword-only arguments for clarity.

resolve_chain (read path) lives in routing/aliases.py — it is a routing concern, not a
raw DB query. This module owns insert_request, update_request_usage, and budget reads.
"""

from __future__ import annotations

from decimal import Decimal

import asyncpg

from db.models import ApiKey

_INSERT_REQUEST = """
INSERT INTO requests
    (requested_model, served_provider_id, served_model, status, error_class, fallback_depth,
     cache_status, api_key_id, prompt_tokens, completion_tokens, total_tokens, cost_cents,
     latency_ms)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
RETURNING id
"""

_UPDATE_REQUEST_USAGE = """
UPDATE requests
SET prompt_tokens     = $2,
    completion_tokens = $3,
    total_tokens      = $4,
    cost_cents        = $5
WHERE id = $1
"""

_GET_API_KEY = """
SELECT id, key_hash, name, soft_limit_cents, hard_limit_cents, created_at
FROM api_keys
WHERE key_hash = $1
"""

_MONTH_SPEND = """
SELECT COALESCE(SUM(cost_cents), 0)
FROM requests
WHERE api_key_id = $1
  AND date_trunc('month', created_at) = date_trunc('month', now())
  AND status = 'success'
"""


async def insert_request(
    conn: asyncpg.Connection,
    *,
    requested_model: str,
    served_provider_id: int | None,
    served_model: str | None,
    status: str,
    error_class: str | None,
    fallback_depth: int,
    cache_status: str | None = None,
    api_key_id: int | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    cost_cents: Decimal | None = None,
    latency_ms: int | None = None,
) -> int:
    """Write a request row and return its id (for streaming close-time update)."""
    row = await conn.fetchrow(
        _INSERT_REQUEST,
        requested_model,
        served_provider_id,
        served_model,
        status,
        error_class,
        fallback_depth,
        cache_status,
        api_key_id,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        cost_cents,
        latency_ms,
    )
    assert row is not None
    return int(row["id"])


async def update_request_usage(
    conn: asyncpg.Connection,
    *,
    request_id: int,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    cost_cents: Decimal,
) -> None:
    """Fill token/cost columns on a streaming request row after the stream closes."""
    await conn.execute(
        _UPDATE_REQUEST_USAGE,
        request_id,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        cost_cents,
    )


async def get_api_key(conn: asyncpg.Connection, key_hash: str) -> ApiKey | None:
    row = await conn.fetchrow(_GET_API_KEY, key_hash)
    if row is None:
        return None
    return ApiKey(
        id=row["id"],
        key_hash=row["key_hash"],
        name=row["name"],
        soft_limit_cents=row["soft_limit_cents"],
        hard_limit_cents=row["hard_limit_cents"],
        created_at=row["created_at"],
    )


async def month_spend_cents(conn: asyncpg.Connection, api_key_id: int) -> Decimal:
    row = await conn.fetchrow(_MONTH_SPEND, api_key_id)
    assert row is not None
    return Decimal(row[0])
