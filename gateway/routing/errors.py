"""Error classification: retryable vs. terminal, and the ProviderError exception.

Pure functions only — no imports from routing.fallback or routing.aliases, so this
module is safe to import from anywhere without cycles.
"""

from __future__ import annotations

import httpx


def is_retryable_status(status: int) -> bool:
    return status == 429 or status >= 500


def label_for_status(status: int) -> str:
    if status == 429:
        return "rate_limit"
    if status >= 500:
        return "server_error"
    return "client_error"  # 400–499 → terminal


def label_for_exception(exc: Exception) -> str | None:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.TransportError):
        return "connection"
    return None  # unknown → caller re-raises


class ProviderError(Exception):
    """Carries everything needed to drive the fallback chain and persist the request row."""

    def __init__(
        self,
        *,
        label: str,
        retryable: bool,
        status: int,
        detail: str,
        depth: int,
        provider_id: int,
        served_model: str,
    ) -> None:
        super().__init__(detail)
        self.label = label
        self.retryable = retryable
        self.status = status
        self.detail = detail
        self.depth = depth
        self.provider_id = provider_id
        self.served_model = served_model


def from_status(
    status: int,
    detail: str,
    *,
    depth: int,
    provider_id: int,
    served_model: str,
) -> ProviderError:
    return ProviderError(
        label=label_for_status(status),
        retryable=is_retryable_status(status),
        status=status,
        detail=detail,
        depth=depth,
        provider_id=provider_id,
        served_model=served_model,
    )


def from_exception(
    exc: Exception,
    *,
    depth: int,
    provider_id: int,
    served_model: str,
) -> ProviderError:
    """Classify a transport exception. Re-raises if the exception type is unrecognised."""
    label = label_for_exception(exc)
    if label is None:
        raise exc
    return ProviderError(
        label=label,
        retryable=True,
        status=502,
        detail=str(exc),
        depth=depth,
        provider_id=provider_id,
        served_model=served_model,
    )
