## Throughput Benchmark — 2026-07-13

Provider: local mock (instant response)
Requests per level per trial: 100
Trials: 3 (each a full sweep across all concurrency levels, with its own warmup)

### Mean across trials (per concurrency level)

| Concurrency | RPS     | RPS stdev | p50 (ms) | p95 (ms) | p99 (ms) |
|-------------|---------|-----------|----------|----------|----------|
| 1           | 215.5   | 28.6    | 4.4      | 7.7      | 8.8      |
| 2           | 309.2   | 68.4    | 6.0      | 9.3      | 14.3     |
| 5           | 623.9   | 110.6   | 7.6      | 10.8     | 13.8     |
| 10          | 581.0   | 97.8    | 15.5     | 27.9     | 34.4     |
| 20          | 459.6   | 118.4   | 35.5     | 86.3     | 108.8    |
| 40          | 377.1   | 30.5    | 76.1     | 212.4    | 250.9    |
| 60          | 365.7   | 25.1    | 117.2    | 248.5    | 261.3    |
| 100         | 287.8   | 115.2   | 209.4    | 358.0    | 380.5    |

Saturation point: ~10 concurrent requests (mean p95 first exceeds 2x baseline 7.7 ms)
Peak sustained RPS: mean=634.0, stdev=101.5 (trial 1: 751.1, trial 2: 580.6, trial 3: 570.4)

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
