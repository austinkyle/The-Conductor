"""Failover benchmark — success rate and latency penalty when the primary provider is down.

Seeds a two-provider chain under alias bench-failover:
  Provider A (port 9002, priority 0): always returns 503 (total outage simulation)
  Provider B (port 9003, priority 1): always returns 200 with canned response

The gateway walks the chain in priority order, so every request fails over to B.

Usage:
    # Reduce backoff for speed; restart gateway first:
    #   FALLBACK_BACKOFF_BASE_MS=0 docker compose -f infra/docker-compose.yml up -d gateway
    python bench/failover_bench.py

Prerequisites:
    docker compose -f infra/docker-compose.yml up -d
    export DATABASE_URL=postgresql://gateway:gateway@localhost:5432/gateway
    pip install httpx asyncpg
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import asyncpg
import httpx

sys.path.insert(0, str(Path(__file__).parent))
from _db import cleanup_bench_alias, seed_bench_provider
from _mock_server import start_mock_provider

_N = 200
_PORT_A = 9002
_PORT_B = 9003
_GATEWAY_URL = "http://localhost:8000/v1/chat/completions"
_ALIAS = "bench-failover"
_PROVIDER_A = "bench-fail-a"
_PROVIDER_B = "bench-ok-b"
_MOCK_BASE_A = f"http://host.docker.internal:{_PORT_A}"
_MOCK_BASE_B = f"http://host.docker.internal:{_PORT_B}"


def _pct(data: list[float], p: float) -> float:
    if not data:
        return float("nan")
    s = sorted(data)
    idx = (len(s) - 1) * p / 100.0
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


async def main() -> None:
    db_url = os.environ.get("DATABASE_URL", "postgresql://gateway:gateway@localhost:5432/gateway")
    conn = await asyncpg.connect(db_url)

    # Warn if backoff is still at the slow default — the bench will take ~100 s.
    check_q = "SELECT current_setting('app.fallback_backoff_base_ms', true)"
    # The env var is read by the gateway process, not Postgres. Just note the warning.
    backoff_env = os.environ.get("FALLBACK_BACKOFF_BASE_MS")
    if backoff_env is None or int(backoff_env or 500) > 0:
        print(
            "WARNING: FALLBACK_BACKOFF_BASE_MS is not 0. "
            "With the default 500 ms backoff, 200 requests will take ~100 s.\n"
            "Set FALLBACK_BACKOFF_BASE_MS=0 in the gateway environment for speed.\n"
        )

    server_a = await start_mock_provider(_PORT_A, fail_rate=1.0)
    server_b = await start_mock_provider(_PORT_B, fail_rate=0.0)

    await seed_bench_provider(
        conn, provider_name=_PROVIDER_A, alias=_ALIAS, base_url=_MOCK_BASE_A, priority=0
    )
    await seed_bench_provider(
        conn, provider_name=_PROVIDER_B, alias=_ALIAS, base_url=_MOCK_BASE_B, priority=1
    )

    start_ts = datetime.now(tz=timezone.utc)
    payload = {
        "model": _ALIAS,
        "messages": [{"role": "user", "content": "ping"}],
        "cache": {"no_cache": True},
    }

    client_latencies: list[float] = []
    errors = 0

    rows = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            print(f"Sending {_N} requests (chain: always-503 A → always-200 B)…")
            for i in range(_N):
                t0 = time.perf_counter()
                try:
                    r = await client.post(_GATEWAY_URL, json=payload)
                    r.raise_for_status()
                    client_latencies.append((time.perf_counter() - t0) * 1000.0)
                except Exception as exc:
                    errors += 1
                    print(f"  Request {i + 1} failed: {exc}")
                if (i + 1) % 50 == 0:
                    print(f"  {i + 1}/{_N}")
        # Read results from the requests spine before cleanup removes served_provider_id rows.
        rows = await conn.fetch(
            """
            SELECT fallback_depth, status, error_class, latency_ms
            FROM requests
            WHERE requested_model = $1
              AND created_at >= $2
            ORDER BY id
            """,
            _ALIAS,
            start_ts,
        )
    finally:
        server_a.close()
        server_b.close()
        await asyncio.gather(server_a.wait_closed(), server_b.wait_closed())
        await cleanup_bench_alias(conn, alias=_ALIAS, provider_names=[_PROVIDER_A, _PROVIDER_B])
        await conn.close()

    depth0_latencies = [float(r["latency_ms"]) for r in rows if r["fallback_depth"] == 0 and r["status"] == "success" and r["latency_ms"] is not None]
    depth1_latencies = [float(r["latency_ms"]) for r in rows if r["fallback_depth"] == 1 and r["status"] == "success" and r["latency_ms"] is not None]

    success_d0 = sum(1 for r in rows if r["fallback_depth"] == 0 and r["status"] == "success")
    success_d1 = sum(1 for r in rows if r["fallback_depth"] == 1 and r["status"] == "success")
    error_count = sum(1 for r in rows if r["status"] == "error")
    total = len(rows)

    def _pct_row(p: int, d0: list[float], d1: list[float]) -> str:
        v0 = _pct(d0, p) if d0 else float("nan")
        v1 = _pct(d1, p) if d1 else float("nan")
        penalty = (v1 - v0) if (d0 and d1) else float("nan")
        d0_s = f"{v0:.1f}" if d0 else "—"
        d1_s = f"{v1:.1f}" if d1 else "—"
        pen_s = f"{penalty:.1f}" if (d0 and d1) else "—"
        return f"| p{p:<9} | {d0_s:<12} | {d1_s:<12} | {pen_s:<21} |"

    def _pct_row_nobaseline(p: int, d1: list[float]) -> str:
        v1 = _pct(d1, p) if d1 else float("nan")
        v1_s = f"{v1:.1f}" if d1 else "—"
        return f"| p{p:<9} | {'—':<12} | {v1_s:<12} | {'—':<21} |"

    latency_rows = "\n".join(
        _pct_row(p, depth0_latencies, depth1_latencies) if depth0_latencies
        else _pct_row_nobaseline(p, depth1_latencies)
        for p in (50, 95, 99)
    )

    report = f"""\
## Failover Benchmark — {date.today().isoformat()}

Chain: Provider A (always-503 mock, port {_PORT_A}) → Provider B (always-200 mock, port {_PORT_B})
Requests: {_N} sequential

| Outcome           | Count | %     |
|-------------------|-------|-------|
| success (depth=0) | {success_d0:<5} | {100.0 * success_d0 / total if total else 0:.1f}%  |
| success (depth=1) | {success_d1:<5} | {100.0 * success_d1 / total if total else 0:.1f}%  |
| error             | {error_count:<5} | {100.0 * error_count / total if total else 0:.1f}%  |

Latency (successful requests, from gateway DB column latency_ms):
| Percentile | depth=0 (ms) | depth=1 (ms) | Failover penalty (ms) |
|------------|-------------|--------------|----------------------|
{latency_rows}

Methodology: local mock servers on loopback; set FALLBACK_BACKOFF_BASE_MS=0 in the
gateway environment for accurate failover-only overhead (without backoff sleep noise).
Cache bypassed via `"cache": {{"no_cache": true}}` on all requests.
"""

    out = Path(__file__).parent / "reports"
    out.mkdir(exist_ok=True)
    fname = out / f"bench-{date.today().isoformat().replace('-', '')}-failover.md"
    fname.write_text(report)
    print(f"\nReport → {fname}\n")
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
