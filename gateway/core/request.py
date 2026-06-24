"""Provider-agnostic request object — streaming-aware from day one.

Phase 1 only walks the non-streaming path, but the shape carries the `stream` flag
and slots for served-provider / usage so Phase 2 (SSE) and Phase 4+ (logging,
budgets) are extensions, not retrofits.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GatewayRequest:
    """A parsed inbound OpenAI-shaped request as it flows through the pipeline."""

    body: dict[str, object]  # the raw OpenAI chat-completions payload
    model: str
    stream: bool

    # Filled in as the request is served — read later for logging/budgets.
    served_provider: str | None = None
    served_model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_body(cls, body: dict[str, object]) -> GatewayRequest:
        model = body.get("model")
        if not isinstance(model, str) or not model:
            raise ValueError("request body must include a non-empty 'model'")
        return cls(body=body, model=model, stream=bool(body.get("stream", False)))
