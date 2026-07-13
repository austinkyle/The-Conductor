## Semantic Cache Similarity Threshold — 2026-07-13

### Methodology
- Eval set: `bench/data/similarity_eval.jsonl`, 160 hand-labeled request pairs
  across 4 domains (customer support, coding Q&A, doc lookup, data queries).
- **This is synthetic, hand-labeled data, not captured production traffic.** It is
  designed to stress-test the threshold with adversarial near-miss cases, not to
  represent real query distributions.
- Classes: `true_duplicate` (60 pairs, a cache hit is correct), `near_miss_trap`
  (60 pairs, high lexical overlap but different intent — a cache hit here is a
  wrong-answer bug), `unrelated` (40 pairs, sanity floor).
- Embedding model: text-embedding-3-small via EMBEDDING_API_BASE. Unique strings are
  deduped before embedding (210 embedding calls for 160 pairs).

### Threshold sweep (0.80 → 0.99, step 0.01)
| Threshold | TPR (dupes hit) | Trap FPR (traps wrongly hit) | Unrelated hit rate | Effective hit rate* |
|-----------|------------------|-------------------------------|---------------------|----------------------|
| 0.80 | 58.3% | 40.0% | 0.0% | 27.3% |
| 0.81 | 53.3% | 35.0% | 0.0% | 24.8% |
| 0.82 | 50.0% | 33.3% | 0.0% | 23.3% |
| 0.83 | 43.3% | 30.0% | 0.0% | 20.3% |
| 0.84 | 38.3% | 23.3% | 0.0% | 17.7% |
| 0.85 | 36.7% | 23.3% | 0.0% | 17.0% |
| 0.86 | 30.0% | 23.3% | 0.0% | 14.3% |
| 0.87 | 23.3% | 23.3% | 0.0% | 11.7% |
| 0.88 | 18.3% | 21.7% | 0.0% | 9.5% |
| 0.89 | 16.7% | 16.7% | 0.0% | 8.3% |
| 0.90 | 8.3% | 13.3% | 0.0% | 4.7% |
| 0.91 | 5.0% | 11.7% | 0.0% | 3.2% |
| 0.92 | 5.0% | 8.3% | 0.0% | 2.8% |
| 0.93 | 5.0% | 5.0% | 0.0% | 2.5% |
| 0.94 | 1.7% | 3.3% | 0.0% | 1.0% |
| 0.95 | 0.0% | 1.7% | 0.0% | 0.2% |
| 0.96 | 0.0% | 1.7% | 0.0% | 0.2% |
| 0.97 | 0.0% | 1.7% | 0.0% | 0.2% |
| 0.98 | 0.0% | 1.7% | 0.0% | 0.2% |
| 0.99 | 0.0% | 1.7% | 0.0% | 0.2% |

\* Effective hit rate assumes an illustrative traffic mix of
40% true duplicates /
10% near-miss traps /
50% unrelated. This mix is an assumption for
illustration, not a measurement of production traffic.

### Selection
Rule: choose the highest threshold-derived hit rate subject to trap false-positive
rate ≤ 1%. Wrong answers are a correctness bug — we sacrifice hit rate for
correctness, never the reverse.

### Root cause: no threshold in range meets the ≤1% target
The strictest true-duplicate pair in the eval set scores **0.9425** cosine
similarity. At least one near-miss trap scores *higher* than that:
- `0.9925` — customer_support: 'How do I track order #4521?' vs 'How do I track order #4522?'
- `0.9487` — data_queries: "What's the churn rate for the last 30 days?" vs "What's the churn rate for the last 90 days?"

Because a trap out-scores the closest true duplicate, no single global threshold can
admit that duplicate while excluding that trap — this is a structural limit of
cosine-similarity thresholding on this embedding model for numeric/ID-bearing
near-misses (e.g. differing only by an order number), not a threshold-tuning problem.
Raising the threshold further does not improve safety against this failure class; it
only destroys recall that would otherwise be safe.

**Recommended interim threshold: 0.95**
- True-positive rate: 0.0%
- Trap false-positive rate: 1.7%
- Unrelated hit rate: 0.0%

This does **not** meet the ≤1% correctness target — see Root Cause above. It is the lowest threshold that reaches the measured trap-FPR floor (1.7%); it is reported as the safest available single-threshold setting, not as a passing result. Closing the remaining gap requires a non-similarity guard (e.g. bypassing the cache when the two requests' numeric literals/IDs differ), which is out of scope for this measurement-only step and is recommended as follow-up work.

### Limitations
Validated on synthetic pairs; production traffic may differ in phrasing, domain mix,
and adversarial density. `SEMANTIC_SIMILARITY_THRESHOLD` remains configurable per
deployment for this reason — re-run this sweep against real (anonymized) query pairs
once production traffic is available.
