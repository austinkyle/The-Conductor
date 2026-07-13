"""Read-only SQL queries for the observability endpoints.

All queries are over the requests spine. Joins to api_keys and models are
read-only. Window strings are validated by the caller (api.py) before arriving
here. The bucket string for spend() is validated against _BUCKETS and injected
as a SQL literal — safe because the allowlist contains only identifiers.
"""

from __future__ import annotations

import asyncpg

_WINDOWS: dict[str, str] = {
    "24h": "24 hours",
    "7d": "7 days",
    "30d": "30 days",
}

_BUCKETS: frozenset[str] = frozenset({"hour", "day"})


def _interval(window: str) -> str:
    return _WINDOWS.get(window, "7 days")


async def spend(
    conn: asyncpg.Connection,
    window: str,
    bucket: str,
) -> list[asyncpg.Record]:
    assert bucket in _BUCKETS
    interval = _interval(window)
    sql = f"""
        SELECT
            date_trunc('{bucket}', created_at) AS ts,
            COALESCE(SUM(cost_cents), 0)        AS cost_cents
        FROM requests
        WHERE created_at >= NOW() - INTERVAL '{interval}'
        GROUP BY 1
        ORDER BY 1
    """
    return list(await conn.fetch(sql))


async def cache_stats(conn: asyncpg.Connection, window: str) -> asyncpg.Record:
    interval = _interval(window)
    row = await conn.fetchrow(
        f"""
        SELECT
            COUNT(*)                                                                   AS total,
            COUNT(*) FILTER (WHERE cache_status = 'exact_hit')                        AS exact_hit,
            COUNT(*) FILTER (WHERE cache_status = 'semantic_hit')                     AS semantic_hit,
            COUNT(*) FILTER (WHERE cache_status NOT IN ('exact_hit', 'semantic_hit')
                                OR cache_status IS NULL)                               AS miss
        FROM requests
        WHERE created_at >= NOW() - INTERVAL '{interval}'
        """
    )
    assert row is not None
    return row


async def latency_stats(conn: asyncpg.Connection, window: str) -> asyncpg.Record:
    interval = _interval(window)
    row = await conn.fetchrow(
        f"""
        SELECT
            percentile_cont(0.50) WITHIN GROUP (ORDER BY latency_ms) AS p50,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms) AS p99
        FROM requests
        WHERE created_at >= NOW() - INTERVAL '{interval}'
          AND latency_ms IS NOT NULL
        """
    )
    assert row is not None
    return row


async def savings(conn: asyncpg.Connection, window: str) -> asyncpg.Record:
    """Would-be cost for cache-hit rows (token counts × cheapest model price)."""
    interval = _interval(window)
    row = await conn.fetchrow(
        f"""
        WITH cheapest AS (
            SELECT DISTINCT ON (alias)
                alias,
                COALESCE(input_price_per_mtok, 0)  AS input_price,
                COALESCE(output_price_per_mtok, 0) AS output_price
            FROM models
            ORDER BY alias, priority ASC
        )
        SELECT COALESCE(SUM(
            (r.prompt_tokens     * m.input_price +
             r.completion_tokens * m.output_price)
            / 1000000.0 * 100
        ), 0) AS cost_saved_cents
        FROM requests r
        LEFT JOIN cheapest m ON m.alias = r.requested_model
        WHERE r.created_at >= NOW() - INTERVAL '{interval}'
          AND r.cache_status IN ('exact_hit', 'semantic_hit')
          AND r.prompt_tokens     IS NOT NULL
          AND r.completion_tokens IS NOT NULL
        """
    )
    assert row is not None
    return row


async def failovers(conn: asyncpg.Connection, window: str) -> list[asyncpg.Record]:
    interval = _interval(window)
    return list(
        await conn.fetch(
            f"""
            SELECT created_at AS ts, requested_model, served_model, fallback_depth
            FROM requests
            WHERE created_at >= NOW() - INTERVAL '{interval}'
              AND fallback_depth > 0
            ORDER BY created_at DESC
            LIMIT 200
            """
        )
    )


async def key_usage(conn: asyncpg.Connection, window: str) -> list[asyncpg.Record]:
    interval = _interval(window)
    return list(
        await conn.fetch(
            f"""
            SELECT
                ak.name,
                COUNT(*)                            AS requests,
                COALESCE(SUM(r.total_tokens),  0)   AS total_tokens,
                COALESCE(SUM(r.cost_cents),    0)   AS cost_cents
            FROM requests r
            JOIN api_keys ak ON ak.id = r.api_key_id
            WHERE r.created_at >= NOW() - INTERVAL '{interval}'
            GROUP BY ak.id, ak.name
            ORDER BY SUM(r.cost_cents) DESC NULLS LAST
            """
        )
    )
