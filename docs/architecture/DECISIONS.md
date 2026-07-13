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

## ADR-005 — jsonb round-trip via asyncpg codec, not per-call-site json.dumps/loads
Decision: register a `jsonb` codec (`encoder=json.dumps, decoder=json.loads`) in `_init_pool_conn` (`app/main.py`), alongside the existing pgvector codec.
Rejected: `json.dumps()` at `semantic.store()`'s call site + `json.loads()` at `semantic.lookup()`'s call site.
Why: asyncpg has no built-in `dict <-> jsonb` conversion, so `semantic.store()` was passing a raw dict into a jsonb bind parameter and raising `DataError` on every cache write — after billing had already completed (BLOCKER 3.4, always a 500 on cache miss). A pool-level codec keeps `lookup()`'s existing `cast(JSON, row["response_body"])` valid with no call-site changes, symmetric with how the vector codec is already handled. Also wrapped both `semantic.store()` call sites (streaming and non-streaming) in `try/except Exception: pass` — a cache write must never fail an already-billed client response, mirroring the existing guard around `semantic.embed()`.

## ADR-006 — semantic_cache.request_hash needs a UNIQUE index, not a plain btree
Decision: added migration `007_semantic_cache_unique_hash.sql` replacing the plain btree index from `004_semantic_cache_index.sql` with a unique one (de-duplicating existing rows first).
Rejected: leaving 004's index as-is.
Why: `store()`'s `ON CONFLICT (request_hash) DO NOTHING` requires a unique constraint/index on the conflict target — a non-unique btree doesn't satisfy that, so every `store()` call was raising `InvalidColumnReferenceError`, discovered while verifying the ADR-005 fix against a real Postgres. Without this, the ADR-005 try/except would have silently swallowed a 100%-failure-rate cache write instead of actually fixing caching.

## ADR-007 — strip `cache` (and other volatile keys) before forwarding upstream
Decision: filter `body` through the existing `cache.exact._VOLATILE_KEYS` set (`stream`, `stream_options`, `cache`) in `pipeline._candidate_setup` before assembling the outbound request, instead of spreading the raw caller body.
Rejected: leaving the OpenAI adapter's pass-through as the only line of defense.
Why: `_candidate_setup` built `out_body` via `{**body, "model": ...}`, forwarding the gateway-only `cache` control field verbatim to real providers (BLOCKER 3.5). The OpenAI adapter's `to_provider_request` is a pure identity pass-through, so this leaked as an unrecognized field on the wire; Anthropic's adapter happened to mask it by rebuilding the request field-by-field. Fixing the shared `_candidate_setup` choke point (used by both streaming and non-streaming attempts) closes the leak for both adapters rather than relying on one adapter's incidental behavior. Confirmed safe to also strip `stream`/`stream_options` here since `to_provider_stream_request` re-sets both unconditionally.

## ADR-008 — retired Anthropic seed models updated via a new migration, not an edit
Decision: `002_seed_providers.sql` / `003_routes.sql` seeded `claude-3-5-sonnet-latest` and `claude-3-5-haiku-latest`. Both are retired and 404 against the live Anthropic API. Added `008_update_anthropic_models.sql`, an `UPDATE` migration that repoints the existing rows' `alias`/`provider_model` to `claude-sonnet-5` and `claude-haiku-4-5-20251001` with current per-mtok pricing.
Rejected: editing 002/003 in place.
Why: applied migrations are immutable (db/CLAUDE.md) — history has to show what was actually seeded and when it was corrected. An `UPDATE` migration keeps that audit trail and is the same pattern 007 used for the `request_hash` index fix.

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

---

## Phase 5B — Dashboard: observability read API + Next.js UI

### Read-only APIRouter on the same FastAPI app, no new service
Decision: six `GET /v1/observability/*` endpoints live in `observability/api.py` and are mounted via `app.include_router(obs_router)` on the existing FastAPI app.
Rejected: a separate dashboard backend service; embedding the queries in the frontend via a Next.js API route.
Why: a second service (its own port, Docker container, deploy lifecycle) is overhead for pure read queries. Embedding DB logic in Next.js API routes couples the frontend directly to the DB, breaking the `requests` table as the single-source spine. Mounting on the existing app keeps the contract clear: everything the dashboard shows is derived from the `requests` spine the gateway already writes.

