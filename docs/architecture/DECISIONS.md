# Architecture Decisions (running log)

Append a short entry as you make each non-trivial decision. For each: the
decision, the alternative you rejected, and WHY. This log is the raw material
for the README's Architecture Decisions section — the single clearest seniority
signal. Juniors document features; seniors document why.

Pre-seeded decisions (from the build spec — flesh out with specifics as you build):

## ADR-001 — Drop-in OpenAI API compatibility
Decision: speak the OpenAI Chat Completions shape, not a custom API.
Rejected: a clean custom contract.
Why: adoptability — any SDK/LangChain/LlamaIndex works by changing one base_url.
Tradeoff accepted: coupling to someone else's contract + a real translation layer per provider.

## ADR-002 — Cache after stream completion; failover only pre-first-token
Decision: assemble + persist the cache entry once the stream closes; serve hits as a synthetic stream. Fail over only before the first token.
Rejected: pretending mid-stream failover is clean.
Why: once the client has partial output you cannot cleanly retry elsewhere. Honesty about this edge is the signal.

## ADR-003 — pgvector instead of a dedicated vector DB
Decision: semantic-cache vectors live in Postgres via pgvector.
Rejected: a standalone vector database.
Why: one fewer piece of infrastructure; Postgres is already in the stack; gateway-cache scale doesn't need a specialized store. Fewer moving parts.

## ADR-004 — FastAPI/Python over Go/Rust
Decision: async FastAPI.
Rejected: Go/Rust for "infra flex."
Why: a clean, well-tested async implementation in the stack you operate beats shaky code in a language you don't. Port the hot path to Go later as a victory lap, not the build.

---

## Phase 0 — skeleton (config, 5-table model, migrations, compose)

### asyncpg over psycopg3
Decision: asyncpg as the Postgres driver.
Rejected: psycopg3 async.
Why: lowest-latency async driver for a proxy where DB calls sit on the request path; pgvector ships a first-class asyncpg adapter. Tradeoff: asyncpg's API is less DBAPI-standard, but we use raw SQL (no ORM) so portability cost is small.

### Hand-rolled sequential migration runner
Decision: a ~40-line runner that applies `migrations/NNN_*.sql` in filename order and records applied files in a `schema_migrations` table; re-runs are no-ops.
Rejected: Alembic / a migration framework.
Why: commodity glue, and the five-table model barely moves. A framework's autogenerate/branching machinery is overhead we'd never use. Never edit an applied migration — add the next NNN file.

### pgvector inside Postgres (image: pgvector/pgvector:pg16)
Decision: semantic-cache vectors live in Postgres via the pgvector extension; `semantic_cache.embedding` is `vector(1536)`. (Restates ADR-003 with the concrete dimension.)
Why 1536: matches OpenAI text-embedding-3-small / ada-002, the default `EMBEDDING_MODEL`. The dimension is fixed in SQL; a different embedding model later means a new migration, not an edit.
Also: `semantic_cache.response_body` is `jsonb` (it stores a structured OpenAI response), not text.

### Column scope vs. "no speculative columns"
Decision: each table carries the columns named by later build phases (e.g. `requests.fallback_depth`, `cache_status`, `cost_cents`), defined now.
Why: migrations are append-only and applied files are immutable, so columns that are explicit downstream requirements are not speculation — defining them once avoids a churn of ALTER migrations. Columns no phase references are omitted.

### Secrets by reference, validated at boot
Decision: `providers.auth_ref` stores the *name* of the env var holding a provider key; `api_keys.key_hash` stores a hash of the gateway-issued caller key. Config requires `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DATABASE_URL`, `REDIS_URL` with no defaults, so a missing secret fails at startup, not mid-request.
