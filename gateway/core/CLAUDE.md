# core/ — request lifecycle & streaming

Owns the FastAPI app entrypoint, the provider-agnostic request abstraction, and
the SSE streaming engine. The request abstraction is streaming-aware from day one.

## Routing table
| Task type | READ | SKIP | Tools / Skills |
|---|---|---|---|
| Add/modify an endpoint | core/, gateway/app/ | translation/, cache/, dashboard/ | FastAPI docs |
| Streaming (SSE) work | core/streaming.py, translation/ stream adapters | cache/, budgets/ | httpx async streaming |
| Wire a cross-cutting concern (cache/route/budget) into the request path | core/pipeline.py + the one module being wired | the other feature modules | — |

## Invariants
- Non-streaming path is built first, but the request object is streaming-aware.
- Failover decisions happen here BEFORE the first token is sent (see routing/).
