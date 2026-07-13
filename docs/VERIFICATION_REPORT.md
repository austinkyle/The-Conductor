# LLM Gateway — Adversarial Verification Report

**Date:** 2026-06-25
**Method:** Live end-to-end verification against the running stack (Docker compose: Postgres+pgvector, Redis, gateway), real OpenAI + Anthropic keys (minimal spend; keys masked everywhere, never logged). Nothing is marked PASS without a command run and an observed result.
**Scope:** Sections 1–7 of the verification plan. Repo root is the **inner** `llm-gateway/` (where `.git` lives); the project is nested one level under the launch dir.

---

## Verdict at a glance

| Severity | Count | Headline |
|---|---|---|
| **[BLOCKER]** | 5 | Semantic cache crashes live traffic; dead live demo + broken quickstart; non-functional CI; broken self-host command; `cache` control field 400s the provider |
| **[SHOULD-FIX]** | 4 | Retired Anthropic seed models (Anthropic routing 404s end-to-end); CI never exercises DB; bench numbers ~2–4× optimistic; `pipeline.py` duplication |
| **[POLISH]** | 6 | guardrail reason collapse; fabricated hash comment; misleading `record_spend` comment; Next.js advisories; `assert`-based allowlist; cosmetic stream-close |

The architecture, documentation, type-discipline, and test design are genuinely senior-grade. The **runtime correctness of the cache layer and the deployability of the project are not.** The single most damning fact: with the *documented, intended* configuration (a valid `OPENAI_API_KEY`), **a normal cache-miss chat request returns HTTP 500 after the upstream provider has already been called and billed.** This ships because every safety net the author built (unit tests with fakes, the benchmark "semantic skipped", a CI that never runs) structurally cannot see it.

---

## Section 1 — Cold-start / stranger test

| Check | Result | Evidence |
|---|---|---|
| Stack boots via compose | **PASS** | `docker compose -f infra/docker-compose.yml up -d --build` → all 3 services healthy; gateway log `no pending migrations` / `Uvicorn running`. |
| `/health` 200 only when DB+Redis up | **PASS** | Up: `200 {"status":"ok","db":true,"redis":true}`. After `docker stop infra-redis-1`: `503 {"status":"unhealthy","db":true,"redis":false}`; recovers on restart. |
| Quickstart logic | **PASS (against localhost)** | `OpenAI(base_url="http://localhost:8000/v1", api_key="dev-key")` → `gpt-4o-mini` returns `pong`, usage populated. The proxy itself works. |
| Required-env vs `.env.example` | **PASS** | `core/config.py` requires exactly 4 (`openai_api_key`, `anthropic_api_key`, `database_url`, `redis_url`); all 4 documented in `.env.example`. No undocumented required var. |

### [BLOCKER] 1.1 — Live demo is dead, and the headline Quickstart points at it
The README Quickstart's first line is `base_url="https://llm-gateway-demo.fly.dev/v1"`, and the "Live Demo" section links the same host.
- `nslookup llm-gateway-demo.fly.dev 1.1.1.1` → **NXDOMAIN**; `8.8.8.8` → **NXDOMAIN**; `fly.dev` itself resolves fine. The host does not exist.
- A reader copy-pasting the headline Quickstart gets a DNS failure. The README's central promise ("One changed line. Same SDK. Done.") is verbatim-broken. `gateway/fly.toml` + `DEPLOY.md` are a real runbook, but nothing is deployed.

### [BLOCKER] 1.2 — Self-host command fails from the repo root
README Self-Host: `docker compose -f llm-gateway/infra/docker-compose.yml up`.
- From the repo root a cloner lands in (`git rev-parse --show-toplevel` = the inner `llm-gateway/`), the path resolves to `llm-gateway/llm-gateway/infra/...` which does not exist. `docker compose -f llm-gateway/infra/docker-compose.yml config` → **FAILS**.
- It only works if you stand in the *parent* of a directory literally named `llm-gateway/` — an artifact of this nested layout, not what `git clone && cd` produces. Correct path is `infra/docker-compose.yml` (verified working).

> 1.1, 1.2 and the CI breakage (2.x) share one root cause: paths were written assuming an **outer `llm-gateway/` wrapper directory** that is not part of the committed repo (`git ls-files` shows top-level `gateway/ dashboard/ infra/ …`, no `llm-gateway/` prefix).

