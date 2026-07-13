"""Throughput benchmark — sustained RPS at increasing concurrency levels.

Finds the saturation point: the concurrency level where p95 latency first
exceeds 2x the p95 at concurrency=1.

Usage:
    python bench/throughput.py

Prerequisites:
    docker compose -f infra/docker-compose.yml up -d
    export DATABASE_URL=postgresql://gateway:gateway@localhost:5432/gateway
    pip install httpx asyncpg

Reproducibility notes (see bench/README.md for the full writeup):
    - Gateway worker count is pinned via GATEWAY_WORKERS (default 1, set in
      infra/docker-compose.yml) rather than left to uvicorn's default, since
      RPS at a given concurrency is directly a function of worker count.
    - The httpx client's connection-pool limits are fixed and recorded in the
      report — an unbounded or under-provisioned pool would cap RPS on its
      own and be mistaken for gateway saturation.
    - A warmup pass runs before every trial's sweep (discarded) to pay for
      connection establishment outside the measured window.
    - The full sweep (all concurrency levels) repeats >=3 independent trials;
      peak RPS and saturation point are reported as mean + stdev across
      trials, not a single sample.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

import asyncpg
import httpx

sys.path.insert(0, str(Path(__file__).parent))
from _config import format_config, mean, run_config, stdev
from _db import cleanup_bench_alias, seed_bench_provider
from _mock_server import start_mock_provider

_PORT = 9001
_GATEWAY_URL = "http://localhost:8000/v1/chat/completions"
_ALIAS = "bench-throughput"
_PROVIDER_NAME = "bench-throughput"
_MOCK_BASE_URL = f"http://host.docker.internal:{_PORT}"
_N_PER_LEVEL = 100
_WARMUP_N = 50
_TRIALS = 3
_CONCURRENCY_LEVELS = [1, 2, 5, 10, 20, 40, 60, 100]
_MAX_CONNECTIONS = 200
_MAX_KEEPALIVE = 100

_PAYLOAD = {
    "model": _ALIAS,
    "messages": [{"role": "user", "content": "ping"}],
    "cache": {"no_cache": True},
}


def _pct(data: list[float], p: float) -> float:
    s = sorted(data)
    idx = (len(s) - 1) * p / 100.0
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


async def _level(client: httpx.AsyncClient, concurrency: int, n: int) -> tuple[float, list[float]]:
    """Run *n* requests at *concurrency*, return (wall_seconds, per_request_latency_ms)."""
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    lock = asyncio.Lock()

    async def one() -> None:
        async with sem:
            t0 = time.perf_counter()
            r = await client.post(_GATEWAY_URL, json=_PAYLOAD)
            r.raise_for_status()
            ms = (time.perf_counter() - t0) * 1000.0
            async with lock:
                latencies.append(ms)

    wall_start = time.perf_counter()
    await asyncio.gather(*[one() for _ in range(n)])
    wall_elapsed = time.perf_counter() - wall_start
    return wall_elapsed, latencies


async def _run_trial(
    client: httpx.AsyncClient, trial_idx: int
) -> list[tuple[int, float, float, float, float]]:
    """One full sweep across all concurrency levels. Returns per-level (c, rps, p50, p95, p99)."""
    print(f"Trial {trial_idx}: warmup ({_WARMUP_N} req at concurrency=1, discarded)…")
    await _level(client, 1, _WARMUP_N)

    results: list[tuple[int, float, float, float, float]] = []
    for c in _CONCURRENCY_LEVELS:
        print(f"Trial {trial_idx}: concurrency={c}: {_N_PER_LEVEL} requests…", end=" ", flush=True)
        wall, lats = await _level(client, c, _N_PER_LEVEL)
        rps = _N_PER_LEVEL / wall
        p50, p95, p99 = _pct(lats, 50), _pct(lats, 95), _pct(lats, 99)
        results.append((c, rps, p50, p95, p99))
        print(f"RPS={rps:.1f}  p50={p50:.1f}ms  p95={p95:.1f}ms")
    return results


async def main() -> None:
    db_url = os.environ.get("DATABASE_URL", "postgresql://gateway:gateway@localhost:5432/gateway")
    conn = await asyncpg.connect(db_url)

    server = await start_mock_provider(_PORT)
    await seed_bench_provider(
        conn, provider_name=_PROVIDER_NAME, alias=_ALIAS, base_url=_MOCK_BASE_URL
    )

    trial_results: list[list[tuple[int, float, float, float, float]]] = []
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            limits=httpx.Limits(
                max_connections=_MAX_CONNECTIONS, max_keepalive_connections=_MAX_KEEPALIVE
            ),
        ) as client:
            for i in range(1, _TRIALS + 1):
                trial_results.append(await _run_trial(client, i))
    finally:
        server.close()
        await server.wait_closed()
        await cleanup_bench_alias(conn, alias=_ALIAS, provider_names=[_PROVIDER_NAME])
        await conn.close()

    # Aggregate per concurrency level across trials.
    agg_rows = []
    for i, c in enumerate(_CONCURRENCY_LEVELS):
        rps_vals = [trial_results[t][i][1] for t in range(_TRIALS)]
        p50_vals = [trial_results[t][i][2] for t in range(_TRIALS)]
        p95_vals = [trial_results[t][i][3] for t in range(_TRIALS)]
        p99_vals = [trial_results[t][i][4] for t in range(_TRIALS)]
        agg_rows.append(
            (c, mean(rps_vals), stdev(rps_vals), mean(p50_vals), mean(p95_vals), mean(p99_vals))
        )

    baseline_p95 = agg_rows[0][4]  # mean p95 at concurrency=1
    saturation_c: int | None = None
    for c, rps, rps_sd, p50, p95, p99 in agg_rows:
        if p95 > 2 * baseline_p95 and saturation_c is None:
            saturation_c = c

    peak_rps_per_trial = [max(r[1] for r in trial) for trial in trial_results]
    peak_rps_mean = mean(peak_rps_per_trial)
    peak_rps_sd = stdev(peak_rps_per_trial)

    cfg = run_config(
        trials=_TRIALS, warmup_n=_WARMUP_N, n_per_trial=_N_PER_LEVEL,
        extra={
            "concurrency_levels": _CONCURRENCY_LEVELS,
            "httpx_max_connections": _MAX_CONNECTIONS,
            "httpx_max_keepalive_connections": _MAX_KEEPALIVE,
            "provider": "local mock (instant response)",
        },
    )

    table = "\n".join(
        f"| {c:<11} | {rps:<7.1f} | {rps_sd:<7.1f} | {p50:<8.1f} | {p95:<8.1f} | {p99:<8.1f} |"
        for c, rps, rps_sd, p50, p95, p99 in agg_rows
    )

    sat_note = (
        f"~{saturation_c} concurrent requests (mean p95 first exceeds 2x baseline {baseline_p95:.1f} ms)"
        if saturation_c
        else f"not reached within tested range (baseline p95={baseline_p95:.1f} ms)"
    )

    per_trial_peak = ", ".join(f"trial {i+1}: {v:.1f}" for i, v in enumerate(peak_rps_per_trial))

    report = f"""\
## Throughput Benchmark — {date.today().isoformat()}

Provider: local mock (instant response)
Requests per level per trial: {_N_PER_LEVEL}
Trials: {_TRIALS} (each a full sweep across all concurrency levels, with its own warmup)

### Mean across trials (per concurrency level)

| Concurrency | RPS     | RPS stdev | p50 (ms) | p95 (ms) | p99 (ms) |
|-------------|---------|-----------|----------|----------|----------|
{table}

Saturation point: {sat_note}
Peak sustained RPS: mean={peak_rps_mean:.1f}, stdev={peak_rps_sd:.1f} ({per_trial_peak})

{format_config(cfg)}
Methodology: asyncio semaphore-bounded concurrency; local mock provider;
cache bypassed; single gateway worker (GATEWAY_WORKERS pinned, see
infra/docker-compose.yml). Each trial re-warms the connection pool before
its measured sweep; RPS/latency are averaged across the {_TRIALS} trials with
stdev shown so run-to-run variance is visible rather than hidden.
"""

    out = Path(__file__).parent / "reports"
    out.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    fname = out / f"bench-{stamp}-throughput.md"
    fname.write_text(report)
    print(f"\nReport → {fname}\n")
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
