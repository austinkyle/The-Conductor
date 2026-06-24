"""OpenAI adapter — pass-through. The gateway's public contract IS the OpenAI Chat
Completions shape, so request and response are the identity transform."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from translation.base import JSON, Adapter

if TYPE_CHECKING:
    from core.streaming import SSEEvent


class OpenAIAdapter(Adapter):
    path = "/chat/completions"

    def auth_headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}"}

    def to_provider_request(self, body: JSON) -> JSON:
        return body

    def from_provider_response(self, resp: JSON) -> JSON:
        return resp

    # --- streaming: pass-through. OpenAI only emits a usage chunk in stream mode when
    # `stream_options.include_usage` is set, so we always request it for reconciliation. ---

    def to_provider_stream_request(self, body: JSON) -> JSON:
        return {**body, "stream": True, "stream_options": {"include_usage": True}}

    async def from_provider_stream(
        self, events: AsyncIterator[SSEEvent]
    ) -> AsyncIterator[JSON]:
        async for event in events:
            chunk = json.loads(event.data)
            if isinstance(chunk, dict):
                yield chunk
