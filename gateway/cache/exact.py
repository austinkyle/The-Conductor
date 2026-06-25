"""Exact-match Redis cache layer.

Key = SHA-256 of the normalized request body (volatile keys stripped). Value = JSON
response body, stored as a UTF-8 string with a configurable TTL.
"""

from __future__ import annotations

import hashlib
import json
from typing import cast

import redis.asyncio as aioredis

from translation.base import JSON

# Keys whose values don't affect the provider's reply.
_VOLATILE_KEYS = frozenset({"stream", "stream_options", "cache"})


def normalize(body: JSON) -> str:
    """Drop volatile keys and produce a canonical JSON string."""
    clean = {k: v for k, v in body.items() if k not in _VOLATILE_KEYS}
    return json.dumps(clean, sort_keys=True, separators=(",", ":"))


def request_hash(body: JSON) -> str:
    return hashlib.sha256(normalize(body).encode()).hexdigest()


async def get(client: aioredis.Redis[str], key: str) -> JSON | None:  # type: ignore[type-arg]
    raw = await client.get(key)  # bytes | str | None
    if raw is None:
        return None
    return cast(JSON, json.loads(raw))


async def put(
    client: aioredis.Redis[str], key: str, response: JSON, ttl: int  # type: ignore[type-arg]
) -> None:
    await client.setex(key, ttl, json.dumps(response))
