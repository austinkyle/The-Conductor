"""DB seed/cleanup helpers shared by bench scripts.

All operations are idempotent: seeding twice is safe, cleanup of non-existent
rows is silent.
"""
from __future__ import annotations

import asyncpg

_UPSERT_PROVIDER = """
INSERT INTO providers (name, base_url, auth_ref)
VALUES ($1, $2, $3)
ON CONFLICT (name) DO UPDATE SET base_url = EXCLUDED.base_url
RETURNING id
"""

# models has no unique constraint on (alias, provider_id) — guard manually.
_MODEL_EXISTS = """
SELECT 1 FROM models WHERE alias = $1 AND provider_id = $2
"""
_INSERT_MODEL = """
INSERT INTO models (alias, provider_id, provider_model, priority)
VALUES ($1, $2, $3, $4)
"""

_DELETE_MODELS = """DELETE FROM models WHERE alias = $1"""
_DELETE_REQUESTS_BY_PROVIDER = """
DELETE FROM requests
WHERE served_provider_id = (SELECT id FROM providers WHERE name = $1)
"""
_DELETE_PROVIDER = """DELETE FROM providers WHERE name = $1"""


async def seed_bench_provider(
    conn: asyncpg.Connection,
    *,
    provider_name: str,
    alias: str,
    base_url: str,
    priority: int = 0,
    auth_ref: str = "BENCH_MOCK_KEY",
) -> None:
    """Insert a test provider + model row. Idempotent (upsert on conflict)."""
    row = await conn.fetchrow(_UPSERT_PROVIDER, provider_name, base_url, auth_ref)
    assert row is not None
    provider_id: int = row["id"]
    exists = await conn.fetchval(_MODEL_EXISTS, alias, provider_id)
    if not exists:
        await conn.execute(_INSERT_MODEL, alias, provider_id, "mock-model", priority)


async def cleanup_bench_alias(
    conn: asyncpg.Connection,
    *,
    alias: str,
    provider_names: list[str],
) -> None:
    """Remove test model/request rows and named providers. Idempotent."""
    await conn.execute(_DELETE_MODELS, alias)
    for name in provider_names:
        await conn.execute(_DELETE_REQUESTS_BY_PROVIDER, name)
        await conn.execute(_DELETE_PROVIDER, name)
