## Cache Benchmark — 2026-06-25

### Hit Rate (gateway mode, threshold=0.92)
Corpus: 50 unique + 50 exact-duplicate + 100 semantic-paraphrase = 200 requests

| cache_status  | count | %     |
|---------------|-------|-------|
| exact_hit     | 50    | 25.0% |
| semantic_hit  | 0     | 0.0% |
| miss          | 150   | 75.0% |

Cost reduction: 0.01¢ saved on 50 cache hits
(based on gpt-4o-mini pricing of $0.15/$0.60 per Mtok)

Methodology: paraphrase corpus hand-crafted to test semantic similarity;
gateway mode uses the live gateway with threshold from SEMANTIC_SIMILARITY_THRESHOLD env var.
