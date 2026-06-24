"""Round-trip translation tests per adapter — pure, no network.

A translation bug is the likeliest source of subtle failures in this layer, so these
assert the exact shapes in both directions.
"""

from __future__ import annotations

from translation.anthropic import AnthropicAdapter
from translation.base import JSON
from translation.openai import OpenAIAdapter


def _first_choice(resp: JSON) -> dict[str, object]:
    choices = resp["choices"]
    assert isinstance(choices, list)
    choice = choices[0]
    assert isinstance(choice, dict)
    return choice


def _content(resp: JSON) -> str:
    message = _first_choice(resp)["message"]
    assert isinstance(message, dict)
    text = message["content"]
    assert isinstance(text, str)
    return text


# --- OpenAI: pass-through identity in both directions ---

def test_openai_request_is_identity() -> None:
    body: JSON = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]}
    assert OpenAIAdapter().to_provider_request(body) == body


def test_openai_response_is_identity() -> None:
    resp: JSON = {"id": "chatcmpl-1", "object": "chat.completion", "choices": []}
    assert OpenAIAdapter().from_provider_response(resp) == resp


# --- Anthropic: OpenAI -> Anthropic request ---

def test_anthropic_request_hoists_system_and_defaults_max_tokens() -> None:
    body: JSON = {
        "model": "claude-3-5-sonnet-latest",
        "messages": [
            {"role": "system", "content": "Be terse."},
            {"role": "user", "content": "Hi"},
        ],
    }
    req = AnthropicAdapter().to_provider_request(body)

    assert req["system"] == "Be terse."  # hoisted out of messages
    assert req["messages"] == [{"role": "user", "content": "Hi"}]  # system removed
    assert req["max_tokens"] == 1024  # required by Anthropic, defaulted
    assert req["model"] == "claude-3-5-sonnet-latest"


def test_anthropic_request_respects_explicit_max_tokens_and_stop() -> None:
    body: JSON = {
        "model": "claude-3-5-sonnet-latest",
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 50,
        "stop": "END",
    }
    req = AnthropicAdapter().to_provider_request(body)
    assert req["max_tokens"] == 50
    assert req["stop_sequences"] == ["END"]


# --- Anthropic: Anthropic response -> OpenAI shape ---

def test_anthropic_response_maps_to_openai_shape() -> None:
    resp: JSON = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-3-5-sonnet-latest",
        "content": [{"type": "text", "text": "Hello there!"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 3},
    }
    out = AnthropicAdapter().from_provider_response(resp)

    assert out["object"] == "chat.completion"
    assert _content(out) == "Hello there!"
    assert _first_choice(out)["finish_reason"] == "stop"
    assert out["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 3,
        "total_tokens": 13,
    }


def test_anthropic_max_tokens_stop_reason_maps_to_length() -> None:
    resp: JSON = {
        "content": [{"type": "text", "text": "..."}],
        "stop_reason": "max_tokens",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    out = AnthropicAdapter().from_provider_response(resp)
    assert _first_choice(out)["finish_reason"] == "length"
