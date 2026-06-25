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

## As built (Phase 3)

### Error classification table
| HTTP status / exception | label | retryable |
|---|---|---|
| 429 | rate_limit | yes |
| 5xx | server_error | yes |
| timeout | timeout | yes |
| transport / connect | connection | yes |
| 4xx (not 429) | client_error | no |
| missing adapter or key | config | no |

### Priority-ordered chain
`models.priority` (added in migration 003) governs candidate order. Lower number = higher priority. Ties broken by `models.id` ASC. `resolve_chain` in `aliases.py` queries by alias first; falls back to a direct `provider_model` match for concrete passthrough requests.

### Backoff
`pipeline._backoff(depth)` computes `min(max_ms, base_ms * factor^depth) / 1000`. Configurable via `Settings.fallback_backoff_base_ms / _factor / _max_ms` (defaults: 500 ms / 1.8 / 30 000 ms). Tests monkeypatch `pipeline._backoff` to `lambda d: 0.0`.

### Persist at stream-open for streaming
For streaming requests, `insert_request` is called after `walk_chain` succeeds (pre-first-token). At that point `fallback_depth` and `served_provider_id` are known; token/cost columns remain null until Phase 4/5.
