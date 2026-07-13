## Failover Benchmark — 2026-07-13

Chain: Provider A (always-503 mock, port 9002) → Provider B (always-200 mock, port 9003)
Requests: 200 sequential

| Outcome           | Count | %     |
|-------------------|-------|-------|
| success (depth=0) | 0     | 0.0%  |
| success (depth=1) | 200   | 100.0%  |
| error             | 0     | 0.0%  |

Latency (successful requests, from gateway DB column latency_ms):
| Percentile | depth=0 (ms) | depth=1 (ms) | Failover penalty (ms) |
|------------|-------------|--------------|----------------------|
| p50        | —            | 576.0        | —                     |
| p95        | —            | 580.0        | —                     |
| p99        | —            | 591.3        | —                     |

Methodology: local mock servers on loopback; set FALLBACK_BACKOFF_BASE_MS=0 in the
gateway environment for accurate failover-only overhead (without backoff sleep noise).
Cache bypassed via `"cache": {"no_cache": true}` on all requests.
