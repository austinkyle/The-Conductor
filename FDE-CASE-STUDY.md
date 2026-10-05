# The Conductor — FDE case study

## Evidence boundary

An implemented OpenAI-compatible gateway with benchmark reports dated July 2026. Code, test sources, and reports were inspected October 5, 2026. The deployed-reference benchmarks use mock providers; they are technical measurements, not customer traffic, adoption, real-work shadowing, or realized savings. Benchmarks were not rerun in this cleanup.

## 1. Observe: workflow and constraint

**Modeled workflow:** applications call model providers; an operator needs to control duplicate work, cost, provider failures, and visibility without requiring every caller to adopt a new API.

**Discovery still required:** examine permission-approved request patterns, error incidents, provider contracts, latency targets, cost attribution, privacy boundaries, and examples where a cached answer would be unsafe. Real query distributions and operator needs are not established by the synthetic benchmark corpus.

## 2. Route: software, AI, human

| Work | Owner | Evidence / reason |
| --- | --- | --- |
| Authenticate, normalize, check exact cache, walk fallback chain and account usage | Software | [Request pipeline](gateway/core/pipeline.py), [budget enforcement](gateway/budgets/enforce.py), [fallback](gateway/routing/fallback.py). Explicit execution rules. |
| Generate a response / embed semantic candidates | Model providers | [Provider adapters](gateway/translation/), [semantic cache](gateway/cache/semantic.py); similarity is probabilistic. |
| Decide cache eligibility and explicit bypasses | Software rules, with caller context | [Guardrails](gateway/cache/guardrails.py) bypass tool-use, high-temperature, and caller-marked fresh/no-cache requests. |
| Set acceptable reuse/cost/latency policy, approve access and handle incidents | Human operator | These are business and security tradeoffs, not model decisions. |

## 3. Design for failure

| Failure | Implemented response | Known limit |
| --- | --- | --- |
| Retryable upstream error before output | Ordered provider fallback with backoff | Terminal errors stop; there is no seamless mid-stream failover. |
| Stream fails after partial output | No mid-stream provider switch | Client/operator needs a defined recovery policy. |
| Similar request changes a numeric identifier | Threshold sweep documents a false-positive trap | No global threshold fixes the observed example; add exact ID/number checks or bypass. |
| Recorded spend exceeds budget | Pre-request check rejects subsequent work | Separate check and later accounting allow concurrent/in-flight overshoot. |
| Multiple tenants share a gateway cache | Cache lookup is request/model based | Tenant-specific isolation and safe reuse policies need design/validation before shared client data is introduced. |
| Deployment introduces remote DB/cache latency | Reports expose the slower authenticated topology | Colocation is a future architectural choice, not a measured improvement. |

## 4. Verify: preserve unfavorable results

The [deployed-reference report](bench/reports/bench-20260713-deployed-reference.md) records authenticated mock-provider measurements: 483.3 ms p50 added overhead and 20.5 mean requests/second at the reported peak. The local figures are from another environment. Neither proves production scale or current availability.

The [similarity evaluation](bench/reports/bench-20260713-similarity-threshold.md) uses synthetic labeled duplicate/near-miss/unrelated examples and documents a target it did not fully meet. Keep that failure visible. [Gateway tests](gateway/tests/) cover cache, routing, budget, streaming, translation, and authentication behavior with engineering fixtures.

Next: a permission-approved replay set from the intended application, evaluated for exact/semantic reuse correctness, tenant isolation, wrong-ID responses, fallback semantics, budget overshoot, and latency. Agree on acceptance criteria and run a shadow/bypass comparison before enabling reuse for business-critical requests.

## 5. Measure business value

Baseline provider spend, repeated requests, error rates, latency, incident time, and application correctness. Compare provider cost avoided with gateway/embedding/DB/cache costs and operator burden. A cache hit saves money only when reuse is appropriate; incorrect reuse and added latency can erase the gain. No realized savings or customer outcome is measured in these reports.

## Architecture choice, adoption, and next work

An OpenAI-shaped interface lowers integration work; adapter complexity, cache correctness, and deployment latency are its costs. Postgres plus Redis reuse familiar infrastructure, but managed-service network hops dominate the historical deployed overhead.

Actual employee/customer adoption is not demonstrated. Prioritize numeric/ID cache safety, tenant boundaries, budget reservation if a strict cap is required, and a measured operator trial before adding providers or promising infrastructure ROI.
