"""Gateway overhead benchmark — measures added latency vs. calling the provider directly.

Usage:
    python bench/overhead.py

Prerequisites:
    docker compose -f infra/docker-compose.yml up -d
    pip install httpx asyncpg
    export DATABASE_URL=postgresql://gateway:gateway@localhost:5432/gateway

Reproducibility notes (see bench/README.md for the full writeup):
    - The provider is a local mock that returns instantly (bench/_mock_server.py),
      never a live LLM API — this isolates OUR added latency from upstream
      provider latency/jitter, which would otherwise dominate the signal.
    - Each trial runs its own warmup (discarded) before the measured requests,
      so connection-pool/event-loop startup costs don't leak into p50.
    - The full run repeats >=3 independent trials and reports mean + stdev per
      percentile, because a single run can't distinguish signal from noise.
    - Every report embeds the run configuration (host, worker count, trial
      sizes) so a second run can be checked against the same conditions.
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

_N = 500
_WARMUP_N = 50
_TRIALS = 3
_PORT = 9001
# The mock server must be reachable from both the host (for the direct baseline)
# and the Docker gateway container (via host.docker.internal).
_MOCK_BASE_URL = f"http://host.docker.internal:{_PORT}"
_DIRECT_URL = f"http://localhost:{_PORT}/chat/completions"
_GATEWAY_URL = "http://localhost:8000/v1/chat/completions"
_ALIAS = "bench-overhead"
_PROVIDER_NAME = "bench-overhead"

_GATEWAY_PAYLOAD = {
    "model": _ALIAS,
    "messages": [{"role": "user", "content": "ping"}],
    "cache": {"no_cache": True},
}
_DIRECT_PAYLOAD = {
    "model": "mock-model",
    "messages": [{"role": "user", "content": "ping"}],
}


def _pct(data: list[float], p: float) -> float:
    s = sorted(data)
    idx = (len(s) - 1) * p / 100.0
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


async def _bench(client: httpx.AsyncClient, url: str, payload: dict, n: int) -> list[float]:
    times: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = await client.post(url, json=payload)
        r.raise_for_status()
        times.append((time.perf_counter() - t0) * 1000.0)
    return times


async def _run_trial(client: httpx.AsyncClient, trial_idx: int) -> dict[str, tuple[float, float]]:
    """Runs one full warmup+measure cycle. Returns {percentile: (direct_ms, gateway_ms)}."""
    print(f"  Trial {trial_idx}: warmup ({_WARMUP_N} req each, discarded)…")
    await _bench(client, _DIRECT_URL, _DIRECT_PAYLOAD, _WARMUP_N)
    await _bench(client, _GATEWAY_URL, _GATEWAY_PAYLOAD, _WARMUP_N)

    print(f"  Trial {trial_idx}: direct baseline ({_N} sequential)…")
    direct = await _bench(client, _DIRECT_URL, _DIRECT_PAYLOAD, _N)
    print(f"  Trial {trial_idx}: gateway ({_N} sequential)…")
    gw = await _bench(client, _GATEWAY_URL, _GATEWAY_PAYLOAD, _N)

    return {f"p{p}": (_pct(direct, p), _pct(gw, p)) for p in (50, 95, 99)}


async def main() -> None:
    db_url = os.environ.get("DATABASE_URL", "postgresql://gateway:gateway@localhost:5432/gateway")
    conn = await asyncpg.connect(db_url)

    server = await start_mock_provider(_PORT)
    await seed_bench_provider(
        conn, provider_name=_PROVIDER_NAME, alias=_ALIAS, base_url=_MOCK_BASE_URL
    )

    trial_results: list[dict[str, tuple[float, float]]] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            for i in range(1, _TRIALS + 1):
                trial_results.append(await _run_trial(client, i))
    finally:
        server.close()
        await server.wait_closed()
        await cleanup_bench_alias(conn, alias=_ALIAS, provider_names=[_PROVIDER_NAME])
        await conn.close()

    rows = []
    per_trial_lines = []
    for p in ("p50", "p95", "p99"):
        directs = [t[p][0] for t in trial_results]
        gws = [t[p][1] for t in trial_results]
        overheads = [g - d for d, g in zip(directs, gws)]
        rows.append((p, mean(directs), mean(gws), mean(overheads), stdev(overheads)))
        per_trial_lines.append(f"| {p} | " + " | ".join(f"{o:.2f}" for o in overheads) + " |")

    cfg = run_config(
        trials=_TRIALS, warmup_n=_WARMUP_N, n_per_trial=_N,
        extra={"gateway_url": _GATEWAY_URL, "provider": "local mock (instant response)"},
    )

    table = "\n".join(
        f"| {label:<10} | {d:<11.2f} | {g:<12.2f} | {o:<10.2f} | {sd:<8.2f} |"
        for label, d, g, o, sd in rows
    )
    per_trial_header = (
        "| Percentile | " + " | ".join(f"Trial {i}" for i in range(1, _TRIALS + 1)) + " |"
    )
    per_trial_sep = "|---" * (_TRIALS + 1) + "|"
    per_trial_table = "\n".join([per_trial_header, per_trial_sep, *per_trial_lines])

    report = f"""\
## Gateway Overhead — {date.today().isoformat()}

Requests per trial: {_N} sequential (after a {_WARMUP_N}-request warmup, discarded)
Trials: {_TRIALS}
Provider: local mock (instant response, eliminates provider latency so we
measure only the latency the gateway itself adds)

### Mean overhead across trials

| Percentile | Direct (ms) | Gateway (ms) | Overhead (ms) | Stdev (ms) |
|------------|-------------|--------------|----------------|------------|
{table}

### Per-trial overhead (ms), for variance inspection

{per_trial_table}

{format_config(cfg)}
Methodology: sequential asyncio requests, same process, loopback network.
Cache bypassed via `"cache": {{"no_cache": true}}` on every request. Each
trial re-warms the connection before the measured requests; percentiles are
computed per-trial, then averaged with stdev shown across the {_TRIALS} trials.
"""

    out = Path(__file__).parent / "reports"
    out.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    fname = out / f"bench-{stamp}-overhead.md"
    fname.write_text(report)
    print(f"\nReport → {fname}\n")
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
