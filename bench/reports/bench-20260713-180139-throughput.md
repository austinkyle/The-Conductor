## Throughput Benchmark — 2026-07-13

Provider: local mock (instant response)
Requests per level per trial: 100
Trials: 3 (each a full sweep across all concurrency levels, with its own warmup)

### Mean across trials (per concurrency level)

| Concurrency | RPS     | RPS stdev | p50 (ms) | p95 (ms) | p99 (ms) |
|-------------|---------|-----------|----------|----------|----------|
| 1           | 2.1     | 0.0     | 480.6    | 511.4    | 649.2    |
| 2           | 4.2     | 0.0     | 477.9    | 490.4    | 518.2    |
| 5           | 9.8     | 0.4     | 478.9    | 564.5    | 1059.2   |
| 10          | 18.8    | 1.5     | 479.0    | 611.5    | 1021.9   |
| 20          | 19.8    | 1.1     | 949.1    | 1448.4   | 1704.2   |
| 40          | 20.2    | 0.5     | 1905.4   | 2038.5   | 3392.5   |
| 60          | 20.1    | 0.1     | 2680.7   | 2957.3   | 3310.0   |
| 100         | 18.3    | 0.6     | 2905.1   | 5089.2   | 5223.8   |

Saturation point: ~20 concurrent requests (mean p95 first exceeds 2x baseline 511.4 ms)
Peak sustained RPS: mean=20.5, stdev=0.1 (trial 1: 20.6, trial 2: 20.5, trial 3: 20.4)

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
- auth: bench-key

Methodology: asyncio semaphore-bounded concurrency; local mock provider;
cache bypassed; single gateway worker (GATEWAY_WORKERS pinned, see
infra/docker-compose.yml). Each trial re-warms the connection pool before
its measured sweep; RPS/latency are averaged across the 3 trials with
stdev shown so run-to-run variance is visible rather than hidden.
