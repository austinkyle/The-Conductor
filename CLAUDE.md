# The Conductor — Project Map (root CLAUDE.md)

> Behavioral contract for Claude Code, not documentation. Keep this file lean:
> it loads every session, and files >200 lines reduce instruction adherence.

## Read Order (token discipline — enforce every session)
1. Read THIS file first. It is the map.
2. Then read ONLY the `CLAUDE.md` of the module you are working in
   (e.g. `gateway/cache/CLAUDE.md`). Do not load other modules' context.
3. Nested CLAUDE.md files load on-demand when you read a file in that subtree.
   If you're unsure they loaded, explicitly open the module's CLAUDE.md before working.
4. Never load the whole repo into context. Route by the tables below.

## WAT framework
- **W — Workflows:** the build phases (see `docs/architecture/DECISIONS.md`) and the
  task routing tables inside each module's CLAUDE.md.
- **A — Agent:** you, Claude Code — read, plan, execute one module at a time.
- **T — Tools:** the module CLAUDE.md routing tables, the migrations in `gateway/db`,
  the benchmark harness in `bench/`, and any skills loaded on demand.

## Module map (Layer 2 — where to navigate by task)
| Module | Owns | Open when the task is... |
|---|---|---|
| `gateway/core/` | FastAPI app, request abstraction, SSE streaming engine | the request lifecycle / streaming |
| `gateway/translation/` | OpenAI<->provider format adapters (openai.py, anthropic.py) | adding/fixing a provider's format |
| `gateway/routing/` | model aliases, fallback chain, retryable-vs-terminal error classification, backoff | routing or failover |
| `gateway/cache/` | exact (Redis) + semantic (pgvector) cache, no-cache guardrails | caching behavior |
| `gateway/budgets/` | per-key cost accounting, soft-warn / hard-block enforcement | budgets / spend limits |
| `gateway/observability/` | request-log writes, dashboard read API | logging / metrics endpoints |
| `gateway/db/` | SQL migrations + data model (5 core tables) | schema changes |
| `dashboard/` | Next.js + TS observability UI | the dashboard |
| `bench/` | load/benchmark harness (asyncio/locust) | measuring proxy overhead / hit rate / failover |
| `infra/` | docker-compose, deploy, secrets wiring | self-host / deployment |
| `docs/architecture/` | running decision log (ADRs) — the seniority signal | recording a design tradeoff |

## Naming conventions
- Architecture decision records: `docs/architecture/ADR-[NNN]-[slug].md` (zero-padded, e.g. ADR-003-pgvector-over-dedicated-vectordb.md).
- Benchmark reports: `bench/reports/bench-[YYYYMMDD]-[scenario].md`.
- Python: snake_case modules, type-hinted, async by default. mypy strict.
- TS: strict mode, named exports.
- DB migrations: `gateway/db/migrations/[NNN]_[slug].sql` (sequential).

## Non-negotiable rules (the behavioral contract)
- Provider API keys / secrets are referenced via env, NEVER stored in the DB or committed. The DB holds a *reference*, not the secret.
- After completing a phase, append the decisions you made (and the alternatives you rejected) to `docs/architecture/DECISIONS.md`. This is graded.
- Two providers only (OpenAI-shape + Anthropic). Do not add a third. Scope discipline is the signal.
- When you finish a unit of work, update the relevant module's CLAUDE.md routing table if reality changed, then commit with a conventional-commit message.

## Code style contract — write the simplest human code, not enterprise code
Optimize for a human reading the file top-to-bottom in one pass. Apply on EVERY file:
- Functions over classes. Use a class only when there is real state to hold. A dict or a function beats a Factory/Manager/Registry.
- No abstraction until there are two concrete callers. The ONLY pre-justified abstractions are: the translation adapter interface, the fallback chain, the cache layer, the streaming engine. Do not introduce others speculatively.
- Standard library and well-known libraries first (httpx, fastapi, pydantic, redis, pgvector). Do NOT hand-roll what a proven library already does.
- Borrow the boring, write the interesting. Reference patterns for commodity glue (migration runner, rate limiter) are fine if understood and license-compatible. The translation, error classification, cache guardrails, and stream reconciliation are written from scratch — they are the point.
- Flat over nested. Early returns over deep if/else. Small files. If a module exceeds ~150 lines for what it does, it is probably over-abstracted — simplify.
- No comments that restate the code. Docstrings only where the WHY is non-obvious.
- No defensive code for inputs that cannot occur. No speculative config flags. Build only what the current phase needs.
