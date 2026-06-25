"""Minimal asyncio HTTP/1.1 mock provider for benchmark scripts.

Returns a canned OpenAI chat-completion response for every POST, regardless of path.
Binds to 0.0.0.0 so the gateway Docker container can reach it via host.docker.internal.
"""
from __future__ import annotations

import asyncio
import json
import random

_CANNED = json.dumps({
    "id": "chatcmpl-mock",
    "object": "chat.completion",
    "created": 1719000000,
    "model": "mock-model",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "ok"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
}).encode()


def canned_response() -> bytes:
    """Minimal valid OpenAI chat completion body."""
    return _CANNED


async def _handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    fail_rate: float,
) -> None:
    try:
        while True:
            request_line = await reader.readline()
            if not request_line:
                break

            content_length = 0
            while True:
                header = await reader.readline()
                if header in (b"\r\n", b"\n", b""):
                    break
                if header.lower().startswith(b"content-length:"):
                    content_length = int(header.split(b":", 1)[1].strip())

            if content_length > 0:
                await reader.readexactly(content_length)

            if fail_rate > 0 and random.random() < fail_rate:
                response = (
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: keep-alive\r\n\r\n"
                )
            else:
                body = canned_response()
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    + b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                    + b"Connection: keep-alive\r\n\r\n"
                    + body
                )

            writer.write(response)
            await writer.drain()

    except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def start_mock_provider(port: int, *, fail_rate: float = 0.0) -> asyncio.Server:
    """Start HTTP server on *port* that returns canned OpenAI responses.

    fail_rate=1.0 → always 503 (simulates provider outage).
    fail_rate=0.0 → always 200 with canned body.
    """
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _handle(reader, writer, fail_rate)

    return await asyncio.start_server(handler, host="0.0.0.0", port=port)
