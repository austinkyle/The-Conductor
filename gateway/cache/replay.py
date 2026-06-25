"""Synthetic SSE stream for cache hits.

Cache hits bypass the provider entirely. To match the live streaming behavior the client
expects, we emit the same OpenAI `chat.completion.chunk` sequence a real provider would
produce: a role-delta chunk, a content-delta chunk, a finish chunk, and a terminal usage
chunk — then the `[DONE]` sentinel.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from core.streaming import sse_encode
from translation.base import JSON

if TYPE_CHECKING:
    from core.request import GatewayRequest


async def synthetic_stream(response: JSON) -> AsyncIterator[bytes]:
    """Replay a cached non-streaming response body as an SSE chunk stream."""
    model = response.get("model", "")
    rid = response.get("id", "cached")

    choices = response.get("choices")
    content = ""
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message")
            if isinstance(msg, dict):
                c = msg.get("content")
                if isinstance(c, str):
                    content = c

    usage = response.get("usage")

    base: JSON = {"id": rid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model}

    yield sse_encode({**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
    yield sse_encode({**base, "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]})
    yield sse_encode({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    if isinstance(usage, dict):
        yield sse_encode({**base, "choices": [], "usage": usage})
    yield b"data: [DONE]\n\n"


def assembled_to_response(req: GatewayRequest, requested_model: str) -> JSON:
    """Build a non-streaming response body from a completed streaming request, for caching."""
    return {
        "id": "cached",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": requested_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": req.assembled_content or ""},
                "finish_reason": "stop",
            }
        ],
        "usage": req.usage,
    }
