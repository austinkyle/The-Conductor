"""Semantic (pgvector) cache layer.

Embed strategy: "last_plus_digest"
  - Take the last user message as the primary semantic signal.
  - Prefix it with the first 8 hex chars of SHA-256 over all *prior* turns (assistant +
    earlier user messages). This scopes the embedding to the session context without
    embedding the full history — small, stable, and avoids embedding-length limits.
  - If there are no user messages, return "" so the caller skips embedding.

The similarity threshold (default 0.92) is a placeholder; bench/ (Phase 5) must validate
it empirically before the value is treated as authoritative.
"""

from __future__ import annotations

import hashlib
import json
from typing import cast

import asyncpg
import httpx

from core.config import get_settings
from translation.base import JSON

EMBED_STRATEGY = "last_plus_digest"

_LOOKUP = """
SELECT response_body, 1 - (embedding <=> $1) AS similarity
FROM semantic_cache
WHERE model = $2
ORDER BY embedding <=> $1
LIMIT 1
"""

_STORE = """
INSERT INTO semantic_cache (request_hash, embedding, response_body, model)
VALUES ($1, $2, $3, $4)
ON CONFLICT (request_hash) DO NOTHING
"""


def embed_text(body: JSON) -> str:
    """Build the text string to embed for this request."""
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return ""

    # Collect prior turns (everything except the last user message) for the digest.
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, dict) and msg.get("role") == "user":
            last_user_idx = i
            break

    if last_user_idx == -1:
        return ""

    last_msg = messages[last_user_idx]
    if not isinstance(last_msg, dict):
        return ""
    content = last_msg.get("content")
    if not isinstance(content, str):
        return ""

    prior = messages[:last_user_idx]
    if prior:
        digest = hashlib.sha256(json.dumps(prior, separators=(",", ":")).encode()).hexdigest()[:8]
        return f"[ctx:{digest}] {content}"
    return content


async def embed(http: httpx.AsyncClient, text: str) -> list[float]:
    s = get_settings()
    resp = await http.post(
        f"{s.embedding_api_base}/embeddings",
        json={"input": text, "model": s.embedding_model},
        headers={"Authorization": f"Bearer {s.openai_api_key}"},
    )
    resp.raise_for_status()
    data = cast(JSON, resp.json())
    items = data["data"]
    assert isinstance(items, list)
    first = items[0]
    assert isinstance(first, dict)
    embedding = first["embedding"]
    assert isinstance(embedding, list)
    return [float(v) for v in embedding]


async def lookup(
    conn: asyncpg.Connection,
    embedding: list[float],
    *,
    requested_model: str,
    threshold: float,
) -> JSON | None:
    row = await conn.fetchrow(_LOOKUP, embedding, requested_model)
    if row is None:
        return None
    similarity = cast(float, row["similarity"])
    if similarity < threshold:
        return None
    return cast(JSON, row["response_body"])


async def store(
    conn: asyncpg.Connection,
    *,
    request_hash: str,
    embedding: list[float],
    response: JSON,
    requested_model: str,
) -> None:
    await conn.execute(_STORE, request_hash, embedding, response, requested_model)
