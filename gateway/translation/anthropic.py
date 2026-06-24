"""Anthropic adapter — OpenAI Chat Completions <-> Anthropic Messages API.

Three real differences are handled explicitly (translation/CLAUDE.md):
  1. message structure   — OpenAI's flat messages -> Anthropic messages (system removed).
  2. system-prompt       — OpenAI puts system in `messages`; Anthropic wants a top-level
                           `system` string. We hoist + concatenate system turns.
  3. response/usage shape — Anthropic returns `content` blocks + `stop_reason` +
                           input/output token counts; we map back to the OpenAI shape.

Gotcha: Anthropic *requires* `max_tokens`; OpenAI treats it as optional, so we supply
a default when the caller omits it.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from translation.base import JSON, Adapter

if TYPE_CHECKING:
    from core.streaming import SSEEvent

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 1024

# Anthropic stop_reason -> OpenAI finish_reason.
_FINISH_REASON = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
}


def _as_text(content: object) -> str:
    """Flatten OpenAI message content (string, or a list of content parts) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            p["text"]
            for p in content
            if isinstance(p, dict) and isinstance(p.get("text"), str)
        ]
        return "".join(parts)
    return ""


def _as_int(value: object) -> int:
    return value if isinstance(value, int) else 0


class AnthropicAdapter(Adapter):
    path = "/messages"

    def auth_headers(self, key: str) -> dict[str, str]:
        return {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}

    def to_provider_request(self, body: JSON) -> JSON:
        messages = body.get("messages")
        if not isinstance(messages, list):
            raise ValueError("request body must include a 'messages' list")

        system_parts: list[str] = []
        out_messages: list[dict[str, object]] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") == "system":
                system_parts.append(_as_text(msg.get("content")))
            else:
                out_messages.append(
                    {"role": msg.get("role"), "content": _as_text(msg.get("content"))}
                )

        max_tokens = body.get("max_tokens")
        req: JSON = {
            "model": body.get("model"),
            "messages": out_messages,
            "max_tokens": max_tokens if isinstance(max_tokens, int) else DEFAULT_MAX_TOKENS,
        }
        if system_parts:
            req["system"] = "\n\n".join(p for p in system_parts if p)
        # Direct pass-through fields with identical semantics.
        for key in ("temperature", "top_p"):
            if key in body:
                req[key] = body[key]
        stop = body.get("stop")
        if isinstance(stop, str):
            req["stop_sequences"] = [stop]
        elif isinstance(stop, list):
            req["stop_sequences"] = stop
        return req

    def from_provider_response(self, resp: JSON) -> JSON:
        blocks = resp.get("content")
        text = ""
        if isinstance(blocks, list):
            text = "".join(
                b["text"]
                for b in blocks
                if isinstance(b, dict)
                and b.get("type") == "text"
                and isinstance(b.get("text"), str)
            )

        usage = resp.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        prompt_tokens = _as_int(usage.get("input_tokens"))
        completion_tokens = _as_int(usage.get("output_tokens"))

        stop_reason = resp.get("stop_reason")
        finish_reason = _FINISH_REASON.get(stop_reason, "stop") if isinstance(stop_reason, str) else "stop"

        return {
            "id": resp.get("id", ""),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": resp.get("model"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

    # --- streaming: Anthropic Messages SSE events -> OpenAI chat.completion.chunk dicts.
    # Input tokens arrive in `message_start`; output tokens + stop_reason in `message_delta`;
    # we emit a terminal usage chunk on `message_stop` so the engine reconciles uniformly. ---

    def to_provider_stream_request(self, body: JSON) -> JSON:
        return {**self.to_provider_request(body), "stream": True}

    async def from_provider_stream(
        self, events: AsyncIterator[SSEEvent]
    ) -> AsyncIterator[JSON]:
        msg_id = ""
        model: object = None
        prompt_tokens = 0
        completion_tokens = 0
        finish_reason = "stop"

        def chunk(delta: JSON, finish: str | None) -> JSON:
            return {
                "id": msg_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }

        async for event in events:
            data = json.loads(event.data)
            if not isinstance(data, dict):
                continue
            etype = data.get("type")

            if etype == "message_start":
                message = data.get("message")
                if isinstance(message, dict):
                    mid = message.get("id")
                    msg_id = mid if isinstance(mid, str) else ""
                    model = message.get("model")
                    usage = message.get("usage")
                    if isinstance(usage, dict):
                        prompt_tokens = _as_int(usage.get("input_tokens"))
                yield chunk({"role": "assistant"}, None)

            elif etype == "content_block_delta":
                delta = data.get("delta")
                if isinstance(delta, dict) and delta.get("type") == "text_delta":
                    text = delta.get("text")
                    if isinstance(text, str):
                        yield chunk({"content": text}, None)

            elif etype == "message_delta":
                delta = data.get("delta")
                if isinstance(delta, dict):
                    stop_reason = delta.get("stop_reason")
                    if isinstance(stop_reason, str):
                        finish_reason = _FINISH_REASON.get(stop_reason, "stop")
                usage = data.get("usage")
                if isinstance(usage, dict):
                    completion_tokens = _as_int(usage.get("output_tokens"))

            elif etype == "message_stop":
                yield chunk({}, finish_reason)
                yield {
                    "id": msg_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [],
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                    },
                }
