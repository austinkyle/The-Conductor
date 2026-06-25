## Throughput Benchmark — 2026-06-25

Provider: local mock (instant response)
Requests per level: 100

| Concurrency | RPS     | p50 (ms) | p95 (ms) | p99 (ms) |
|-------------|---------|----------|----------|----------|
| 1           | 340.8   | 2.9      | 3.3      | 3.5      |
| 2           | 492.8   | 3.9      | 4.7      | 5.6      |
| 5           | 700.7   | 6.8      | 9.8      | 13.1     |
| 10          | 702.5   | 12.5     | 23.4     | 31.8     |
| 20          | 730.2   | 21.9     | 55.6     | 74.0     |
| 40          | 320.1   | 91.2     | 243.1    | 271.3    |
| 60          | 338.3   | 132.5    | 259.3    | 272.9    |
| 100         | 324.3   | 158.2    | 278.8    | 297.1    |

Saturation point: ~5 concurrent requests (p95 first exceeds 2× baseline 3.3 ms)
Peak sustained RPS: 730.2

Methodology: asyncio semaphore-bounded concurrency; local mock provider;
cache bypassed; single gateway process (uvicorn --workers 1 recommended).
