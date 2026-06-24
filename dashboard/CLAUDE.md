# dashboard/ — Next.js + TS observability UI

Reads from the observability read API. Shows: spend over time, cache hit rate,
p50/p95/p99 latency, cost-saved-by-cache, failover events, per-key usage.

## Routing table
| Task type | READ | SKIP | Tools / Skills |
|---|---|---|---|
| Build/modify a chart or view | dashboard/ only | the entire gateway/ backend except the read-API contract | frontend-design skill |
| Wire to backend | dashboard/lib/api.ts + the observability read-API shape | gateway internals | — |

## Invariants
- TS strict mode, named exports. Talk to the backend only through the documented read API; do not reach into the DB.
