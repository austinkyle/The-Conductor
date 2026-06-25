# observability/ — request log writes + dashboard read API

## Routing table
| Task type | READ | SKIP | Tools / Skills |
|---|---|---|---|
| Write a request-log row | observability/log.py, gateway/db (requests) | translation/, cache/ | — |
| Dashboard read endpoint | observability/api.py, observability/queries.py | gateway internals | — |

## Invariants
- The `requests` table is the single spine for dashboard + budgets. One row per call, always written (even on error — set status/error_class).
- All queries are read-only. No writes from the read API.

## Read API endpoints (all `GET /v1/observability/*?window=24h|7d|30d`)

| Endpoint | Response shape |
|---|---|
| `/spend?window&bucket=hour\|day` | `[{ts: datetime, cost_cents: Decimal}]` |
| `/cache` | `{total, exact_hit, semantic_hit, miss: int, hit_rate: float}` |
| `/latency` | `{p50, p95, p99: float \| null}` |
| `/savings` | `{cost_saved_cents: Decimal}` |
| `/failovers` | `[{ts, requested_model, served_model: str\|null, fallback_depth: int}]` |
| `/keys` | `[{name: str, requests, total_tokens: int, cost_cents: Decimal}]` |
