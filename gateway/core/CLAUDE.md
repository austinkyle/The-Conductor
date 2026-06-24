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

## As built — streaming (Phase 2)
- `pipeline._prepare` is the shared setup for both branches (parse → resolve → adapter → key → out_body). `proxy_chat_completion` is non-streaming; `stream_chat_completion` is the SSE path. `app/main.py` branches on the `stream` flag to pick `StreamingResponse` vs `JSONResponse`.
- `streaming.py` is the engine: `iter_sse` (parse provider SSE lines → `SSEEvent`), `sse_encode` (chunk dict → SSE frame), `stream_openai` (forward live + buffer text + reconcile usage). Adapters yield OpenAI `chat.completion.chunk` dicts; the engine never branches on provider.
- At stream close the engine stashes `req.usage` (reconciled) and `req.assembled_content` (buffered text) for Phase 4 (cache) / Phase 5 (budgets); it emits its own `data: [DONE]`.
- The upstream status is checked at stream open only — a `>=400` raises before the first token. No mid-stream failover (ADR-002).
