"""Typed row shapes for the five core tables.

Plain frozen dataclasses, not an ORM — queries use raw asyncpg and map rows into
these for type-checked reads. Mirrors migrations/001_init.sql.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class ApiKey:
    id: int
    key_hash: str
    name: str
    soft_limit_cents: int | None
    hard_limit_cents: int | None
    created_at: datetime


@dataclass(frozen=True)
class Provider:
    id: int
    name: str
    base_url: str
    auth_ref: str
    api_format: str
    created_at: datetime


@dataclass(frozen=True)
class Model:
    id: int
    alias: str
    provider_id: int
    provider_model: str
    input_price_per_mtok: Decimal | None
    output_price_per_mtok: Decimal | None
    created_at: datetime
    priority: int = 0


@dataclass(frozen=True)
class Request:
    id: int
    api_key_id: int | None
    requested_model: str | None
    served_provider_id: int | None
    served_model: str | None
    status: str
    error_class: str | None
    fallback_depth: int
    cache_status: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost_cents: Decimal | None
    latency_ms: int | None
    created_at: datetime


@dataclass(frozen=True)
class SemanticCacheEntry:
    id: int
    request_hash: str
    embedding: list[float]
    response_body: dict[str, object]
    model: str | None
    created_at: datetime
