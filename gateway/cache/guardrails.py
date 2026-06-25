"""Cache bypass guardrails — pure function, no I/O.

Four conditions force a bypass:
  1. temperature > threshold (high-temperature responses are non-deterministic by design)
  2. caller no-cache signal (`cache: false` or `cache: {no_cache: true}`)
  3. caller recent-context signal (`cache: {recent_context: true}`) — stateless gateway,
     so caller knows whether the session state is too fresh to trust a cached reply
  4. tool-use request (non-empty `tools`, `functions`, or a non-"none" `tool_choice`)

Returns the bypass reason string (truthy) or None (no bypass).
"""

from __future__ import annotations

from translation.base import JSON


def should_bypass(body: JSON, *, temperature_bypass: float = 0.3) -> str | None:
    temp = body.get("temperature")
    if isinstance(temp, (int, float)) and float(temp) > temperature_bypass:
        return "temperature"

    cache_flag = body.get("cache")
    if cache_flag is False:
        return "no_cache"
    if isinstance(cache_flag, dict):
        if cache_flag.get("no_cache") or cache_flag.get("recent_context"):
            return "no_cache"

    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        return "tool_use"

    functions = body.get("functions")
    if isinstance(functions, list) and functions:
        return "tool_use"

    tool_choice = body.get("tool_choice")
    if isinstance(tool_choice, str) and tool_choice != "none":
        return "tool_use"
    if isinstance(tool_choice, dict):
        return "tool_use"

    return None