### Six focused query functions, raw asyncpg — no ORM abstraction
Decision: each endpoint has one SQL function in `queries.py` that returns raw `asyncpg.Record` objects, converted to Pydantic models in the endpoint handler.
Rejected: a generic query builder; wrapping in a repository class.
Why: the queries are each structurally distinct (aggregation, percentile, join-with-CTE, filter). A shared abstraction would either be parameterized to the point of illegibility or would just duplicate the SQL inside a wrapper. Raw asyncpg + explicit column access is readable, testable in isolation, and consistent with the rest of the gateway.

### `bucket` injected as an f-string literal, not a SQL parameter
Decision: `date_trunc('{bucket}', ...)` is built with a Python f-string after validating `bucket` against `frozenset({"hour", "day"})`.
Rejected: passing `bucket` as a `$N` parameter (Postgres does not support runtime identifiers as `date_trunc` granularity arguments).
Why: SQL does not support bind parameters for string-constant positions like `date_trunc`'s first argument. The allowlist validation before the f-string (`assert bucket in _BUCKETS`) is the safe equivalent of parameterization — the value is proven to be one of two known-safe literals before injection.

### CORSMiddleware with `allow_origins=["*"]` in dev
Decision: `CORSMiddleware` is added to the FastAPI app with `allow_origins=["*"]` so the browser dashboard on `:3000` can fetch the gateway on `:8000`.
Rejected: proxying gateway calls through the Next.js server (`/api/*` rewrites).
Why: a Next.js proxy adds a round-trip for every chart data fetch. The gateway read endpoints are unauthenticated read-only analytics — `allow_origins=["*"]` is appropriate scope. A production deploy (same origin or behind a reverse proxy) would restrict origins to the dashboard domain.

### Recharts v3 for the dashboard; no CSS framework
Decision: recharts AreaChart (spend), BarChart (latency), plain `<table>` for failovers and keys. Inline styles only.
Rejected: chart.js, d3, a CSS framework (Tailwind / MUI).
Why: recharts is the most widely-used declarative React chart library and ships good TypeScript types. A CSS framework is unnecessary scope for a single-page analytics dashboard. Inline styles keep the component files self-contained with no build configuration.

---

## Phase 5C — Benchmark harness

Four standalone asyncio scripts in `bench/` measure gateway overhead, cache hit rate,
failover reliability, and throughput saturation. All reports go to `bench/reports/`.

### Measured similarity threshold: superseded — see ADR below
The 0.92 placeholder discussed here has been measured and replaced. See "Semantic
cache similarity threshold — measured" below for the sweep, the chosen value, and a
false-positive finding that placeholder discussion didn't anticipate.

### Benchmark design decisions

#### asyncio.start_server mock provider instead of a real upstream
Decision: all four bench scripts use a minimal `asyncio.start_server` HTTP/1.1 mock that
returns a canned OpenAI response instantly (bench/_mock_server.py). Binds to 0.0.0.0 so
the Docker gateway can reach it via `host.docker.internal`.
Rejected: using a real provider (OpenAI/Anthropic) for the overhead and throughput benches;
using aiohttp or a third-party mock framework.
Why: real provider latency (50–500 ms) dominates and obscures the sub-millisecond gateway
overhead we want to measure. A canned response eliminates that noise. asyncio.start_server
is stdlib — no dependency. host.docker.internal is the idiomatic macOS bridge between
host-bound bench processes and Docker containers.

#### Sequential bench for overhead; semaphore-bounded gather for throughput
Decision: overhead.py uses 500 sequential requests; throughput.py sweeps concurrency levels
[1,2,5,10,20,40,60,100] with asyncio.Semaphore.
Rejected: using Locust (external dependency) or concurrent tasks for the overhead bench.
Why: overhead is an additive latency measurement — concurrent requests would conflate
gateway processing with scheduling artifacts. Sequential gives the cleanest p50/p95/p99.
Throughput needs concurrency to find the saturation point; the semaphore bound makes the
curve reproducible.

