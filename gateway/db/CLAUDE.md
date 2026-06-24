# db/ — data model & migrations (5 core tables)

Tables: api_keys, providers, models, requests, semantic_cache.
Secrets are referenced (auth_ref / env), never stored in plaintext.

## Routing table
| Task type | READ | SKIP | Tools / Skills |
|---|---|---|---|
| Schema change | db/migrations/ (add next NNN_*.sql), db/models.py | all feature modules | — |
| pgvector setup | db/migrations/001_init.sql | dashboard/ | pgvector extension |

## Invariants
- Sequential migration files: NNN_slug.sql. Never edit an applied migration; add a new one.
- `semantic_cache.embedding` is a pgvector column. One Postgres, not a separate vector DB.
