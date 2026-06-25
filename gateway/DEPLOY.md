# Deploy to Fly.io — copy-paste runbook

Live URL once deployed: **https://llm-gateway-demo.fly.dev**

All commands run from `llm-gateway/gateway/` (the directory containing `fly.toml` and `Dockerfile`).

---

## Prerequisites

### 1. Install flyctl and log in

```bash
brew install flyctl
fly auth login
```

### 2. Neon (Postgres + pgvector)

Create a free project at https://neon.tech.

- Neon ships `pgvector` built in — migration 001 does `CREATE EXTENSION IF NOT EXISTS vector`.
- **Do not** use `fly postgres create`; Fly's stock Postgres has no pgvector and migration 001 will fail.
- Copy the **pooled connection string** (ends with `?sslmode=require`).

### 3. Upstash (Redis)

Create a free database at https://upstash.com.

- Copy the `rediss://…` URL (TLS-enabled).

---

## Deploy

### Step 1 — Register the app

```bash
cd gateway
fly launch --no-deploy --copy-config --name llm-gateway-demo
```

Accept the defaults. The `fly.toml` already exists, so `--copy-config` reuses it.

### Step 2 — Set secrets

```bash
fly secrets set \
  DATABASE_URL="postgresql://…neon…?sslmode=require" \
  REDIS_URL="rediss://…upstash…" \
  OPENAI_API_KEY="sk-…" \
  ANTHROPIC_API_KEY="sk-ant-placeholder" \
  --app llm-gateway-demo
```

> `ANTHROPIC_API_KEY` is required by the config even if you only use OpenAI.
> Set it to a dummy value (`sk-ant-placeholder`) if you have no Anthropic key —
> the gateway only calls Anthropic when a model alias routes there, which the
> default seed data does not do for `gpt-4o-mini`.

### Step 3 — Deploy

```bash
fly deploy --app llm-gateway-demo
```

The Dockerfile CMD runs `python -m db.migrate` (creates tables, seeds providers /
models / dev-key via migrations 001–006) then starts uvicorn on port 8000.

---

## Verify

```bash
# 1. Check logs — expect: "applied: ['001_...', '002_...', ...]" then uvicorn started
fly logs --app llm-gateway-demo

# 2. Health check
curl https://llm-gateway-demo.fly.dev/health
# → {"status":"ok","db":true,"redis":true}

# 3. Live completion (uses the seeded dev-key)
curl https://llm-gateway-demo.fly.dev/v1/chat/completions \
  -H "Authorization: Bearer dev-key" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hello"}]}'
# → OpenAI-shaped JSON response
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `CREATE EXTENSION vector` fails | DB has no pgvector | Use Neon, not Fly Postgres |
| `ValidationError: anthropic_api_key` | Secret not set | Run Step 2 with ANTHROPIC_API_KEY |
| 401 on completion | Wrong auth header | Use `Authorization: Bearer dev-key` |
| Cold start timeout | min_machines_running=0 | Normal — first request wakes the machine (~2s) |