#### Hard-coded paraphrase corpus (not generated at runtime)
Decision: cache_bench.py embeds a 50-question × 3-variant corpus as a Python literal.
Rejected: generating paraphrases via an LLM at bench runtime.
Why: reproducibility. A runtime-generated corpus changes every run, making threshold
comparisons meaningless across runs. The hard-coded corpus is the reproducible ground truth.

#### Two bench modes for cache: gateway vs. similarity
Decision: `--mode=gateway` sends requests through the live gateway and reads `cache_status`
from the requests table. `--mode=similarity` calls the embedding API directly and computes
cosine similarities against multiple thresholds — no gateway needed.
Rejected: patching the gateway's `lru_cache`-backed settings for each threshold (invasive
and requires process restart); running a full docker-compose sweep per threshold (slow).
Why: the two modes test different things. Gateway mode validates that the configured
threshold produces the expected hit rate under a realistic corpus. Similarity mode
independently quantifies the threshold sensitivity curve without touching the gateway,
so you can pick a threshold and then validate it in gateway mode.

### Headline benchmark numbers
Run `python bench/overhead.py`, `bench/cache_bench.py`, `bench/failover_bench.py`,
and `bench/throughput.py` to populate these. Update this section with actual values.

- Gateway overhead: 2.3 ms p50, 2.8 ms p95 added latency over direct provider call (Apple M1 Pro; direct p50=0.6 ms, gateway p50=2.9 ms)
- Cache hit rate: 25.0% under the bench corpus at threshold 0.92 (50/200: 50 exact hits, 0 semantic hits — semantic cache skipped, OPENAI_API_KEY not set in bench run)
- Cost reduction: 25% of would-be spend avoided by exact-cache hits (50 of 200 requests served from Redis with cost_cents=0)
- Failover: 100% of requests succeed when primary provider returns 503; p50 gateway latency at depth=1 = 1 ms (FALLBACK_BACKOFF_BASE_MS=0; with default 500 ms backoff add ~500 ms per fallover depth)
- Throughput saturation: ~5 concurrent requests at peak linear efficiency; plateau at ~730 RPS (single uvicorn worker); latency p95 crosses 2× baseline at concurrency=10

## ADR: Semantic cache similarity threshold — measured (2026-07-13)

Decision: `SEMANTIC_SIMILARITY_THRESHOLD` changes from the 0.92 placeholder to **0.95**,
measured via `bench/cache_bench.py --mode=similarity` against a live OpenAI embedding
API (`text-embedding-3-small`).

### Methodology
Built a 160-pair hand-labeled eval set (`bench/data/similarity_eval.jsonl`) across 4
domains (customer support, coding Q&A, doc lookup, data queries), 3 classes per
domain: `true_duplicate` (paraphrase, a hit is correct), `near_miss_trap` (high
lexical overlap, different intent — e.g. differing order numbers, differing time
windows, differing numeric parameters — a hit is a wrong-answer bug), `unrelated`
(sanity floor). This is synthetic data, explicitly not captured production traffic.
Swept thresholds 0.80→0.99 (step 0.01); measured true-positive rate (duplicate pairs
correctly hit), trap false-positive rate (trap pairs wrongly hit), and unrelated hit
rate at each point. Full sweep table and root-cause analysis:
`bench/reports/bench-20260713-similarity-threshold.md`.

### Finding: no threshold in the swept range meets the ≤1% false-positive target
The selection rule (highest hit rate subject to trap FPR ≤ 1%) had no qualifying
threshold. The strictest true-duplicate pair scored 0.9425 cosine similarity; a
near-miss trap ("How do I track order #4521?" vs "…#4522?") scored 0.9925 — higher
than every true duplicate in the set. A trap that out-scores the closest duplicate
cannot be excluded by any global threshold while keeping that duplicate — this is a
structural limit of cosine-similarity thresholding on numeric/ID-bearing near-misses,
not a tuning problem. Above 0.95, trap FPR plateaus at a floor of 1.7% (one
unresolvable pair) while true-positive rate drops to 0%; raising the threshold
further buys no additional safety and only destroys recall.