---

## Section 2 — Tests, types, CI

| Check | Result | Evidence |
|---|---|---|
| `pytest` (local, real env) | **PASS** | `85 passed in 0.51s`. |
| `pytest` (CI's fake env) | **PASS w/ caveat** | `OPENAI_API_KEY=sk-test … DATABASE_URL=postgresql://localhost/test` → `84 passed, 1 skipped`. The skip is `test_migrate.py` (skips when Postgres unavailable). |
| `mypy` (strict) | **PASS** | `Success: no issues found in 40 source files`. Genuine — strict mode, no blanket ignores. |
| Dashboard `tsc --noEmit` | **PASS** | `npm ci && npm run type-check` → rc=0. |
| Coverage on the judgment seams | **PASS (not glue)** | `test_routing.py` drives the real `proxy_chat_completion` via `httpx.MockTransport`: 503→failover depth=1, 400→non-cascade (provider B never contacted), chain exhaustion, backoff timing. `test_translation.py` round-trips both directions incl. system-hoist/`max_tokens`/`stop_reason`. `test_cache.py` exhausts every guardrail branch + exact/semantic/replay. |

### [BLOCKER] 2.1 — CI is non-functional (and was never even committed)
Two layers of broken:
1. `.github/` is **untracked** (`git status` → `?? .github/`; `git ls-files` shows only `infra/docker-compose.yml` under config). The workflow has never been part of the repo, so it has never run on GitHub at all.
2. Even as written, `.github/workflows/ci.yml` sets `working-directory: llm-gateway/gateway` (gateway job), `working-directory: llm-gateway/dashboard` + `cache-dependency-path: llm-gateway/dashboard/package-lock.json` (dashboard job). On checkout, `GITHUB_WORKSPACE` is the repo root = the inner `llm-gateway/`, whose children are `gateway/`, `dashboard/`, … There is **no `llm-gateway/` subdirectory**. Both jobs would fail at the first `run` step ("working-directory does not exist") before any test or type-check executes. The green-CI signal does not exist.

### [SHOULD-FIX] 2.2 — Even with paths fixed, CI never exercises the DB
CI provides `DATABASE_URL=postgresql://localhost/test` with **no Postgres service** in the workflow. The only DB-touching test (`test_migrate.py`) `pytest.skip("postgres unavailable")`s, and every other test uses in-memory fakes. So migrations, real asyncpg type behavior, and the SQL in `queries.py`/`semantic.py` are never run in CI. This is precisely the blind spot that hid BLOCKER 3.4 (see below): asyncpg's runtime jsonb strictness is invisible to the fake-backed suite.

---

## Section 3 — The four judgment seams (live, real requests)

### 3a — Translation — **PASS (both providers)**
- **OpenAI** (`gpt-4o-mini`), system + 4-turn conversation → `chat.completion`, content `"20"` (correct), `finish_reason="stop"`, usage populated.
- **Anthropic**: the seeded model 404s (see SHOULD-FIX 3.5), so I proved the seam via a temporary alias → `claude-haiku-4-5`. Result: OpenAI-shaped `chat.completion`, content `"20"` (system prompt honored = hoisted to top-level `system`; multi-turn preserved), `finish_reason="stop"`, usage mapped (`input_tokens`→`prompt_tokens=40`, `output_tokens`→`completion_tokens=5`). All three documented Anthropic diffs (message structure, top-level system, response/usage shape) handled correctly. Temp alias removed.

### 3b — Streaming — **PASS (both providers)**
- **OpenAI** live SSE: role-delta → content deltas → `finish_reason:"stop"` → terminal `choices:[],usage{…}` chunk → `data: [DONE]`. DB row reconciled `prompt_tokens=20, completion_tokens=6, total_tokens=26` matching the usage chunk.
- **Anthropic** live SSE (via temp alias): synthesized OpenAI chunks in the same sequence; every frame is `chat.completion.chunk`; DB reconciled `20/119/139` matching the synthesized usage chunk (`input_tokens` from `message_start`, `output_tokens` from `message_delta` folded at `message_stop`).
- **Synthetic stream on cache hit**: identical streaming request after caching → `exact_hit`, served as `id:"cached"` role/content/finish/usage chunks + `[DONE]`, cost 0. Shape matches live.

### 3c — Routing / failover — **PASS**
- **Transparent failover (live):** temp chain `failtest` = dead provider `http://127.0.0.1:9` (connection refused, retryable) at priority 0 → real OpenAI at priority 1. Request → **HTTP 200 served by OpenAI, `fallback_depth=1`**, `served_provider_id=1`.
- **Backoff is real:** failover elapsed 1259ms vs ~700ms direct; the ~500ms delta is `_backoff(0)` (`FALLBACK_BACKOFF_BASE_MS=500`). Independently reconfirmed by `failover_bench` showing depth=1 p50=515ms. Not a no-op.
- **Terminal fail-fast (live):** temp chain with a bogus primary model (OpenAI 404 = `client_error`, terminal) ahead of a valid secondary → **HTTP 404, `fallback_depth=0`, `status=error`**, secondary never tried. 4xx does not cascade.
- **No mid-stream failover:** confirmed by code — `_stream_attempt` peeks status only at stream open (`pipeline.py:175`); the returned `forward()` generator is consumed by `async for chunk in gen` with no surrounding retry, so a mid-stream upstream death surfaces as a broken stream, not a silent retry. Matches ADR-002.

### 3d — Cache + guardrails — **MIXED; one BLOCKER, one BLOCKER**
- **Exact cache — PASS:** identical request → 1st 1629ms `miss`, 2nd 5.5ms `exact_hit`, `cost_cents=0`.
- **Guardrails (temperature, tool_use) — PASS:** both repeats slow + 200 → bypass both layers (and return 200 because bypass skips the broken `store`, see below).

#### [BLOCKER] 3.4 — Semantic cache crashes the request and never stores anything
`cache/semantic.py:116` passes a Python `dict` as the `jsonb` `$3` parameter to asyncpg, which has no dict→jsonb codec registered. Three independent proofs:
1. **Live:** a fresh, uncached, non-bypassed request → **HTTP 500**, while the request row is written `status=success, cost_cents=0.0004` (provider called + billed) — the 500 comes from `store()` *after* the row insert and `record_spend`.
2. **In-container repro:** `INSERT INTO semantic_cache … $3=dict` → `asyncpg.exceptions.DataError: invalid input for query argument $3 … (expected str, got dict)`.
3. **Logs:** real request `chatcmpl-…` traceback ending at `cache/semantic.py:116`.

Consequences:
- `semantic_cache` count stays **0** after any number of seed requests → a `semantic_hit` is **impossible**; the HNSW index (real, verified) sits on a permanently empty table.
- `store()` is **not** wrapped in try/except in `pipeline.py` (only `embed()` is). So whenever the embedding API is reachable (the default compose config sets `EMBEDDING_MODEL`), **every cache-miss non-streaming request 500s after paying the provider.** Streaming misses don't 500 the client (store runs post-`[DONE]`), but still error server-side and never cache.
- **The project's own cache benchmark cannot run against a correctly-configured gateway:** `python bench/cache_bench.py --mode=gateway` → `httpx.HTTPStatusError: 500` on the first request. The committed "25% hit rate" report was only obtainable by running with a non-working embedding key so `embed()` fails and `store()` is skipped.
- Invisible to tests: `_FakeConn.execute` just appends args; it never exercises asyncpg's jsonb encoding. Combined with the dead CI (2.1) and the bench's "semantic skipped", nothing in the author's workflow ever hit this.

*Fix:* register a jsonb codec on pool init (`set_type_codec('jsonb', encoder=json.dumps, decoder=json.loads)` in `app/main.py:_init_pool_conn`) — fixes both the store encode and the latent lookup decode (`lookup` currently `cast`s a jsonb column to `JSON`/dict, which without a codec would return a `str`). **Behavioral change → listed for review, not silently applied.**

#### [BLOCKER] 3.5 — `cache` control field is leaked upstream → 400 for two of four guardrails
The outbound provider body is `{**body, "model": …}` (`pipeline.py:104`), built from the raw request — `exact.normalize` strips `cache`/`stream`/`stream_options` only for the *hash*, not for the upstream call. So:
- `cache:{no_cache:true}` and `cache:{recent_context:true}` (and `cache:false`) → the `cache` field is forwarded to OpenAI → **HTTP 400 "Unrecognized request argument supplied: cache"** (verified live, rows `client_error`). The bypass "works" (cache skipped) but the request then fails.
- Two of the four documented caller-facing guardrails are therefore **unusable against a real provider.** The bench only tolerates `cache:{no_cache:true}` because the mock ignores unknown fields.

*Fix:* strip control-only keys (`cache`) from the outbound body. **Behavioral → listed for review.**

---

## Section 4 — Budgets + secrets hygiene

| Check | Result | Evidence |
|---|---|---|
| Hard limit blocks **before** forwarding | **PASS** | Set `budget:1:2026-06=100.0000` (= hard 100¢) → **HTTP 402**, `requests` row count unchanged (137→137): no row, no upstream call. `check_budget` runs before `walk_chain` (`pipeline.py:207`). |
| Soft limit warns but serves | **PASS** | Set counter `50.0000` (≥ soft 10¢, < hard 100¢) → **HTTP 200** + log `soft budget warning for key 1 (dev-key): spent 50.0000 of 10 cents`. |
| Cost math by hand | **PASS** | gpt-4o-mini (0.15/0.60 per Mtok), prompt 20 + completion 6 → `(20·0.15 + 6·0.60)/1e6·100 = 0.00066 → 0.0007¢` = observed row. Anthropic row `(20·1 + 119·5)/1e6·100 = 0.0615¢` = observed. |
| Keys hashed; provider secrets by reference | **PASS** | `api_keys.key_hash` = `sha256` (auth.py + migration 005); `providers.auth_ref` names the env var only. No secret in DB rows, migrations, code, logs, or URL query params (`grep` clean). |
| `.env` gitignored / no `sk-` in history | **PASS** | `.env` untracked; full-history `sk-(proj-\|ant-)` scan clean; live key fragments not present in any tracked blob. Only `sk-` match is DEPLOY.md's intentional `sk-ant-placeholder`. |

### [POLISH] 4.1 — Fabricated hash in a comment
Migration 005 comment claims `sha256("dev-key") = a97e1c95…`. Actual (Python + DB) = `7e9f8fd111802be…`. The code is correct (`encode(sha256('dev-key'::bytea),'hex')`); the comment value is invented and does not compute — a small "looks-done" tell.

### [POLISH] 4.2 — `record_spend` comment contradicts code
The comment says TTL is set "on first write only" / "nx=True", but `r.expire(key, _TTL_SECONDS)` runs unconditionally on every spend (no `nx`). Harmless (rolling 35-day TTL) but the comment is wrong.

---

## Section 5 — Benchmarks

| Metric | README / committed | Reproduced (this run) | Result |
|---|---|---|---|
| Overhead p50/p95/p99 (ms) | 2.3 / 2.8 / 3.1 | **4.5–4.7 / 10.8–11.4 / 14.5–14.8** (two runs) | **[SHOULD-FIX]** ~2× p50, ~4× tail |
| Failover success | 100% (200/200, depth=1) | **100% (200/200, depth=1)** | **PASS** |
| Throughput peak | ~730 RPS | **~435 RPS** (peak at concurrency 10) | **[SHOULD-FIX]** ~60% |
| Methodology stated | required | present in every report (hardware, load pattern, provider mix) | **PASS** |

- Overhead is reported honestly as added latency vs. a direct provider call, with p50/p95/p99 — methodology is sound. But the committed figures are the rosy end; on the same hardware class (auto-detected M1 Pro) they reproduce ~2–4× worse and consistently so. A senior reader would read 2.3ms p50 as a quiet-machine best case, not a typical number.
- The "25% cache hit rate" report is only producible in the degraded config that dodges BLOCKER 3.4 (semantic disabled). `semantic_hit` is structurally 0.

---

## Section 6 — Docs vs. reality (ADRs)

| ADR | Claim | Reality | Result |
|---|---|---|---|
| 001 | OpenAI-shape contract, per-provider adapter | `openai.py` identity; `anthropic.py` real translation; pipeline never branches on provider (dict dispatch) | **PASS** |
| 002 | Cache after stream close; failover only pre-first-token | Write-at-`[DONE]`; status peek at stream open; no mid-stream retry | **PASS** |
| 003 | pgvector, HNSW cosine, `vector(1536)` | `idx_semantic_cache_embedding … USING hnsw (embedding vector_cosine_ops)` on `vector(1536)` — **verified live** | **PASS (schema)** — but the table is permanently empty (BLOCKER 3.4), so the layer is dead in practice |
| 004 | FastAPI async, no sync blocking in hot path | No `time.sleep`/sync `requests`/blocking I/O in `app/core/routing/cache/translation/budgets/observability`; httpx-async + asyncpg + redis.asyncio throughout. Only sync `read_text()` is the startup migration runner | **PASS** |

- README has all six sections; each ADR names a rejected alternative + why; the mermaid diagram matches the real structure. `DECISIONS.md` is genuinely strong — phase-by-phase decisions with rejected alternatives and rationale (the clearest seniority signal in the repo).
- **Live demo does not resolve** (BLOCKER 1.1) — the one ADR-adjacent claim that fails outright.

---

## Section 7 — Scope + human-code audit

- **Scope discipline: PASS.** Exactly two providers (`openai`, `anthropic`) and five tables (`api_keys`, `providers`, `models`, `requests`, `semantic_cache`). "Future Work / Out of Scope" names deliberate exclusions (mid-stream failover, third provider, threshold validation, dashboard auth, horizontal scale).
- **No AI-slop architecture.** Functions over classes; the only ABC (`Adapter`) has two real impls and is a pre-justified seam; provider dispatch is a plain dict; no factory/manager/registry; no speculative config flags; comments explain *why*, not *what*. mypy-strict clean. This reads as reasoned, not lifted.
- **SQL injection check:** `observability/queries.py` builds `date_trunc('{bucket}', …)` via f-string but guards with `assert bucket in _BUCKETS` (allowlist of two identifiers); `window` is a bound `$1` interval. Safe. ([POLISH]: relying on `assert` for a safety boundary is stripped under `python -O`; prefer an explicit check.)

### [SHOULD-FIX] 7.1 — `pipeline.py` is 495 lines and duplicates the cache path
The file is 3× the project's own ~150-line guideline. `proxy_chat_completion` and `stream_chat_completion` duplicate the entire exact+semantic cache-check-and-hit-insert block nearly verbatim (~lines 213–269 vs 359–419). This is why BLOCKER 3.4 exists *identically in both branches* — a single `_check_cache` helper would have localized it. The clearest extract-method opportunity in the codebase.

### [SHOULD-FIX] 3.5b (data) — Seeded Anthropic models are retired
Seed migration 002 routes `claude-3-5-sonnet-latest`; migration 003 adds `claude-3-5-haiku-latest`. Against the provided Anthropic key, **all `claude-3-5-*` names → 404 not_found** (only `claude-sonnet-4-5` / `claude-haiku-4-5` resolve). So with shipped seed data, any request routed to Anthropic 404s end-to-end, and the `smart` alias (Anthropic primary) 404s *terminally* — by design it will **not** fall back to its OpenAI secondary (4xx is terminal). The translation seam is correct; the seed data has bit-rotted.

### [POLISH] 7.2 — guardrail reason collapse
`recent_context` and the `no_cache` flag both return the reason string `"no_cache"` (`guardrails.py:27`) — four documented conditions, three labels. Moot in practice because the pipeline uses `should_bypass` only as a truthy gate; the reason string is **never persisted** (a bypassed request is recorded as `cache_status="miss"`, indistinguishable from a real miss). Documented "four distinct guardrails" overstates what is observable.

### [POLISH] 7.3 — Dashboard dependency advisories
`npm audit`: Next.js 14.2 carries multiple **high**-severity advisories (DoS / cache-poisoning / request-smuggling). Pin/upgrade before any real deploy.

---

## What's genuinely good (so the verdict is fair)

- `mypy --strict` clean across 40 files; 85 meaningful unit tests that actually drive the pipeline (failover, non-cascade, translation round-trips, guardrail matrix).
- Translation, streaming, failover, budgets, exact cache, and secrets hygiene all verified correct end-to-end with live providers.
- `DECISIONS.md` and the per-module `CLAUDE.md` routing tables are excellent; ADRs are real arguments with rejected alternatives.
- Lean, async, idiomatic code with no speculative abstraction.

---

## Seniority verdict (blunt)

Would a senior engineer conclude the author is a forward-deployed-level engineer? **On the writing — design notes, ADRs, type discipline, test *design*, scope control — yes, clearly.** On the *shipping*, no — and this is where they'd get suspicious fast. The first real-world action a reviewer takes is "clone it and run the quickstart": the demo URL is NXDOMAIN, the self-host command's path is wrong from the repo root, and CI has never been green because its working directory doesn't exist — three faces of the same uncommitted-wrapper-directory mistake, which means **the author never actually ran their own published instructions from a clean checkout.** The deeper tell is the cache layer: configure the gateway exactly as documented (valid OpenAI key) and a plain cache-miss returns 500 *after billing the provider*, because `store()` hands asyncpg a dict for a jsonb column — and the semantic cache has never stored a single row. That defect is real-senior-grade *hidden*: it survives only because the unit tests fake the DB, CI never touches a DB, and the benchmark conveniently runs with embeddings disabled. The author built a beautiful map of the territory and a test suite shaped like rigor, but the suite is built to pass rather than to catch, and the headline feature was never exercised against a real database. A senior reviewer would trust this person to *design* the system and would not trust this build to run in production without the cache layer, the deploy path, and CI being made real.

---

## Fixes applied (safe / non-behavioral only)

Scope chosen: **safe fixes only, then stop.** No behavioral, architectural, or documented-tradeoff change was made. The working tree was already carrying a large **uncommitted/untracked delta authored by the build** (the committed `README.md` is still a placeholder; the full README, the `.github/` workflow, and several `tests/*.py` updates were never committed). To avoid bundling or misattributing that work, only the two fixes that touch files clean at HEAD were committed; the rest were applied to the working tree and left for the author to commit alongside their own pending changes.

**Committed** (branch `verify/safe-fixes`, two separate commits):
- `docs(db)`: corrected the fabricated `sha256("dev-key")` value in migration 005's comment → `7e9f8fd1…` (POLISH 4.1).
- `docs(budgets)`: fixed the misleading TTL comment in `record_spend` (POLISH 4.2).

**Applied to working tree, intentionally not committed** (entangled with the author's uncommitted README rewrite / untracked `.github/`):
- `.github/workflows/ci.yml`: `working-directory` `llm-gateway/gateway`→`gateway`, `llm-gateway/dashboard`→`dashboard`, and the matching `cache-dependency-path` (BLOCKER 2.1, path layer only — the file still needs to be **committed/tracked** to exist as CI at all).
- `README.md` Quickstart `base_url` → `http://localhost:8000/v1`; Self-Host command → `infra/docker-compose.yml`; "Live Demo" section reworded to state no hosted instance is running and point at self-host / `DEPLOY.md` (BLOCKERs 1.1, 1.2).

**Re-verified after fixes:** `docker compose -f infra/docker-compose.yml config` resolves from repo root; ci.yml paths (`gateway`, `dashboard`, `dashboard/package-lock.json`) all exist; localhost quickstart returns 200; `pytest` 85 passed; `mypy --strict` clean.

**NOT fixed — left for review (behavioral / data; per fix protocol, STOP):**
- BLOCKER 3.4 — semantic `store()` jsonb crash (needs a jsonb codec on pool init; changes runtime behavior — fresh misses currently 500).
- BLOCKER 3.5 — `cache` control field leaked upstream (needs stripping it from the outbound body; changes what is sent to providers).
- SHOULD-FIX 3.5b — retired Anthropic seed models (needs a new seed migration choosing current model names — a product/data decision tied to the deploying account's model access).

---

## Appendix — environment & hygiene
- Stack: `infra-postgres-1` (pgvector/pg16), `infra-redis-1`, `infra-gateway-1` (built locally). Brought up with the corrected `infra/docker-compose.yml` path.
- Real OpenAI (len 164) + Anthropic (len 108) keys used for live calls; **masked everywhere, never echoed**. Total spend: a few dozen tiny chat/embedding calls.
- Caches were flushed (`redis FLUSHALL`, `truncate semantic_cache`) mid-run to remove a prior session's entries that initially polluted exact/semantic results; all reported cache results are post-flush.
- Temp routing rows (`anthropic-test`, `failtest`, `termtest`, `deadprovider`) were created for live seam tests and **deleted** afterward.
