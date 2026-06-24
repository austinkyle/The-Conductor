# routing/ — aliases, fallback chain, error classification

## Routing table
| Task type | READ | SKIP | Tools / Skills |
|---|---|---|---|
| Add/modify a model alias | routing/aliases.py, gateway/db (models table) | cache/, dashboard/ | — |
| Fallback chain logic | routing/fallback.py | translation internals | — |
| Classify an error as retryable | routing/errors.py | everything else | — |

## Invariants
- Retryable: 429, 5xx, timeout, connection error. Terminal: 4xx (esp. 400). Never retry a terminal error onto the next provider — it just wastes latency.
- Apply backoff so a struggling provider isn't hammered.
- Record `fallback_depth` on every request row.
- Mid-stream failover is NOT supported by design. Failover only before the first token. Document this honestly.
