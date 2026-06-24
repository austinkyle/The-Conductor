"""Read queries against the data model. Raw asyncpg, rows mapped into the frozen
dataclasses in models.py for type-checked reads."""

from __future__ import annotations

import asyncpg

from db.models import Model, Provider

# Match on the logical alias first, then the concrete provider model name. In Phase 1
# the two are equal; Phase 3 makes alias a distinct logical name with a fallback chain.
_RESOLVE_MODEL = """
SELECT
    m.id, m.alias, m.provider_id, m.provider_model,
    m.input_price_per_mtok, m.output_price_per_mtok, m.created_at,
    p.id AS p_id, p.name AS p_name, p.base_url, p.auth_ref, p.created_at AS p_created_at
FROM models m
JOIN providers p ON p.id = m.provider_id
WHERE m.alias = $1 OR m.provider_model = $1
ORDER BY (m.alias = $1) DESC
LIMIT 1
"""


async def resolve_model(
    conn: asyncpg.Connection, model: str
) -> tuple[Model, Provider] | None:
    """Resolve a requested model string to its (model, provider). None if unknown."""
    row = await conn.fetchrow(_RESOLVE_MODEL, model)
    if row is None:
        return None
    resolved = Model(
        id=row["id"],
        alias=row["alias"],
        provider_id=row["provider_id"],
        provider_model=row["provider_model"],
        input_price_per_mtok=row["input_price_per_mtok"],
        output_price_per_mtok=row["output_price_per_mtok"],
        created_at=row["created_at"],
    )
    provider = Provider(
        id=row["p_id"],
        name=row["p_name"],
        base_url=row["base_url"],
        auth_ref=row["auth_ref"],
        created_at=row["p_created_at"],
    )
    return resolved, provider
