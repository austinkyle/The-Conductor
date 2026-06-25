"""Resolve a model string to a priority-ordered list of (Model, Provider) candidates."""

from __future__ import annotations

import asyncpg

from db.models import Model, Provider

# All rows matching an alias, ordered by priority — yields the full fallback chain.
_BY_ALIAS = """
SELECT
    m.id, m.alias, m.provider_id, m.provider_model,
    m.input_price_per_mtok, m.output_price_per_mtok, m.priority, m.created_at,
    p.id AS p_id, p.name AS p_name, p.base_url, p.auth_ref, p.api_format, p.created_at AS p_created_at
FROM models m
JOIN providers p ON p.id = m.provider_id
WHERE m.alias = $1
ORDER BY m.priority ASC, m.id ASC
"""

# Concrete passthrough — client sent a provider_model string directly (no alias).
_BY_MODEL = """
SELECT
    m.id, m.alias, m.provider_id, m.provider_model,
    m.input_price_per_mtok, m.output_price_per_mtok, m.priority, m.created_at,
    p.id AS p_id, p.name AS p_name, p.base_url, p.auth_ref, p.api_format, p.created_at AS p_created_at
FROM models m
JOIN providers p ON p.id = m.provider_id
WHERE m.provider_model = $1
LIMIT 1
"""


def _row_to_pair(row: asyncpg.Record) -> tuple[Model, Provider]:
    model = Model(
        id=row["id"],
        alias=row["alias"],
        provider_id=row["provider_id"],
        provider_model=row["provider_model"],
        input_price_per_mtok=row["input_price_per_mtok"],
        output_price_per_mtok=row["output_price_per_mtok"],
        created_at=row["created_at"],
        priority=row["priority"],
    )
    provider = Provider(
        id=row["p_id"],
        name=row["p_name"],
        base_url=row["base_url"],
        auth_ref=row["auth_ref"],
        api_format=row["api_format"],
        created_at=row["p_created_at"],
    )
    return model, provider


async def resolve_chain(
    conn: asyncpg.Connection, model: str
) -> list[tuple[Model, Provider]]:
    """Resolve model string to an ordered candidate chain. Empty list → pipeline returns 404."""
    rows = await conn.fetch(_BY_ALIAS, model)
    if rows:
        return [_row_to_pair(r) for r in rows]
    row = await conn.fetchrow(_BY_MODEL, model)
    if row is None:
        return []
    return [_row_to_pair(row)]
