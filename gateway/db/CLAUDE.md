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

## Schema notes (as built, 001_init)
- Driver: asyncpg, raw SQL (no ORM). `models.py` holds frozen dataclass row shapes.
- `migrate.py` tracks applied files in `schema_migrations`; idempotent re-runs.
- `semantic_cache.embedding` is `vector(1536)` (default OpenAI embedding dim); `response_body` is `jsonb`.
- Prices in `models` are USD per 1,000,000 tokens.

## Phase 3 additions (003_routes)
- `models.priority int NOT NULL DEFAULT 0` — lower value = higher priority in the fallback chain.
- `db/models.py`: `Model.priority: int = 0` added as the last field (default preserves existing positional constructors).
- `db/queries.py`: `resolve_model` replaced by `insert_request`; chain resolution lives in `routing/aliases.py`.
- `requests` write path: `insert_request` writes `requested_model`, `served_provider_id`, `served_model`, `status`, `error_class`, `fallback_depth` on every request (success and error). Remaining columns (tokens, cost, cache_status, latency) are filled in Phase 4/5.

## Phase 4 additions (004_semantic_cache_index)
- `HNSW cosine index` on `semantic_cache.embedding` — makes ANN cosine search sub-linear at scale.
- `insert_request` gains `cache_status text | None` — written as `"exact_hit"`, `"semantic_hit"`, or `"miss"` on every request row.

## Post-launch fix (007_semantic_cache_unique_hash)
- 004's `request_hash` index was a plain btree, which does NOT satisfy `ON CONFLICT (request_hash) DO NOTHING` in `store()` — Postgres requires a unique index/constraint on the conflict target. 007 replaces it with a `UNIQUE INDEX` (de-duping existing rows first). See ADR-006.

## Post-launch fix (008_update_anthropic_models)
- 002/003 seeded `claude-3-5-sonnet-latest` / `claude-3-5-haiku-latest`, both retired and 404 live against the real Anthropic API. 008 updates those rows in place to `claude-sonnet-5` and `claude-haiku-4-5-20251001` with current pricing, rather than editing 002/003.
