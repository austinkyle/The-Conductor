"""OpenAI adapter — pass-through. The gateway's public contract IS the OpenAI Chat
Completions shape, so request and response are the identity transform."""

from __future__ import annotations

from translation.base import JSON, Adapter


class OpenAIAdapter(Adapter):
    path = "/chat/completions"

    def auth_headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}"}

    def to_provider_request(self, body: JSON) -> JSON:
        return body

    def from_provider_response(self, resp: JSON) -> JSON:
        return resp
