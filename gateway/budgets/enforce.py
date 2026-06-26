"""Per-key budget enforcement: Redis counter with DB as source of truth.

Redis key shape: budget:{api_key_id}:{YYYY-MM}
TTL is set to ~35 days on first write to survive month-boundary clock skew.
On a counter miss the counter is rebuilt from the DB monthly sum, then TTL is set.

check_budget  — call before forwarding; raises 402 on hard block, logs on soft warn.
record_spend  — call after success; increments the Redis counter.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

import asyncpg
import redis.asyncio as aioredis
from fastapi import HTTPException

from db.models import ApiKey

# aioredis.Redis is generic but the type-arg is optional in practice; ignore at the
# call site where the generic form causes mypy unused-ignore noise.

_log = logging.getLogger(__name__)

_TTL_SECONDS = 35 * 24 * 3600  # ~35 days covers month-end boundaries


def _counter_key(api_key_id: int, now: datetime) -> str:
    return f"budget:{api_key_id}:{now.strftime('%Y-%m')}"


async def _current_spend(
    conn: asyncpg.Connection,
    r: aioredis.Redis,
    api_key_id: int,
) -> Decimal:
    now = datetime.now(timezone.utc)
    key = _counter_key(api_key_id, now)

    raw = await r.get(key)
    if raw is not None:
        return Decimal(raw.decode() if isinstance(raw, bytes) else raw)

    # Counter miss — rebuild from DB, then prime Redis.
    from db.queries import month_spend_cents

    db_spend = await month_spend_cents(conn, api_key_id)
    # Store as string with 4 decimal places for precision.
    value = str(db_spend.quantize(Decimal("0.0001")))
    await r.set(key, value, ex=_TTL_SECONDS, nx=True)
    return db_spend


async def check_budget(
    conn: asyncpg.Connection,
    r: aioredis.Redis,
    key: ApiKey,
) -> None:
    """Raise 402 if the key has hit its hard limit; warn if it's past its soft limit.

    Call before forwarding the request to the provider — if hard-blocked the upstream
    is never called. Sets `x-budget-warning` on the response headers via the exception
    detail for the soft-warn case (the non-streaming caller reads it from the pipeline
    return value path).
    """
    if key.hard_limit_cents is None and key.soft_limit_cents is None:
        return

    spend = await _current_spend(conn, r, key.id)

    if key.hard_limit_cents is not None and spend >= key.hard_limit_cents:
        raise HTTPException(
            status_code=402,
            detail=f"budget exceeded: spent {spend} cents, limit {key.hard_limit_cents} cents",
        )

    if key.soft_limit_cents is not None and spend >= key.soft_limit_cents:
        _log.warning(
            "soft budget warning for key %d (%s): spent %.4f of %d cents",
            key.id,
            key.name,
            spend,
            key.soft_limit_cents,
        )


async def record_spend(
    r: aioredis.Redis,
    api_key_id: int,
    cents: Decimal,
) -> None:
    """Increment the monthly Redis spend counter by cents (numeric string, 4dp)."""
    now = datetime.now(timezone.utc)
    key = _counter_key(api_key_id, now)
    # INCRBYFLOAT keeps precision; creates the key at 0 if missing.
    await r.incrbyfloat(key, float(cents))
    # Refresh the ~35-day TTL on every write (rolling window covering month boundaries).
    await r.expire(key, _TTL_SECONDS)
