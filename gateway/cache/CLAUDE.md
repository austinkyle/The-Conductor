# cache/ — exact (Redis) + semantic (pgvector) + guardrails

## Routing table
| Task type | READ | SKIP | Tools / Skills |
|---|---|---|---|
| Exact-match cache | cache/exact.py (Redis) | routing/, dashboard/ | — |
| Semantic cache | cache/semantic.py, gateway/db (semantic_cache table) | budgets/ | pgvector |
| No-cache guardrails | cache/guardrails.py | translation/ | — |

## Invariants (the correctness signal — get these right)
- Embed the LAST user message + a lightweight hash/summary of prior context, NOT the whole history. Make it configurable; document why.
- BYPASS cache when: temperature above threshold, `no-cache` flag set, tool-use request, very recent context. A semantic cache that ignores temperature is a correctness bug.
- Cache AFTER a stream completes; serve hits as a synthetic stream.
- Similarity threshold is empirical — justify it with measured data from bench/, not a magic number.
- Write `cache_status` (miss / exact_hit / semantic_hit) to every request row.
