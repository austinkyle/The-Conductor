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

---

## Phase 1 — transparent non-streaming proxy (two providers)

### ADR-001 (detail) — the translation seam, and where provider-specifics live
Decision: a per-provider `Adapter` (translation/base.py) owns the endpoint `path`, `auth_headers`, and the OpenAI↔native request/response mapping; the pipeline knows only the provider `base_url` (from the DB) and which adapter to use. `openai.py` is the identity transform because the public contract *is* the OpenAI Chat Completions shape.
Rejected: branching on provider name inside the pipeline; a normalized "universal" internal message format.
Why: the coupling to OpenAI's contract (ADR-001) is accepted for adoptability, so the cost of that coupling — a real translation layer — is isolated behind one interface. A universal internal format would be a third shape to maintain for two providers; the adapter pair is less code and the differences (Anthropic's top-level `system`, required `max_tokens`, `x-api-key`/`anthropic-version` headers, `content` blocks, `stop_reason`) are mapped explicitly and round-trip tested.

### Streaming-aware request object, non-streaming path first
Decision: `core.GatewayRequest` carries the `stream` flag and served-provider/usage slots from day one; Phase 1 only walks the non-streaming branch and refuses `stream:true` with a 501.
Why: Phase 2 (SSE) extends the shape rather than retrofitting it. Refusing streaming honestly beats silently dropping the flag.

### Direct model→provider resolution, seeded by migration
Decision: a request's `model` is resolved directly against `models.alias` (alias = provider_model for now) via a join to `providers`; providers/models rows are seeded by an append-only migration (`002_seed_providers.sql`).
Rejected: logical aliases + fallback chain (deferred to Phase 3); a config-file provider map (would bypass the providers/models tables and the secrets-by-reference path).
Why: keeps key resolution flowing through `providers.auth_ref`, and seeding via the idempotent migration runner keeps provider data in tracked, append-only history alongside the schema.