### Decision
Ship **0.95** — the lowest threshold that reaches the measured trap-FPR floor, i.e.
the safest available single-threshold setting on this eval set, not a passing result
against the ≤1% target. On this eval set its true-positive rate is 0%, so the
semantic cache should be expected to contribute near-zero hit rate until the
underlying gap is closed. This is the conservative, correctness-first choice
mandated for this cache: wrong answers are a correctness bug, so hit rate is
sacrificed rather than risk serving a wrong answer for a numeric-ID mismatch.

Rejected: keeping 0.92 (measured trap FPR 8.3% — an order of magnitude over target);
picking any threshold in 0.80–0.94 for a higher illustrative hit rate (all such
points have trap FPR well above 1%).

### Follow-up (not implemented in this step)
Closing the gap requires a non-similarity guard — e.g. extracting numeric
literals/IDs from both requests and bypassing the cache when they differ — added
alongside the existing bypass guardrails in `gateway/cache/guardrails.py`. Out of
scope here: this step measures the threshold, it does not change cache lookup logic.

### Limitation
Validated on synthetic, hand-labeled pairs; real traffic may have a different domain
mix and adversarial density. `SEMANTIC_SIMILARITY_THRESHOLD` stays a per-deployment
config value for this reason — re-run the sweep against real (anonymized) query
pairs once available.

---

## Benchmark harness reproducibility fix (2026-07-13)

### Problem
The README's committed overhead/throughput numbers (2.3 ms p50 overhead, ~730 RPS
peak) came from a single un-repeated run of `bench/overhead.py` /
`bench/throughput.py`. An independent verification run reproduced 2-4x worse.
Root cause was not gateway performance but the harness: no recorded run
configuration (worker count, connection-pool limits, host specs), a thin warmup
(10 requests), and a single sample with no variance reported — nothing distinguished
a real regression from ordinary noise.

