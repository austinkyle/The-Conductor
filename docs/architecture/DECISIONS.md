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

---

## Phase 2 — SSE streaming + per-provider stream translation

### Adapters yield OpenAI chunk dicts; the engine owns SSE bytes, buffering, reconciliation
Decision: each adapter's `from_provider_stream` consumes parsed provider SSE events and yields OpenAI `chat.completion.chunk` *dicts*. The engine (`core/streaming.py`) serializes each to an SSE frame, forwards it live, buffers the assembled assistant text, and harvests `usage`. The commodity SSE parser (`iter_sse`) and encoder (`sse_encode`) live in the engine, shared by both adapters.
Rejected: adapters that emit raw SSE bytes (would force the engine to re-parse to buffer/reconcile, duplicating JSON work and splitting the chunk shape across two layers); a usage side-channel out of the chunk stream.
Why: provider stream-event translation is the judgment seam (root CLAUDE.md) and belongs in the adapter; the SSE plumbing is commodity and belongs in one place. With adapters speaking one normalized shape (OpenAI chunks), the engine stays fully provider-agnostic — content buffering and usage harvesting are written once.

### Usage reconciliation at stream close, in-band as a terminal usage chunk
Decision: both providers surface final token counts as a terminal OpenAI-shape usage chunk (`choices: []`, `usage: {...}`). OpenAI needs `stream_options.include_usage: true` on the request (it omits usage in stream mode otherwise); Anthropic carries `input_tokens` in `message_start` and the cumulative `output_tokens` + `stop_reason` in `message_delta`, which the adapter folds into a synthesized usage chunk on `message_stop`. The engine reads `usage` from whichever chunk carries it and stashes it on `GatewayRequest` (with the buffered `assembled_content`) at close.
Why: counts only exist at the end of the stream. A single in-band, OpenAI-shaped usage chunk means the client sees standard behavior and the engine reconciles uniformly — no per-provider branching for the buffer-then-persist path Phase 4 (cache) and Phase 5 (budgets) build on.

### Buffer-then-persist; failover only before the first token (restates ADR-002)
Decision: the assembled response is buffered as it streams so Phase 4 can persist/cache it. A streaming upstream error can only surface to the client *before the first token* — the status check sits at stream open (`http.stream` → `aread()` on `>=400` → `HTTPException`); once chunks have begun there is no mid-stream failover. The pooled DB connection is held for the generator's lifetime, forward-compatible with Phase 4/5 close-time writes.
Rejected: pretending a mid-stream provider failure can be cleanly retried elsewhere.
Why: once the client holds partial output, retrying on another provider produces a corrupt stream. Honesty about this edge (ADR-002) is the signal; the buffer is what makes close-time persistence and synthetic cache replay possible later.

---

## Phase 3 — routing aliases + fallback chain + error classification

### ADR-002 (detail) — failover decision sits inside walk_chain, pre-first-token
Decision: `_stream_attempt` opens the HTTP stream via an `AsyncExitStack`, peeks the status code, and either raises a classified `ProviderError` (closing the stack) or returns a `forward()` async generator that owns the stack. `walk_chain` decides to cascade or stop *before* `_stream_attempt` returns; the caller never holds a partial stream when the chain is still being walked.
Why: this satisfies ADR-002 without special-casing the streaming branch. The `attempt` callable passed to `walk_chain` is generic over T — the non-streaming branch returns JSON, the streaming branch returns an `AsyncIterator[bytes]`. Both branches share identical failover semantics.

### Priority column over implicit id order
Decision: `models.priority int NOT NULL DEFAULT 0` (migration 003) governs candidate order within an alias chain, not `id` (insertion order). Ties go to lower id.
Rejected: relying on insertion order (migration seed order) to imply priority.
Why: a future operator adding a second candidate for "smart" would have to know that inserting after the existing row means fallback. An explicit `priority` column makes intent legible in the table and survives reordering.

