# budgets/ — per-key cost accounting & enforcement

## Routing table
| Task type | READ | SKIP | Tools / Skills |
|---|---|---|---|
| Cost calc per request | budgets/accounting.py, gateway/db (models pricing, requests) | translation/, dashboard/ | — |
| Soft-warn / hard-block enforcement | budgets/enforce.py, gateway/db (api_keys) | cache/ | Redis counters |

## Invariants
- Reconcile token usage when the stream closes (counts arrive at the end).
- Hard limit blocks; soft limit warns. Behavior keyed off api_keys.hard_limit.
