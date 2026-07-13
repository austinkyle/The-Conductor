## Throughput Benchmark — 2026-07-13

Provider: local mock (instant response)
Requests per level per trial: 100
Trials: 3 (each a full sweep across all concurrency levels, with its own warmup)

### Mean across trials (per concurrency level)

| Concurrency | RPS     | RPS stdev | p50 (ms) | p95 (ms) | p99 (ms) |
|-------------|---------|-----------|----------|----------|----------|
| 1           | 4.5     | 0.0     | 218.7    | 224.8    | 298.0    |
| 2           | 9.0     | 0.0     | 219.7    | 226.6    | 256.5    |
| 5           | 21.2    | 1.5     | 220.2    | 242.8    | 672.4    |
| 10          | 40.0    | 4.7     | 220.7    | 283.4    | 689.9    |
| 20          | 43.5    | 1.5     | 432.8    | 637.5    | 720.3    |
| 40          | 42.4    | 2.1     | 871.6    | 1134.7   | 1547.9   |
| 60          | 41.9    | 0.1     | 1123.3   | 1823.3   | 1853.1   |
| 100         | 32.6    | 1.0     | 1727.3   | 2747.4   | 2855.4   |

Saturation point: ~20 concurrent requests (mean p95 first exceeds 2x baseline 224.8 ms)
Peak sustained RPS: mean=43.7, stdev=1.5 (trial 1: 42.0, trial 2: 44.8, trial 3: 44.4)

### Run configuration
- host_arch: x86_64
- host_cpu: AMD EPYC
- host_ram: 0.9 GiB
- os: Linux 6.12.91-fly
- python: 3.11.15
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