### Classification rules: 4xx is terminal, 5xx/429/transport is retryable
Decision: status 4xx (except 429) is a terminal error — never cascade. 5xx, 429, httpx.TimeoutException, and httpx.TransportError are retryable.
Rejected: cascading on any error.
Why: a 400/401/403/404 from a provider almost certainly means the *request* is wrong (bad payload, bad auth), not the provider. Cascading would silently hide configuration bugs and waste the next provider's quota. A 5xx, 429, or connection error is a provider availability issue — exactly the case a fallback chain is designed for.

### Config error (missing adapter/key) is terminal
Decision: a missing adapter class or unresolvable `auth_ref` env var raises `ProviderError(label="config", retryable=False)`, which stops the chain immediately.
Why: this is operator misconfig — it will fail on every provider in the chain the same way. Cascading through all candidates and failing on each wastes latency with no upside.

### request row written at walk_chain resolution (write-at-open for streams)
Decision: `insert_request` is called once, immediately after `walk_chain` resolves — on success with `status="success"`, on failure with `status="error"`. For streaming, the write happens before the first byte is yielded to the client.
Rejected: deferring the write to stream close (the Phase 4 approach for token/cost columns).
Why: provider identity (`served_provider_id`, `fallback_depth`) is known at resolution time. Writing at open means even a half-completed stream gets a row. Token/cost/cache columns remain null and are filled in Phase 4/5.

---

## Phase 4 — two-layer cache (exact + semantic) with guardrails

### Bypass guardrails are a pure function; `recent_context` is caller-signaled
Decision: `should_bypass(body, *, temperature_bypass) -> str | None` takes the request body and returns the bypass reason or None. The "very recent context" guardrail is signaled by the caller via `body["cache"]["recent_context"]`, not inferred by the gateway.
Rejected: the gateway trying to detect recency itself (session-length heuristics, clock-based windowing).
Why: the gateway is stateless — it has no knowledge of the caller's session history. Any heuristic it applied would be wrong in edge cases and untestable. The caller always knows whether its context is too fresh for a cached reply; making it explicit keeps the contract honest and the function purely testable.

### Embed strategy: `last_plus_digest`
Decision: `embed_text` embeds the **last** user message, prefixed with the first 8 hex chars of SHA-256 over all prior turns (earlier messages combined).
Rejected: embedding the entire message history; embedding only the last message (no context scope).
Why: embedding the full history risks hitting embedding-length limits for long conversations, and long inputs make similarity search less precise. Embedding only the last message misses session context — the same question means different things in different conversations. The 8-char SHA-256 prefix is a collision-resistant context fingerprint: same prior context → same prefix → embeddings from different sessions don't collide. Prefix is short (8 chars) and cheap to compute.

### Semantic similarity threshold is a placeholder
Decision: `semantic_similarity_threshold` defaults to 0.92 and is clearly documented as a placeholder.
Rejected: treating 0.92 as authoritative without empirical measurement.
Why: the right threshold depends on the embedding model, query distribution, and the cost of false positives (wrong cached answer) vs. false negatives (cache miss). The bench/ harness (Phase 5) must measure hit-rate vs. false-positive rate on real traffic before the value is used in production. A placeholder with a loud comment is better than a magic number that gets cargo-culted.

### Cache hit row: `served_provider_id = NULL, served_model = NULL`
Decision: on a cache hit, `insert_request` is called with `served_provider_id=None, served_model=None, status="success", cache_status="exact_hit"|"semantic_hit"`.
Rejected: skipping the insert for cache hits; recording a fake provider.
Why: every gateway request gets a row — that's how the observability dashboard knows request volume. `NULL` provider columns are the honest signal that no provider was called (the response came from cache). `cache_status` distinguishes the hit type.

### Write-at-stream-close, not write-at-stream-open (cache for streaming)
Decision: for streaming requests, the cache is written AFTER the `async for chunk in gen:` loop exhausts the generator, not before or during streaming.
Rejected: writing the cache entry at stream-open (no assembled content yet); writing it from inside the generator.
Why: `req.assembled_content` is only set by the streaming engine after the last chunk is yielded. The post-loop code only runs if the loop completes normally — `GeneratorExit` from a client disconnect skips the block, so partial/interrupted streams are never cached. This is the simplest correct approach: let the generator run, then cache what the engine buffered.