### Decision
Fixed the harness rather than re-tuning the gateway:
- Warmup increased to 50 requests, run per-trial (not once for the whole script).
- Every measurement now repeats 3 trials within a run, reporting mean + stdev.
- Gateway worker count is pinned via `GATEWAY_WORKERS` (default 1, set in
  `infra/docker-compose.yml` and read by `gateway/Dockerfile`'s uvicorn invocation)
  instead of relying on uvicorn's undocumented default.
- httpx connection-pool limits used by `throughput.py` are named constants, recorded
  in the report instead of being an invisible implicit config.
- `bench/_config.py` gathers host CPU/RAM/OS/package-version/trial-size info at
  runtime and every report embeds it, so a report is self-documenting: a reader
  doesn't need this file open to know what conditions produced a number.
- `bench/README.md` added as the reproduction one-pager (exact commands, what
  "reproducible" means here, known sources of variance on a dev laptop).

Verified: 3 consecutive full runs each of `overhead.py` and `throughput.py` on the
same dev laptop, mean p50 overhead 3.41 / 3.44 / 3.89 ms (14% spread) and peak RPS
601 / 666 / 634 (11% spread) — both within the ~15% reproducibility bar. Reports in
`bench/reports/bench-20260713-*-overhead.md` and `-throughput.md`.

### Rejected
Tuning the gateway itself to produce better-looking numbers — out of scope for a
measurement-fidelity fix, and would have hidden the real question (was the harness
trustworthy?) behind a coincidentally-nicer number.

### Limitation
These are dev-laptop numbers, not the deployed reference instance. The main README
carries an explicit interim note; FINAL numbers are still pending a re-measurement
on the deployed Fly instance, which removes dev-laptop background-load noise as a
variance source.

---

## Phase 6 — Fly.io deployment, budget-capped demo key (2026-07-13)

### Demo/bench keys seeded via a new migration, not an admin endpoint
Decision: `009_seed_demo_keys.sql` inserts `demo-key` ($10 hard cap) and `bench-key`
($25 hard cap) the same way `005_seed_api_key.sql` seeds `dev-key` — raw value in a
comment, `encode(sha256(...), 'hex')`, `ON CONFLICT (key_hash) DO NOTHING`.
Rejected: building an admin endpoint/CLI to create API keys.
Why: two keys, known in advance, needed once at deploy time — an admin surface
(auth, validation, docs) is unjustified scope for that. A migration is append-only,
auditable, and matches the existing `dev-key` precedent exactly. If key creation
becomes a recurring operational need, that's the trigger to build the endpoint.

### Benchmark methodology: SSH into the Fly VM and run the existing harness unmodified
Decision: uploaded `bench/overhead.py`, `throughput.py`, `failover_bench.py` and
their shared helpers to the live machine via `fly ssh sftp put`, and ran them via
`fly ssh console -C "..."` against the gateway process already listening on
`localhost:8000` there — the same process real traffic hits.
Rejected: adding a `--base-url` flag to run the scripts from a laptop against the
public URL; skipping re-benchmarking and keeping the dev-laptop numbers as final.
Why: a `--base-url` variant changes the scripts (more surface to keep in sync with
`bench/README.md`'s documented local-only design) and would need real provider
calls or a publicly reachable mock, both worse than the existing mocked-provider
methodology. Running the *existing* harness unmodified, in-process on the VM,
required no code changes and produced numbers from the actual deployed
hardware/network path. Cost: real environmental gaps to solve (no
`host.docker.internal` DNS on a bare Firecracker VM, `BENCH_MOCK_KEY` missing from
the live process's env since it's a compose-only var, and Fly's autostop killing
the machine mid-run because loopback-only bench traffic is invisible to the
edge-proxy connection count that autostop watches) — each is now documented as a
Troubleshooting row in `gateway/DEPLOY.md`.

### `cache_bench.py --mode=gateway` is unsafe against the live instance — skip it, don't adapt it
Decision: did not re-measure cache hit rate on the deployed instance. The
dev-laptop figure (25.0%, from Phase 5C) stands as the correctness benchmark.
Rejected: running `cache_bench.py --mode=gateway` against `conductor-demo` anyway;
patching it to skip the reset step for a "safer" partial run.
Why: that script calls `redis.flushdb()` (wipes the entire Redis DB) and an
unscoped `DELETE FROM semantic_cache` to guarantee a clean slate — correct for a
disposable local stack, destructive against a shared live one. Budget counters
(`budget:{api_key_id}:{YYYY-MM}`) live in the same Redis keyspace, so a flush would
also reset `demo-key`'s and `bench-key`'s spend to zero — an unrelated feature
(budget enforcement) silently corrupted by a benchmark run. Patching the script to
avoid the reset would measure a different, uncontrolled cache state, not a
comparable number. Skipping it and documenting why (both in `gateway/DEPLOY.md` and
the README's Benchmark Results section) is more honest than a number that isn't
actually comparable to the 0.92-placeholder-era measurement.

### Fly secrets set is atomic per-invocation; export and set must happen in one shell call
Decision: `DATABASE_URL`/`REDIS_URL`/`OPENAI_API_KEY`/`ANTHROPIC_API_KEY` are all
exported and passed to a single `fly secrets set` command in one shell invocation.
Rejected: exporting variables in one command/session and referencing them in a
later, separate one (as happens naturally when an agent or script runs each line
as its own subprocess).
Why: discovered the hard way — a split invocation sends `fly secrets set` empty
strings for every secret, which succeeds silently (no error) and only surfaces
later as a crash-loop against `127.0.0.1:5432` (the pydantic-settings default) once
the machine tries to boot against a DB that isn't configured. `fly secrets list`
showing identical digests for `DATABASE_URL` and `REDIS_URL` (both hashing to the
same empty value) was the actual tell. Documented as the first Troubleshooting row
in `gateway/DEPLOY.md` since it's the failure mode most likely to recur for anyone
following the runbook with tooling that splits commands across processes.
