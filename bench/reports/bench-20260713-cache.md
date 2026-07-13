## Cache Benchmark — 2026-07-13

### Hit Rate (gateway mode, threshold=0.92)
Corpus: 50 unique + 50 exact-duplicate + 100 semantic-paraphrase = 200 requests

| cache_status  | count | %     |
|---------------|-------|-------|
| exact_hit     | 50    | 25.0% |
| semantic_hit  | 6     | 3.0% |
| miss          | 144   | 72.0% |

Cost reduction: 0.01¢ saved on 56 cache hits
(based on gpt-4o-mini pricing of $0.15/$0.60 per Mtok)

### Hit vs miss latency (gateway DB column latency_ms)
| Percentile | Hit (exact+semantic, ms) | Miss (ms) |
|------------|--------------------------|-----------|
| p50        | 124.0        | 457.5        |
| p95        | 359.0        | 760.8        |
| p99        | 427.4        | 2012.0       |

Auth: bench-key. Reset scope: exact-cache
keys deleted by hash, semantic_cache rows deleted by `model = 'bench-cache'` only —
non-destructive against a shared instance (no `flushdb`, no unscoped `DELETE`).

Methodology: paraphrase corpus hand-crafted to test semantic similarity;
gateway mode uses the live gateway with threshold from SEMANTIC_SIMILARITY_THRESHOLD env var.
