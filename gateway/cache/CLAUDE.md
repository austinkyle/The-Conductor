# cache/ — exact (Redis) + semantic (pgvector) + guardrails

## Routing table
| Task type | READ | SKIP | Tools / Skills |
|---|---|---|---|
| Exact-match cache | cache/exact.py (Redis) | routing/, dashboard/ | — |
| Semantic cache | cache/semantic.py, gateway/db (semantic_cache table) | budgets/ | pgvector |
| No-cache guardrails | cache/guardrails.py | translation/ | — |
| Synthetic stream replay | cache/replay.py | routing/, translation/ | — |

## Invariants (the correctness signal — get these right)
- Embed the LAST user message + a lightweight hash/summary of prior context, NOT the whole history. Make it configurable; document why.
- BYPASS cache when: temperature above threshold, `no-cache` flag set, tool-use request, very recent context. A semantic cache that ignores temperature is a correctness bug.
- Cache AFTER a stream completes; serve hits as a synthetic stream.
- Similarity threshold is empirical — justify it with measured data from bench/, not a magic number.
- Write `cache_status` (miss / exact_hit / semantic_hit / one of the four bypass reasons) to every request row — bypasses are distinguishable from genuine misses, not collapsed into `"miss"`.

## As built (Phase 4)

### Module layout
| File | Owns |
|---|---|
| `guardrails.py` | `should_bypass(body, *, temperature_bypass) -> str \| None` — pure, no I/O. Returns a distinct reason per condition (`"temperature"`, `"no_cache"`, `"recent_context"`, `"tool_use"`) — never collapsed. |
| `exact.py` | `normalize`, `request_hash`, `get`, `put` — Redis SHA-256 exact match |
| `semantic.py` | `embed_text`, `embed`, `lookup`, `store` — pgvector ANN search |
| `replay.py` | `synthetic_stream`, `assembled_to_response` — SSE replay for cache hits |

### Bypass guardrails
Four conditions trigger bypass (checked in order):
1. `temperature > semantic_temperature_bypass` (default 0.3)
2. `body["cache"] is False` or `body["cache"]["no_cache"]`
3. `body["cache"]["recent_context"]` — caller-signaled recency flag (gateway is stateless, so the caller knows whether its session is too fresh for a cached reply)
4. Non-empty `tools`, `functions`, or a non-"none" `tool_choice`

### Embed strategy: `last_plus_digest`
`embed_text` takes the **last** user message and prefixes it with the first 8 hex chars of SHA-256 over all **prior** turns. This scopes the embedding to the conversation context without embedding the full history, avoids embedding-length limits, and keeps stored vectors small.

### Exact cache (Redis)
- Key: SHA-256 of normalized body (volatile keys `stream`, `stream_options`, `cache` stripped)
- Value: JSON response body stored as UTF-8 string
- TTL: `exact_cache_ttl_seconds` (default 3600 s)

### Semantic cache (pgvector)
- Table: `semantic_cache` — `request_hash text`, `embedding vector(1536)`, `response_body jsonb`, `model text`
- HNSW cosine index on `embedding` (migration 004)
- Lookup: cosine similarity `1 - (embedding <=> $1)` ≥ `semantic_similarity_threshold` (default 0.95, measured — see Threshold note below)
- Store: `ON CONFLICT (request_hash) DO NOTHING` — concurrent duplicates are harmless

### Write-at-close for streaming
Cache is written AFTER the `async for chunk in gen:` loop in `stream_chat_completion` exhausts the generator, at which point `req.assembled_content` and `req.usage` are set by the SSE engine. Client disconnect (`GeneratorExit`) skips the post-loop block so incomplete streams are never cached.

### Synthetic stream replay
Cache hits are served as a synthetic `chat.completion.chunk` SSE sequence matching the live shape:
`role-delta → content-delta → finish → usage → [DONE]`

### pgvector pool init
`app/main.py` registers the pgvector asyncpg codec via `init=_init_pool_conn` on pool creation so `list[float] ↔ vector` round-trips work on every connection.

### Threshold note
0.95 is measured, not a placeholder: `bench/cache_bench.py --mode=similarity` sweeps
0.80–0.99 against a 160-pair labeled eval set (true duplicates / adversarial
near-miss traps / unrelated) and picks the safest single threshold found. It does
**not** fully satisfy the ≤1% false-positive target — a numeric-ID near-miss
("order #4521" vs "order #4522") out-scores every true duplicate in the eval set,
which no global threshold can fix. See
`bench/reports/bench-20260713-similarity-threshold.md` for the sweep, the root-cause
analysis, and the recommended follow-up (a non-similarity guard for mismatched
numeric literals/IDs, not yet implemented).
