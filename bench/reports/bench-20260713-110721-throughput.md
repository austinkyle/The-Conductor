## Throughput Benchmark — 2026-07-13

Provider: local mock (instant response)
Requests per level per trial: 100
Trials: 3 (each a full sweep across all concurrency levels, with its own warmup)

### Mean across trials (per concurrency level)

| Concurrency | RPS     | RPS stdev | p50 (ms) | p95 (ms) | p99 (ms) |
|-------------|---------|-----------|----------|----------|----------|
| 1           | 215.1   | 18.4    | 4.2      | 7.2      | 10.7     |
| 2           | 302.9   | 31.0    | 5.9      | 9.8      | 18.2     |
| 5           | 554.9   | 124.1   | 8.7      | 12.7     | 15.5     |
| 10          | 547.8   | 124.1   | 16.4     | 30.6     | 40.1     |
| 20          | 544.2   | 174.2   | 31.2     | 74.7     | 116.3    |
| 40          | 325.2   | 18.2    | 89.5     | 236.6    | 263.4    |
| 60          | 312.8   | 15.4    | 139.2    | 282.0    | 296.4    |
| 100         | 300.8   | 9.3     | 173.4    | 301.8    | 316.7    |

Saturation point: ~10 concurrent requests (mean p95 first exceeds 2x baseline 7.2 ms)
Peak sustained RPS: mean=601.1, stdev=88.7 (trial 1: 693.6, trial 2: 516.7, trial 3: 593.1)

### Run configuration
- host_arch: arm64
- host_cpu: Apple M1 Pro
- host_ram: 32.0 GiB
- os: Darwin 25.5.0
- python: 3.11.1
- httpx: 0.28.1
- asyncpg: 0.31.0
- gateway_workers: 1 (default, pinned in docker-compose)
- trials: 3
- warmup_requests_per_trial: 50
- requests_per_trial: 100
- concurrency_levels: [1, 2, 5, 10, 20, 40, 60, 100]
- httpx_max_connections: 200
- httpx_max_keepalive_connections: 100
- provider: local mock (instant response)

Methodology: asyncio semaphore-bounded concurrency; local mock provider;
cache bypassed; single gateway worker (GATEWAY_WORKERS pinned, see
infra/docker-compose.yml). Each trial re-warms the connection pool before
its measured sweep; RPS/latency are averaged across the 3 trials with
stdev shown so run-to-run variance is visible rather than hidden.
