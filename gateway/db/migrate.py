"""Sequential migration runner.

Applies migrations/NNN_*.sql in filename order, tracking applied files in a
schema_migrations table. Idempotent: already-applied files are skipped.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg

from core.config import get_settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_CREATE_TRACKING = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
"""


async def apply_migrations(conn: asyncpg.Connection) -> list[str]:
    """Apply any pending migrations. Returns the filenames newly applied."""
    await conn.execute(_CREATE_TRACKING)
    applied = {
        row["filename"]
        for row in await conn.fetch("SELECT filename FROM schema_migrations")
    }

    newly: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("[0-9]*.sql")):
        if path.name in applied:
            continue
        async with conn.transaction():
            await conn.execute(path.read_text())
            await conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES ($1)", path.name
            )
        newly.append(path.name)
    return newly


async def main() -> None:
    conn = await asyncpg.connect(get_settings().database_url)
    try:
        newly = await apply_migrations(conn)
        print(f"applied: {newly}" if newly else "no pending migrations")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
