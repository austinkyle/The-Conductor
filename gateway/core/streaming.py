"""The SSE streaming engine.

Commodity plumbing lives here (parse provider SSE lines into events, serialize OpenAI
chunks back to SSE bytes, forward live). The provider-specific event translation is the
adapters' job — they yield OpenAI `chat.completion.chunk` dicts and this engine treats
them uniformly: forward each chunk to the client, buffer the assembled text so Phase 4
can persist it, and reconcile usage at stream close onto the request object.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

    from core.request import GatewayRequest
    from translation.base import JSON, Adapter


@dataclass
class SSEEvent:
    """One parsed Server-Sent Event: an optional `event:` name and its `data:` payload."""

    event: str | None
    data: str


async def iter_sse(lines: AsyncIterator[str]) -> AsyncIterator[SSEEvent]:
    """Group a provider's raw SSE lines into events.

    Skips comments/keepalives (`ping`), blank separators, and the `[DONE]` sentinel — the
    engine emits its own `[DONE]` to the client. OpenAI sends only `data:` lines; Anthropic
    also sends `event:` lines, so both fields are carried.
    """
    event: str | None = None
    data_parts: list[str] = []
    async for raw in lines:
        line = raw.rstrip("\r")
        if line == "":  # event boundary
            if data_parts:
                data = "\n".join(data_parts)
                if data != "[DONE]":
                    yield SSEEvent(event=event, data=data)
            event = None
            data_parts = []
            continue
        if line.startswith(":"):  # comment / keepalive
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event = value
        elif field == "data":
            data_parts.append(value)
    # Flush a trailing event with no terminating blank line.
    if data_parts:
        data = "\n".join(data_parts)
        if data != "[DONE]":
            yield SSEEvent(event=event, data=data)


def sse_encode(chunk: JSON) -> bytes:
    """Serialize one OpenAI chunk dict to an SSE `data:` frame."""
    return b"data: " + json.dumps(chunk).encode() + b"\n\n"


async def stream_openai(
    req: GatewayRequest, adapter: Adapter, response: httpx.Response
) -> AsyncIterator[bytes]:
    """Forward an adapter's OpenAI chunk stream to the client as SSE bytes.

    While forwarding live, buffer the assembled assistant text and harvest usage from
    whichever chunk carries it; both are stashed on `req` at close for Phase 4/5.
    """
    parts: list[str] = []
    async for chunk in adapter.from_provider_stream(iter_sse(response.aiter_lines())):
        choices = chunk.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if isinstance(content, str):
                        parts.append(content)
        usage = chunk.get("usage")
        if isinstance(usage, dict):
            req.usage = {k: v for k, v in usage.items() if isinstance(v, int)}
        yield sse_encode(chunk)

    yield b"data: [DONE]\n\n"
    req.assembled_content = "".join(parts)
