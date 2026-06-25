## Gateway Overhead — 2026-06-25

Hardware: arm64, Apple M1 Pro
Requests: 500 sequential
Provider: local mock (instant response, eliminates provider latency)

| Percentile | Direct (ms) | Gateway (ms) | Added overhead (ms) |
|------------|-------------|--------------|---------------------|
| p50        | 0.6         | 2.9          | 2.3                 |
| p95        | 0.8         | 3.6          | 2.8                 |
| p99        | 0.9         | 4.0          | 3.1                 |

Methodology: sequential asyncio requests, same process, loopback network.
Cache bypassed via `"cache": {"no_cache": true}` on every request.
