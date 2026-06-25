"""Throughput benchmark — sustained RPS at increasing concurrency levels.

Finds the saturation point: the concurrency level where p95 latency first
exceeds 2× the p95 at concurrency=1.

Usage:
    python bench/throughput.py

Prerequisites:
    docker compose -f infra/docker-compose.yml up -d
    # Recommended: single gateway worker for a clean saturation curve:
    #   uvicorn --workers 1 (set in docker-compose if testing worker saturation)
    export DATABASE_URL=postgresql://gateway:gateway@localhost:5432/gateway
    pip install httpx asyncpg
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import date
from pathlib import Path

import asyncpg
import httpx

sys.path.insert(0, str(Path(__file__).parent))
from _db import cleanup_bench_alias, seed_bench_provider
from _mock_server import start_mock_provider

_PORT = 9001
_GATEWAY_URL = "http://localhost:8000/v1/chat/completions"
_ALIAS = "bench-throughput"
_PROVIDER_NAME = "bench-throughput"
_MOCK_BASE_URL = f"http://host.docker.internal:{_PORT}"
_N_PER_LEVEL = 100
_CONCURRENCY_LEVELS = [1, 2, 5, 10, 20, 40, 60, 100]

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


async def main() -> None:
    db_url = os.environ.get("DATABASE_URL", "postgresql://gateway:gateway@localhost:5432/gateway")
    conn = await asyncpg.connect(db_url)

    server = await start_mock_provider(_PORT)
    await seed_bench_provider(
        conn, provider_name=_PROVIDER_NAME, alias=_ALIAS, base_url=_MOCK_BASE_URL
    )

    results: list[tuple[int, float, float, float, float]] = []  # concurrency, rps, p50, p95, p99

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=100),
        ) as client:
            # Warm up to establish connections.
            print("Warming up (10 req at concurrency=1)…")
            await _level(client, 1, 10)

            for c in _CONCURRENCY_LEVELS:
                print(f"Concurrency={c}: {_N_PER_LEVEL} requests…", end=" ", flush=True)
                wall, lats = await _level(client, c, _N_PER_LEVEL)
                rps = _N_PER_LEVEL / wall
                p50 = _pct(lats, 50)
                p95 = _pct(lats, 95)
                p99 = _pct(lats, 99)
                results.append((c, rps, p50, p95, p99))
                print(f"RPS={rps:.1f}  p50={p50:.1f}ms  p95={p95:.1f}ms")
    finally:
        server.close()
        await server.wait_closed()
        await cleanup_bench_alias(conn, alias=_ALIAS, provider_names=[_PROVIDER_NAME])
        await conn.close()

    baseline_p95 = results[0][3]  # p95 at concurrency=1
    saturation_c: int | None = None
    for c, rps, p50, p95, p99 in results:
        if p95 > 2 * baseline_p95 and saturation_c is None:
            saturation_c = c

    peak_rps = max(r[1] for r in results)

    table = "\n".join(
        f"| {c:<11} | {rps:<7.1f} | {p50:<8.1f} | {p95:<8.1f} | {p99:<8.1f} |"
        for c, rps, p50, p95, p99 in results
    )

    sat_note = (
        f"~{saturation_c} concurrent requests (p95 first exceeds 2× baseline {baseline_p95:.1f} ms)"
        if saturation_c
        else f"not reached within tested range (baseline p95={baseline_p95:.1f} ms)"
    )

    report = f"""\
## Throughput Benchmark — {date.today().isoformat()}

Provider: local mock (instant response)
Requests per level: {_N_PER_LEVEL}

| Concurrency | RPS     | p50 (ms) | p95 (ms) | p99 (ms) |
|-------------|---------|----------|----------|----------|
{table}

Saturation point: {sat_note}
Peak sustained RPS: {peak_rps:.1f}

Methodology: asyncio semaphore-bounded concurrency; local mock provider;
cache bypassed; single gateway process (uvicorn --workers 1 recommended).
"""

    out = Path(__file__).parent / "reports"
    out.mkdir(exist_ok=True)
    fname = out / f"bench-{date.today().isoformat().replace('-', '')}-throughput.md"
    fname.write_text(report)
    print(f"\nReport → {fname}\n")
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
