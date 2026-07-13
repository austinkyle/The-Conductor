# Deployed-reference benchmark — 2026-07-13

Consolidates the full bench harness (overhead, throughput, cache, failover) run
**authenticated as `bench-key`** against the live `conductor-demo` Fly instance.
Each number below is sourced from its own dated report in this directory — this
page is the index + headline summary, not a replacement for the per-trial detail
in those reports.

## Run configuration (applies to all four benchmarks below)

| Field | Value |
|---|---|
| Fly app | `conductor-demo` |
| Machine | `shared-cpu-1x`, 1 GiB RAM |
| Region | `sjc` |
| Host CPU | AMD EPYC (Fly's shared-cpu-1x host) |
| OS | Linux 6.12.91-fly |
| Python | 3.11.15 |
| `GATEWAY_WORKERS` | 1 (pinned) |
| Postgres | Neon (managed, public internet, not co-located with the VM) |
| Redis | Upstash (managed, public internet, not co-located with the VM) |
| Auth | `Authorization: Bearer bench-key` on every gateway-bound request |
| Provider (overhead/throughput/cache/failover-chain mocks) | local instant-response mock, eliminates upstream-provider latency/jitter so only the gateway's own added latency is measured |
| Method | scripts uploaded via `fly ssh sftp put`, run via `fly ssh console` against the same `localhost:8000` gateway process real traffic hits (see `gateway/DEPLOY.md`) |

How to reproduce: follow `gateway/DEPLOY.md`'s "Running the bench/ benchmark
harness against this instance" section end to end, setting
`GATEWAY_API_KEY=bench-key` in every invocation (already the documented
default in that runbook as of this run).

---

## Overhead

Source: [`bench-20260713-175446-overhead.md`](bench-20260713-175446-overhead.md)
— 3 trials x 500 sequential requests/trial (50-request warmup/trial, discarded).

| Percentile | Direct (ms) | Gateway (ms) | Overhead (ms) | Stdev across trials (ms) |
|---|---|---|---|---|
| p50 | 1.38 | 484.71 | 483.33 | 1.77 |
| p95 | 1.65 | 504.64 | 502.99 | 3.22 |
| p99 | 1.96 | 636.71 | 634.76 | 125.11 |

## Throughput

Source: [`bench-20260713-180139-throughput.md`](bench-20260713-180139-throughput.md)
— 3 full sweeps (trials) across concurrency levels 1-100, 100 requests/level/trial.

Peak sustained RPS: **mean 20.5, stdev 0.1** (trial values: 20.6 / 20.5 / 20.4)
Saturation point: **~20 concurrent requests** (mean p95 first exceeds 2x the
concurrency=1 baseline of 511.4 ms)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|
| 1 | 2.1 | 480.6 | 511.4 | 649.2 |
| 10 | 18.8 | 479.0 | 611.5 | 1021.9 |
| 20 | 19.8 | 949.1 | 1448.4 | 1704.2 |
| 100 | 18.3 | 2905.1 | 5089.2 | 5223.8 |

(Full 8-row table in the source report.)

## Cache

Source: [`bench-20260713-cache.md`](bench-20260713-cache.md) — 200-request
corpus (50 unique + 50 exact-duplicate + 100 semantic-paraphrase), single run
(this script doesn't have a multi-trial mode; hit-rate/latency-by-status don't
carry the same run-to-run noise a timing sweep does).

| cache_status | count | % |
|---|---|---|
| exact_hit | 50 | 25.0% |
| semantic_hit | 6 | 3.0% |
| miss | 144 | 72.0% |

Hit vs miss latency (gateway DB column `latency_ms`):

| Percentile | Hit (ms) | Miss (ms) |
|---|---|---|
| p50 | 124.0 | 457.5 |
| p95 | 359.0 | 760.8 |
| p99 | 427.4 | 2012.0 |

Reset for this run was **non-destructive**: exact-cache Redis keys were
deleted by exact hash (only keys this run itself writes) and `semantic_cache`
rows by `model = 'bench-cache'` only — no `flushdb`, no unscoped `DELETE`, so
`demo-key`'s and `bench-key`'s real spend/cache state was untouched. See
`docs/architecture/DECISIONS.md` Phase 6 for why the prior run skipped this
benchmark, and `bench/cache_bench.py`/`bench/README.md` for the scoped-reset
implementation that made this run safe.

## Failover

Source: [`bench-20260713-failover.md`](bench-20260713-failover.md) — 200
sequential requests, chain: always-503 mock (provider A) -> always-200 mock
(provider B), production `FALLBACK_BACKOFF_BASE_MS=500` (not the local-dev
`=0` speed setting).

| Outcome | Count | % |
|---|---|---|
| success (depth=0) | 0 | 0.0% |
| success (depth=1) | 200 | 100.0% |
| error | 0 | 0.0% |

Depth=1 latency: p50 638.0 ms, p95 642.0 ms, p99 655.3 ms (includes one real
500 ms backoff sleep per request — expected chain-walk behavior, not gateway
overhead).

---

## Why these numbers are worse than the anonymous same-day run

An earlier run today measured the same four benchmarks **anonymously** (no
`Authorization` header) — see `bench-20260713-163439-overhead.md`,
`bench-20260713-163758-throughput.md`, `bench-20260713-fly-failover.md`. Every
number above is worse under `bench-key` auth: overhead p50 rose from ~216 ms to
~483 ms, peak RPS dropped from ~44 to ~20.5, failover depth=1 p50 rose from
576 ms to 638 ms. This is expected, not a regression introduced by this run:
authenticating adds a real budget-check round trip (`resolve_api_key` +
`check_budget`/`record_spend`, hitting Neon and Upstash over the public
internet) that an anonymous request skips entirely. `bench-key`'s own spend
after this run is $0.0000 (`GET /v1/observability/spend`) since bench models
are seeded without pricing — the auth path's cost here is pure latency, not
budget consumption.

Per the sanity rule (re-run anything that looks surprisingly *good*): nothing
above came back better than the anonymous run or than expectation, so nothing
was re-run. Cache hit latency being lower than miss latency is the one number
that looks "good," but it has an obvious structural explanation (a cache hit
skips the mock-provider round trip entirely) rather than being a surprise, so
it wasn't treated as a red flag.
