# bench/ — reproducing the numbers

Every number in the main README's "Benchmark Results" table comes from a script
in this directory. This page is the exact recipe to reproduce each one.

## Why the numbers didn't reproduce before

An earlier round of numbers (2.3 ms p50 overhead, ~730 RPS peak) was measured
from a **single** un-repeated run, with a small warmup and no recorded run
configuration. An independent re-run came out 2-4x worse. Root cause: no way
to tell whether that was noise, a colder warmup, a different worker count, or
a busier host — the report didn't record any of it. Those numbers have been
retracted from the main README pending a re-measurement on the deployed
reference instance.

The harness now:
- Mocks the upstream provider with an instant-response stub
  (`bench/_mock_server.py`) for the overhead/throughput benches, so we measure
  *our* added latency, not upstream latency/jitter.
- Runs a discarded warmup before every measured trial.
- Repeats every measurement across `>=3` independent trials and reports
  mean + stdev, not a single sample.
- Pins the gateway to a fixed worker count (`GATEWAY_WORKERS`, default `1`,
  set in `infra/docker-compose.yml`) and a fixed httpx connection-pool size,
  and embeds both — plus host CPU/RAM/OS/package versions — in every report
  via `bench/_config.py`. A report is self-documenting: you shouldn't need
  this file open to know what conditions produced a number.

## Prerequisites (all benches)

```bash
docker compose -f infra/docker-compose.yml up -d --build
pip install httpx asyncpg
export DATABASE_URL=postgresql://gateway:gateway@localhost:5432/gateway
```

Wait for the gateway healthcheck to go green before running anything:

```bash
docker compose -f infra/docker-compose.yml ps
```

## Overhead (`bench/overhead.py`)

Measures added latency of a full round-trip through the gateway vs. calling
the (mocked) provider directly.

```bash
python bench/overhead.py
```

Output: `bench/reports/bench-<timestamp>-overhead.md`. 3 trials of 500
sequential requests each (50-request warmup per trial, discarded).

## Throughput (`bench/throughput.py`)

Sweeps concurrency levels 1-100 to find peak sustained RPS and the
saturation point (where p95 first exceeds 2x the concurrency=1 baseline).

```bash
python bench/throughput.py
```

Output: `bench/reports/bench-<timestamp>-throughput.md`. 3 full sweeps
(trials), each with its own warmup.

For a clean single-worker saturation curve, `GATEWAY_WORKERS=1` is the
docker-compose default — don't scale the gateway service while running this.

## Cache hit-rate (`bench/cache_bench.py --mode=gateway`)

```bash
python bench/cache_bench.py --mode=gateway
```

Requires a live `OPENAI_API_KEY` only for `--mode=similarity` (semantic
threshold sweep); `--mode=gateway` (exact-cache hit rate) does not.

Its pre-run reset is scoped, not destructive: exact-cache Redis keys are
deleted by exact hash (only the ones this run itself will write — never
`budget:*` counters or unrelated entries), and `semantic_cache` rows are
deleted by `model = 'bench-cache'` only. Safe to run against a shared or live
instance, not just a disposable local stack.

Report includes hit-vs-miss latency (from the gateway's `latency_ms` DB
column) alongside hit rate.

## Failover (`bench/failover_bench.py`)

```bash
FALLBACK_BACKOFF_BASE_MS=0 python bench/failover_bench.py
```

## Running authenticated (against a real API key)

All four scripts default to anonymous requests (no `Authorization` header),
matching local dev where auth enforcement is often not the thing under test.
Set `GATEWAY_API_KEY` to send every gateway-bound request with that key, e.g.
`GATEWAY_API_KEY=bench-key python bench/overhead.py`. Each report records
which mode (`bench-key` / `anonymous`) it ran in. Prefer an authenticated run
when measuring numbers a real API consumer would experience — anonymous
requests skip the budget-check Redis/DB round trip and understate overhead.

## Reproducibility bar

Run the same script 3 times back-to-back (fresh `docker compose down && up`
between runs if you want to rule out warm-container effects). The headline
number in each run's report (mean overhead p50, mean peak RPS) should agree
within ~15% of the other runs. If it doesn't, something about the run
environment changed — check the embedded "Run configuration" block in each
report first; it's the diff you're looking for.

## Known sources of variance to control for

- **Other processes on the host.** Close anything CPU-heavy; the gateway
  event loop and the mock provider are both single-threaded per worker.
- **Docker Desktop resource limits.** These change host<->container network
  latency on macOS in particular. Keep them fixed across runs you intend to
  compare.
- **Cold vs. warm containers.** The warmup in each script discards
  connection-setup cost within a run, but a freshly-started Postgres/Redis
  container is doing more background work than one that's been idle for a
  few minutes. Prefer comparing runs against a stack that's been up for a
  similar amount of time.
