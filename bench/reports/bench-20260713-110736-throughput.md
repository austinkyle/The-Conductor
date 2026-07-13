## Throughput Benchmark — 2026-07-13

Provider: local mock (instant response)
Requests per level per trial: 100
Trials: 3 (each a full sweep across all concurrency levels, with its own warmup)

### Mean across trials (per concurrency level)

| Concurrency | RPS     | RPS stdev | p50 (ms) | p95 (ms) | p99 (ms) |
|-------------|---------|-----------|----------|----------|----------|
| 1           | 179.0   | 25.6    | 5.1      | 8.7      | 12.4     |
| 2           | 267.9   | 8.3     | 6.7      | 11.3     | 12.7     |
| 5           | 598.0   | 151.5   | 8.2      | 11.6     | 13.9     |
| 10          | 605.7   | 79.6    | 14.5     | 26.3     | 34.5     |
| 20          | 575.2   | 181.1   | 30.4     | 65.0     | 86.7     |
| 40          | 341.4   | 18.4    | 87.2     | 237.5    | 272.3    |
| 60          | 326.6   | 9.8     | 130.0    | 273.2    | 289.4    |
| 100         | 339.5   | 27.8    | 158.6    | 265.5    | 278.9    |

Saturation point: ~10 concurrent requests (mean p95 first exceeds 2x baseline 8.7 ms)
Peak sustained RPS: mean=665.6, stdev=123.4 (trial 1: 772.7, trial 2: 530.7, trial 3: 693.3)

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
