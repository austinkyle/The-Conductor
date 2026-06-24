# bench/ — load & benchmark harness (the rigor signal)

Drives synthetic load through the gateway and produces the numbers for the README.

## Routing table
| Task type | READ | SKIP | Tools / Skills |
|---|---|---|---|
| Proxy-overhead measurement | bench/overhead.py | dashboard/ | asyncio / locust |
| Cache hit-rate + cost-reduction | bench/cache_bench.py | translation/ | — |
| Failover success / recovery time | bench/failover_bench.py | budgets/ | — |
| Throughput / saturation | bench/throughput.py | — | — |

## Invariants
- Every report states METHODOLOGY (load pattern, hardware, provider mix). Methodology is what separates a benchmark from a marketing claim.
- Report proxy overhead as added latency vs. calling the provider directly, p50/p95/p99. Be honest that a proxy adds latency; show it's small and bounded.
- Output to bench/reports/bench-YYYYMMDD-scenario.md.
