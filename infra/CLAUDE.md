# infra/ — self-host & deploy

## Routing table
| Task type | READ | SKIP | Tools / Skills |
|---|---|---|---|
| docker-compose | infra/docker-compose.yml | all source modules | — |
| Deploy live demo | infra/ deploy notes | dashboard internals | Fly.io / VPS |
| Secrets wiring | infra/.env handling, .env.example | — | — |

## Invariants
- One-command self-host via docker-compose. The title promises a *deployed* instance — there must be a working live URL.
- Secrets via env only. .env is gitignored; .env.example documents the variable names with no values.
