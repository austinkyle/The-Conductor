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


def _urls() -> tuple[str, str, str]:
    base = os.environ.get("DATABASE_URL")
    if not base:
        pytest.skip("DATABASE_URL not set")
    parts = urlsplit(base)
    testdb = f"migtest_{uuid.uuid4().hex[:12]}"
    admin_url = urlunsplit(parts._replace(path="/postgres"))
    test_url = urlunsplit(parts._replace(path=f"/{testdb}"))
    return admin_url, test_url, testdb


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
