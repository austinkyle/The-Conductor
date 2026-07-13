# The Conductor

The Conductor is an OpenAI-compatible transparent proxy that adds a two-layer cache, multi-provider failover, per-key budget enforcement, and a live observability dashboard to any stack already calling the OpenAI API.

```mermaid
graph LR
    Client -->|POST /v1/chat/completions| GW[Gateway]
    GW -->|SHA-256 exact match| Redis[(Redis)]
    GW -->|cosine ANN| PG[(Postgres pgvector)]
    GW -->|walk_chain| Anthropic
    GW -->|walk_chain| OpenAI
    GW -->|request row| PG
    Dashboard -->|GET /v1/observability/*| GW
```

---

## Quickstart

One changed line. Same SDK. Done. (Point `base_url` at your gateway — the self-host
command below brings one up on `localhost:8000`.)

```python
import openai
client = openai.OpenAI(base_url="http://localhost:8000/v1", api_key="dev-key")
print(client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":"hello"}]).choices[0].message.content)
```

---

## Architecture Decisions

These are the four decisions that shaped the design. Each one had a real alternative — the choice is the argument.

### ADR-001 — OpenAI-shape contract

**Decision:** Speak the OpenAI Chat Completions shape, not a custom API.

**Rejected:** A clean custom internal contract.

**Why:** Adoptability. Any SDK, LangChain instance, or LlamaIndex pipeline already works by changing one `base_url`. The coupling cost — a real translation layer per provider — is accepted and isolated behind a per-provider `Adapter` interface. A "universal" internal message format would be a third shape to maintain for two providers; the adapter pair is less code and the provider differences are mapped explicitly.

---

### ADR-002 — Cache after stream completion; failover only pre-first-token

**Decision:** Assemble and persist the cache entry once the stream closes. Fail over only before the first token is yielded.

**Rejected:** Mid-stream failover.

**Why:** Once the client has partial output it cannot cleanly retry elsewhere — continuing on a second provider produces a corrupt stream with a seam in the middle. The status peek in `_stream_attempt` runs inside `walk_chain` before any chunk is yielded; if the upstream returns 4xx/5xx, the chain cascades to the next candidate with no partial output sent. This constraint is honest and testable; pretending mid-stream failover is clean is not.

---

### ADR-003 — pgvector over a dedicated vector database

**Decision:** Semantic-cache vectors live in Postgres via the pgvector extension.

**Rejected:** A standalone vector database (Pinecone, Qdrant, Weaviate).

**Why:** One fewer piece of infrastructure. Postgres is already in the stack for the request log; gateway-cache scale does not need a specialized store. The HNSW cosine index in pgvector is fast enough for the access pattern (single ANN lookup per request, sub-millisecond on a warm index). Fewer moving parts beat marginal index-query performance at this scale.

---

### ADR-004 — FastAPI/Python over Go/Rust

**Decision:** Async FastAPI.

**Rejected:** Go or Rust for "infrastructure credibility."

**Why:** A clean, well-tested async implementation in the operated stack beats shaky code in a language the team does not operate. Gateway overhead measured at 2.3 ms p50 — well within bounds for a proxy. The hot path can be ported to Go later as a victory lap, not the build.

---

## Benchmark Results

All numbers from `bench/reports/` — run against a local mock provider on loopback, single uvicorn worker.

| Benchmark | Result |
|---|---|
| Overhead p50 | 2.3 ms added over direct provider call |
| Overhead p95 | 2.8 ms added |
| Overhead p99 | 3.1 ms added |
| Cache hit rate | 25.0% (50/200 exact hits under bench corpus) |
| Failover success rate | 100% (200/200 when primary returns 503) |
| Throughput peak | ~730 RPS (single worker, saturation at ~5 concurrent) |

**Methodology:** Direct p50 = 0.6 ms (loopback mock). Cache bypassed for overhead and throughput benches (`cache: {no_cache: true}`). `FALLBACK_BACKOFF_BASE_MS=0` for failover timing. Semantic cache skipped in bench run (no live `OPENAI_API_KEY`); exact-cache hit rate reflects the 50-question paraphrase corpus with identical repeats.

---

## Self-Host

```bash
OPENAI_API_KEY=sk-... ANTHROPIC_API_KEY=sk-... docker compose -f infra/docker-compose.yml up
```

Health check:

```bash
curl http://localhost:8000/health
# → {"status":"ok","db":true,"redis":true}
```

See [gateway/DEPLOY.md](gateway/DEPLOY.md) for the Fly.io runbook.

---

## Live Demo

No hosted instance is currently running. Bring one up locally with the **Self-Host**
command above, or deploy your own to Fly.io following [gateway/DEPLOY.md](gateway/DEPLOY.md).

---

## Future Work / Deliberately Out of Scope

**Mid-stream failover** — not supported by design (ADR-002). Once the client has partial output, retrying elsewhere produces a corrupt stream.

**Third provider** — adding one requires a new adapter in `translation/` but is otherwise mechanical. Excluded as scope discipline; two providers are sufficient to demonstrate the pattern.

**Semantic threshold validation** — `bench/cache_bench.py --mode=similarity` sweeps thresholds 0.80–0.99 against the paraphrase corpus and measures precision/recall, but requires a live `OPENAI_API_KEY`. Run it to replace the 0.92 placeholder before production use.

**Dashboard authentication** — the six observability endpoints are read-only and unauthenticated. Restrict in production behind a reverse proxy (e.g., nginx `auth_basic`, Fly.io `[http_service.checks]`).

**Horizontal scale** — Redis spend counters use `INCRBYFLOAT` (atomic); asyncpg connections are per-process. Multiple workers or machines work correctly but are not load-tested.
