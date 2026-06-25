"""Resolve an incoming Authorization header to an ApiKey row (or None).

Missing/unmatched header → None (anonymous request, no enforcement).
Only SHA-256 hashed keys are stored; the raw value is never written anywhere.
"""

from __future__ import annotations

import hashlib

import asyncpg

from db.models import ApiKey
from db.queries import get_api_key


async def resolve_api_key(
    conn: asyncpg.Connection,
    authorization: str | None,
) -> ApiKey | None:
    if not authorization:
        return None
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    return await get_api_key(conn, key_hash)
