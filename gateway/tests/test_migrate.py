"""Integration test for the migration runner.

Needs a reachable pgvector-enabled Postgres (DATABASE_URL). Creates a throwaway
database so the run is isolated, then drops it. Skips cleanly if no DB is present.
"""

import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from db.migrate import apply_migrations

_TABLES = ["api_keys", "providers", "models", "requests", "semantic_cache"]

# Current seeds, as of the latest migration (008_update_anthropic_models). This is the
# regression test for the retired-model bug class: if a migration reintroduces a stale
# provider_model (e.g. claude-3-5-sonnet-latest), this fails instead of shipping quietly.
_EXPECTED_PROVIDER_MODELS = {
    "gpt-4o-mini": {"gpt-4o-mini"},
    "claude-sonnet-5": {"claude-sonnet-5"},
    "smart": {"claude-sonnet-5", "gpt-4o"},
    "fast": {"gpt-4o-mini", "claude-haiku-4-5-20251001"},
}


def _urls() -> tuple[str, str, str]:
    base = os.environ.get("DATABASE_URL")
    if not base:
        pytest.skip("DATABASE_URL not set")
    parts = urlsplit(base)
    testdb = f"migtest_{uuid.uuid4().hex[:12]}"
    admin_url = urlunsplit(parts._replace(path="/postgres"))
    test_url = urlunsplit(parts._replace(path=f"/{testdb}"))
    return admin_url, test_url, testdb


async def _provision_migrated_db() -> tuple[str, str, str]:
    """Create a throwaway DB and apply all migrations. Returns admin_url, test_url, testdb."""
    admin_url, test_url, testdb = _urls()
    try:
        admin = await asyncpg.connect(admin_url)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"postgres unavailable: {exc}")

    try:
        await admin.execute(f'CREATE DATABASE "{testdb}"')
    finally:
        await admin.close()

    conn = await asyncpg.connect(test_url)
    try:
        await apply_migrations(conn)
    finally:
        await conn.close()

    return admin_url, test_url, testdb


async def _drop_db(admin_url: str, testdb: str) -> None:
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{testdb}"')
    finally:
        await admin.close()


async def test_migrations_apply_idempotently() -> None:
    admin_url, test_url, testdb = _urls()
    try:
        admin = await asyncpg.connect(admin_url)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"postgres unavailable: {exc}")

    try:
        await admin.execute(f'CREATE DATABASE "{testdb}"')
    finally:
        await admin.close()

    conn = await asyncpg.connect(test_url)
    try:
        first = await apply_migrations(conn)
        assert "001_init.sql" in first

        table_count = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = ANY($1::text[])",
            _TABLES,
        )
        assert table_count == len(_TABLES)

        # Second run is a no-op — that is the idempotency guarantee.
        second = await apply_migrations(conn)
        assert second == []
    finally:
        await conn.close()
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{testdb}"')
        finally:
            await admin.close()


async def test_seeded_model_aliases_resolve_to_current_provider_models() -> None:
    """Applies 001->current on a fresh DB, then checks every seeded alias against the
    live seeds rather than a snapshot — catches a migration leaving a stale/retired
    provider model (e.g. 008's claude-3-5-sonnet-latest -> claude-sonnet-5 fix) in place."""
    admin_url, test_url, testdb = await _provision_migrated_db()
    conn = await asyncpg.connect(test_url)
    try:
        rows = await conn.fetch("SELECT alias, provider_model FROM models")
        by_alias: dict[str, set[str]] = {}
        for row in rows:
            by_alias.setdefault(row["alias"], set()).add(row["provider_model"])

        assert by_alias == _EXPECTED_PROVIDER_MODELS

        retired = {"claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"}
        seen = {pm for pms in by_alias.values() for pm in pms}
        assert not (seen & retired), f"retired provider models still seeded: {seen & retired}"
    finally:
        await conn.close()
        await _drop_db(admin_url, testdb)
