"""Ordered fallback chain walk with per-attempt backoff."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, TypeVar

from db.models import Model, Provider
from routing.errors import ProviderError

T = TypeVar("T")


@dataclass(frozen=True)
class Attempt:
    depth: int
    model: Model
    provider: Provider


async def walk_chain(
    chain: list[tuple[Model, Provider]],
    attempt: Callable[[Attempt], Coroutine[Any, Any, T]],
    *,
    backoff: Callable[[int], float],
) -> tuple[T, Attempt]:
    """Try each candidate in order. Retry retryable failures; raise immediately on terminal.

    Returns the successful (result, attempt) pair so the caller knows which candidate won
    and can persist fallback_depth and served_provider_id.
    """
    last: ProviderError | None = None
    for depth, (model, provider) in enumerate(chain):
        a = Attempt(depth, model, provider)
        try:
            return await attempt(a), a
        except ProviderError as exc:
            if not exc.retryable:
                raise  # terminal — never cascade to the next candidate
            last = exc
            if depth + 1 < len(chain):
                await asyncio.sleep(backoff(depth))
    assert last is not None  # chain is guaranteed non-empty by resolve_chain
    raise last
