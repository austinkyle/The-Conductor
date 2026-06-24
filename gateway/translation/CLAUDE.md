# translation/ — provider format adapters

Translates between the OpenAI Chat Completions contract (the gateway's public
shape) and each provider's native format. This is the documented coupling
tradeoff: adoptability over purity.

## Routing table
| Task type | READ | SKIP | Tools / Skills |
|---|---|---|---|
| Add a provider | translation/base.py + new adapter file | routing/, cache/, dashboard/ | that provider's API reference |
| Fix request translation | the one adapter (openai.py / anthropic.py) | everything else | — |
| Fix stream-event translation | the adapter's stream section + core/streaming.py | budgets/, cache/ | provider SSE event schema |

## Invariants
- Anthropic differs from OpenAI in: message structure, system-prompt handling, stream event shapes. Handle all three explicitly.
- A translation bug is the likeliest source of subtle failures here — add a round-trip test per adapter.

## As built — adapter contract (Phase 1)
- Each `Adapter` (base.py) owns its provider's `path`, `auth_headers(key)`, and request/response mapping. The pipeline only knows the provider's `base_url` (from the DB) + the adapter; it does not special-case providers.
- `openai.py` is the identity transform — the public contract IS OpenAI shape.
- Stream methods are stubbed (`NotImplementedError`); Phase 2 fills them.

## Anthropic gotchas (Phase 1)
- **`max_tokens` is required** by the Messages API; OpenAI treats it as optional. The adapter defaults to `DEFAULT_MAX_TOKENS` (1024) when the caller omits it.
- **Auth/headers:** `x-api-key: <key>` + `anthropic-version` (not `Authorization: Bearer`). Endpoint is `/messages`, not `/chat/completions`.
- **System prompt:** OpenAI carries `role:"system"` in `messages`; Anthropic wants a top-level `system` string. System turns are hoisted out and concatenated.
- **Response:** map `content[].text` blocks → `choices[0].message.content`; `stop_reason` → `finish_reason` (`end_turn`/`stop_sequence`→`stop`, `max_tokens`→`length`); `usage.input_tokens`/`output_tokens` → `prompt_tokens`/`completion_tokens` (+`total_tokens`).
