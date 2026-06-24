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
