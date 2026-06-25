# budgets/ — per-key cost accounting + enforcement

Owns the cost math and the per-key spend counter. No DB schema changes — all needed
columns (api_key_id, cost_cents, etc.) were in 001_init.

## Routing table
| Task type | READ | SKIP | Tools / Skills |
|---|---|---|---|
| Modify cost math | budgets/accounting.py | enforce.py |  |
| Change enforcement thresholds / Redis logic | budgets/enforce.py | accounting.py |  |
| Wire a new caller-auth mechanism | core/auth.py | budgets/ entirely |  |

## As built (Phase 5A)

### Redis counter shape
`budget:{api_key_id}:{YYYY-MM}` — string holding a float with 4dp precision.
TTL: 35 days (set on first write via `expire`; covers month-boundary clock skew).

On a counter cache-miss: rebuild from `month_spend_cents` DB query, then prime Redis
with `SET … NX` (idempotent under concurrent miss).

### Anonymous policy
A missing or unrecognized Authorization header resolves to `key=None`. The pipeline
writes `api_key_id=NULL`, skips all budget checks, and records `cost_cents` for
observability. No enforcement, no `record_spend`.

### Cost on cache hit
Cache hits write `cost_cents=0` — the response was served free, not forwarded to a
provider. The observability dashboard can derive "cost saved by cache" from these rows
using the token counts stored from the original response body.

### Latency
`latency_ms` is `int((time.monotonic() - t0) * 1000)` measured from pipeline entry.
For the streaming path, latency is measured to the point where the chain resolves
(pre-first-token) — it is the provider-selection latency, not total stream duration.
