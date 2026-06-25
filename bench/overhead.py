"""Gateway overhead benchmark — measures added latency vs. calling the provider directly.

Usage:
    python bench/overhead.py

Prerequisites:
    docker compose -f infra/docker-compose.yml up -d
    pip install httpx asyncpg
    export DATABASE_URL=postgresql://gateway:gateway@localhost:5432/gateway
"""
from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import asyncpg
import httpx

sys.path.insert(0, str(Path(__file__).parent))
from _db import cleanup_bench_alias, seed_bench_provider
from _mock_server import start_mock_provider

_N = 500
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


def _cpu_model() -> str:
    try:
        return subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        try:
            out = Path("/proc/cpuinfo").read_text()
            for line in out.splitlines():
                if "model name" in line:
                    return line.split(":", 1)[1].strip()
        except Exception:
            pass
    return "unknown"


async def main() -> None:
    db_url = os.environ.get("DATABASE_URL", "postgresql://gateway:gateway@localhost:5432/gateway")
    conn = await asyncpg.connect(db_url)

    server = await start_mock_provider(_PORT)
    await seed_bench_provider(
        conn, provider_name=_PROVIDER_NAME, alias=_ALIAS, base_url=_MOCK_BASE_URL
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            print(f"Warming up (10 req each)…")
            await _bench(client, _DIRECT_URL, _DIRECT_PAYLOAD, 10)
            await _bench(client, _GATEWAY_URL, _GATEWAY_PAYLOAD, 10)

            print(f"Direct baseline: {_N} sequential requests to mock…")
            direct = await _bench(client, _DIRECT_URL, _DIRECT_PAYLOAD, _N)

            print(f"Gateway: {_N} sequential requests via proxy…")
            gw = await _bench(client, _GATEWAY_URL, _GATEWAY_PAYLOAD, _N)
    finally:
        server.close()
        await server.wait_closed()
        await cleanup_bench_alias(conn, alias=_ALIAS, provider_names=[_PROVIDER_NAME])
        await conn.close()

    rows = []
    for p in (50, 95, 99):
        d = _pct(direct, p)
        g = _pct(gw, p)
        rows.append((f"p{p}", d, g, g - d))

    arch = platform.machine()
    cpu = _cpu_model()

    table = "\n".join(
        f"| {label:<10} | {d:<11.1f} | {g:<12.1f} | {o:<19.1f} |"
        for label, d, g, o in rows
    )

    report = f"""\
## Gateway Overhead — {date.today().isoformat()}

Hardware: {arch}, {cpu}
Requests: {_N} sequential
Provider: local mock (instant response, eliminates provider latency)

| Percentile | Direct (ms) | Gateway (ms) | Added overhead (ms) |
|------------|-------------|--------------|---------------------|
{table}

Methodology: sequential asyncio requests, same process, loopback network.
Cache bypassed via `"cache": {{"no_cache": true}}` on every request.
"""

    out = Path(__file__).parent / "reports"
    out.mkdir(exist_ok=True)
    fname = out / f"bench-{date.today().isoformat().replace('-', '')}-overhead.md"
    fname.write_text(report)
    print(f"\nReport → {fname}\n")
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
