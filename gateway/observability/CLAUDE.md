# observability/ — request log writes + dashboard read API

## Routing table
| Task type | READ | SKIP | Tools / Skills |
|---|---|---|---|
| Write a request-log row | observability/log.py, gateway/db (requests) | translation/, cache/ | — |
| Dashboard read endpoint | observability/api.py, gateway/db (requests) | budgets internals | — |

## Invariants
- The `requests` table is the single spine for dashboard + budgets. One row per call, always written (even on error — set status/error_class).
