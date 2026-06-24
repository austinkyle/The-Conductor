"""The adapter seam: OpenAI Chat Completions <-> a provider's native format.

This interface is the one pre-justified abstraction in this layer (root CLAUDE.md).
Each provider gets one Adapter that knows its endpoint path, auth header style, and
request/response mapping. The stream methods translate the provider's SSE event stream
into OpenAI `chat.completion.chunk` dicts; the engine (core/streaming.py) owns the SSE
bytes, live forwarding, buffering, and usage reconciliation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.streaming import SSEEvent

# The OpenAI chat-completions payloads are open-shaped JSON; we map fields explicitly
# rather than model every field, so a loose dict is the honest type at this boundary.
JSON = dict[str, object]


class Adapter(ABC):
    path: str  # endpoint path appended to the provider base_url

    @abstractmethod
    def auth_headers(self, key: str) -> dict[str, str]:
        """Provider-specific auth (and version) headers for the outbound call."""

    @abstractmethod
    def to_provider_request(self, body: JSON) -> JSON:
        """OpenAI request body -> provider request body."""

    @abstractmethod
    def from_provider_response(self, resp: JSON) -> JSON:
        """Provider response body -> OpenAI chat-completion response body."""

    # --- streaming ---

    @abstractmethod
    def to_provider_stream_request(self, body: JSON) -> JSON:
        """OpenAI request body -> provider request body with streaming enabled."""

    @abstractmethod
    def from_provider_stream(
        self, events: AsyncIterator[SSEEvent]
    ) -> AsyncIterator[JSON]:
        """Provider SSE events -> OpenAI `chat.completion.chunk` dicts."""