### Synthetic stream shape matches live streaming
Decision: cache hits served to streaming callers emit the same `chat.completion.chunk` SSE sequence a provider would: role-delta → content-delta → finish-reason → usage → [DONE].
Rejected: returning the non-streaming response body directly on a streaming request.
Why: the client's stream parser already started before it knew whether the response would be live or cached. Returning a JSON body on a `StreamingResponse` would break the client. The synthetic stream also preserves the client's ability to stream-render incrementally even on hits (though with a single content chunk instead of a token-by-token stream).

### pgvector asyncpg codec registered on pool init, not per-request
Decision: `list[float] ↔ vector` type codec registered via `asyncpg.create_pool(init=_init_pool_conn)`.
Rejected: registering per-connection inline in `semantic.store`/`lookup`.
Why: `init` fires on every new connection in the pool, making the codec available to all queries on that connection without any per-query setup. Per-request registration would add a round-trip to every DB call, and forgetting to register before the first vector query would be a runtime error in production.

### `ON CONFLICT (request_hash) DO NOTHING` for semantic store
Decision: `store` uses `ON CONFLICT (request_hash) DO NOTHING` — concurrent inserts for the same hash are silently dropped.
Rejected: `ON CONFLICT DO UPDATE`; raising on conflict.
Why: duplicate entries (same content, same response) add noise but don't affect correctness — the lookup returns `LIMIT 1`. Idempotent inserts are safe to retry. `DO NOTHING` is the lowest-ceremony correct choice.

---

## Phase 5A — Budgets: per-key cost accounting + soft-warn / hard-block enforcement

### Redis counter with DB as source of truth
Decision: the monthly spend counter lives in Redis (`budget:{api_key_id}:{YYYY-MM}`, string, 4dp float). On a counter cache-miss the counter is rebuilt from a `SUM(cost_cents)` query over the requests table for the current month, then primed with `SET … NX`. TTL is 35 days to survive month-end boundaries.
Rejected: DB-only counter (a `SELECT SUM` on every request would add 1–2 ms per call, paid on every request); purely in-memory counter (lost on restart, inconsistent under multi-instance deploy).
Why: Redis `INCRBYFLOAT` is O(1) and sub-millisecond; the DB query is the authoritative fallback on cold-start or eviction. The two-layer design means the counter is always consistent: a cold Redis just reads from the source of truth, not from a stale cache.

### Anonymous requests are allowed (api_key_id NULL, no enforcement)
Decision: a missing or unrecognized `Authorization` header resolves to `key=None`. The request is served normally; `api_key_id=NULL` is written to the requests row; no budget is checked or decremented.
Rejected: treating unrecognized keys as auth errors (401); requiring a key for all calls.
Why: backward-compatible with existing no-auth tests and curl/SDK clients that don't send a key. The gateway is a cost-reduction and reliability proxy first; auth is per-key opt-in. `api_key_id=NULL` rows are still observable in the dashboard.

### cost_cents = 0 on cache hits
Decision: cache hits (exact or semantic) write `cost_cents=0` — the response was served without calling a provider.
Rejected: writing NULL for cache hits; omitting the cost column on hits.
Why: `0` is the accurate cost for a cached response. NULL would conflate "we don't know the cost" with "there was no cost". The dashboard computes cost saved by cache as the sum of `cost_cents` on rows where `cache_status = 'miss'` minus the (near-)zero cost on hits; a reliable zero makes that math clean.

### Latency measured wall-clock from pipeline entry; streaming latency = chain-resolution latency
Decision: `latency_ms = int((time.monotonic() - t0) * 1000)` where `t0` is set at the top of `proxy_chat_completion` / `stream_chat_completion`. For the streaming path, `t0` to chain resolution (pre-first-token) is written; the total stream duration is not persisted.
Rejected: measuring from the HTTP server (adds framework overhead noise); measuring end-to-end stream duration (requires holding state across the async generator, complicates the close-time update path).
Why: chain-resolution latency is the decision-quality metric — how long does the gateway take to pick a provider and start forwarding? Total stream duration is dominated by the provider's generation speed, which the gateway cannot control. Both are useful but chain-resolution latency is the gateway's own performance signal.
