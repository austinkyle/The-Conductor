# Deploy to Fly.io — copy-paste runbook

Live URL: **https://conductor-demo.fly.dev** (already deployed — this doc also
covers what running it looked like end to end).

All commands run from `conductor/gateway/` (the directory containing `fly.toml` and `Dockerfile`).

---

## Prerequisites

### 1. Install flyctl, log in, add a payment method

```bash
brew install flyctl
fly auth login
```

Fly requires a payment method on the org before it will start **any** machine,
even on the free allowance — without one, `fly launch`/`fly deploy` fails with
`requested machine count exceeds organization limit`, which reads like a quota
problem but is actually a missing-card problem. Add a card at
https://fly.io/dashboard → your org → Billing before proceeding.

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
fly launch --no-deploy --copy-config --name conductor-demo
```

Accept the defaults. The `fly.toml` already exists, so `--copy-config` reuses it
(flyctl reformats it — quoting/ordering changes, content is unchanged — plus it
appends a `[[vm]]` block sizing the machine; `shared-cpu-1x`/1 GiB is enough).

### Step 2 — Set secrets, all in one shell invocation

```bash
export NEON_DATABASE_URL="postgresql://…neon…?sslmode=require"
export UPSTASH_REDIS_URL="rediss://…upstash…"
source ../.env   # for OPENAI_API_KEY / ANTHROPIC_API_KEY, if kept there

fly secrets set \
  DATABASE_URL="$NEON_DATABASE_URL" \
  REDIS_URL="$UPSTASH_REDIS_URL" \
  OPENAI_API_KEY="$OPENAI_API_KEY" \
  ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  --app conductor-demo
```

**This must be one shell invocation.** A shell / an agent tool that runs each
command as a separate process only shares the working directory across calls,
not exported variables — export the URLs in one call, then reference them in a
*different* call, and `fly secrets set` receives empty strings for all four
secrets silently. `fly secrets list` will show identical digests for
`DATABASE_URL` and `REDIS_URL` in that failure mode (both empty), and the
deployed machine crash-loops trying to connect to `127.0.0.1:5432` (the
pydantic-settings default) — see Troubleshooting.

### Step 3 — Add the demo/bench API keys

`gateway/db/migrations/009_seed_demo_keys.sql` seeds two budget-capped keys the
same way `005_seed_api_key.sql` seeds `dev-key` (`encode(sha256(...), 'hex')`,
`ON CONFLICT (key_hash) DO NOTHING` — never edit an applied migration, this one
is additive):

- `demo-key` — `hard_limit_cents=1000` ($10.00 hard cap), `soft_limit_cents=800`. Meant to be shared publicly; the cap is the point (see README's Live Demo section).
- `bench-key` — `hard_limit_cents=2500` ($25.00 hard cap), for internal benchmark runs, kept separate so bench traffic can't burn the public key's budget.

This migration is already committed and applies automatically in Step 4 along
with 001–008. No separate action needed unless you're adding a third key later.

### Step 4 — Deploy

```bash
fly deploy --app conductor-demo
```

The Dockerfile CMD runs `python -m db.migrate` (applies every migration up to
009: schema, seed providers/models/routes, `dev-key`, `demo-key`/`bench-key`)
then starts uvicorn on port 8000.

---

## Verify

```bash
# 1. Check logs — expect migrations listed as applied, then uvicorn started.
# `fly logs` streams forever and never exits on its own; background it and
# kill it after a few seconds rather than waiting for it to finish.
fly logs --app conductor-demo & LOGPID=$!; sleep 8; kill $LOGPID

# 2. Health check
curl https://conductor-demo.fly.dev/health
# → {"status":"ok","db":true,"redis":true}

# 3. Live completion (uses the seeded demo-key)
curl https://conductor-demo.fly.dev/v1/chat/completions \
  -H "Authorization: Bearer demo-key" \
  -H "Content-Type: application/json" \
  -d '{"model":"fast","messages":[{"role":"user","content":"hello"}]}'
# → OpenAI-shaped JSON response
```

### Cache-hit and failover checks

`fallback_depth` and `cache_status` are DB columns, never returned to the HTTP
client — read them back via `GET /v1/observability/failovers` and
`GET /v1/observability/cache` instead of looking for a response header.

To demo failover: point one alias's primary provider at a dead endpoint
(`UPDATE providers SET base_url = 'http://127.0.0.1:1' WHERE name = 'openai'`
against the Neon connection string), send a completion through that alias,
confirm it still succeeds (served by the fallback provider) and that
`/v1/observability/failovers` shows a fresh row with `fallback_depth: 1`, then
restore `base_url`.

**Two gotchas that will produce a false "no failover happened" result:**
- Send a request with unique content each time
  (e.g. `f"...nonce-{random.randint(...)}..."`). Identical repeated requests
  hit the **exact cache** and never reach any provider.
- Add `"cache": {"no_cache": true}` to every request body in the demo anyway.
  Near-duplicate phrasing (e.g. two "nonce-N: ..." variants differing only by
  a number) can still cross the **semantic** cache's cosine-similarity
  threshold and replay a cached response from a different provider than the
  one that's actually live right now — this looks exactly like failover
  silently not reverting, but it's a cache hit, not a routing bug.

---

## Running the `bench/` benchmark harness against this instance

`bench/overhead.py` / `bench/throughput.py` / `bench/failover_bench.py` are
built for `docker compose` + a local mock provider (see `bench/README.md`),
not a remote target — there's no `--base-url` flag. They *can* still produce
an honest "measured on this instance" number, by running unmodified **on the
Fly VM itself** against the gateway process already listening on
`localhost:8000` there:

```bash
# One-time per machine: get the scripts onto it (ephemeral disk — redo after
# any redeploy or restart).
fly ssh console -a conductor-demo -C "mkdir -p /app/bench"
for f in overhead.py throughput.py failover_bench.py _config.py _db.py _mock_server.py; do
  fly ssh sftp put "bench/$f" "/app/bench/$f" -a conductor-demo
done

# host.docker.internal is a docker-compose-ism; the Fly VM isn't a docker
# host, so alias it to localhost or the scripts' mock-provider URL won't resolve.
fly ssh console -a conductor-demo -C \
  "sh -c 'grep -q host.docker.internal /etc/hosts || echo \"127.0.0.1 host.docker.internal\" >> /etc/hosts'"

# The scripts' seeded bench provider references a BENCH_MOCK_KEY env secret
# (set in infra/docker-compose.yml locally); the Fly machine doesn't have it.
# Set it as a real (dummy-value) Fly secret for the run, then unset it after —
# it's not a real credential, just a lookup key the mock accepts unchecked.
fly secrets set BENCH_MOCK_KEY=bench-dummy-000 --app conductor-demo

# Fly auto-stops the machine when its *edge-proxied* http traffic goes idle —
# bench traffic here is all-loopback and invisible to that proxy, so the
# machine can suspend itself mid-run. Keep a public health-check hitting it
# from outside for the duration of the bench run.
( while true; do curl -s -o /dev/null https://conductor-demo.fly.dev/health; sleep 3; done ) &
PINGER=$!

fly ssh console -a conductor-demo -C "sh -c 'cd /app && . .venv/bin/activate && python bench/overhead.py'"
fly ssh console -a conductor-demo -C "sh -c 'cd /app && . .venv/bin/activate && python bench/throughput.py'"
fly ssh console -a conductor-demo -C "sh -c 'cd /app && . .venv/bin/activate && python bench/failover_bench.py'"

kill $PINGER
fly ssh sftp get /app/bench/reports/<report>.md bench/reports/<report>.md -a conductor-demo
fly secrets unset BENCH_MOCK_KEY --app conductor-demo
```

Do **not** run `bench/cache_bench.py --mode=gateway` against this instance —
it calls `redis.flushdb()` and `DELETE FROM semantic_cache` to start from a
clean slate, which is safe against a disposable local stack but would wipe the
live instance's real cache state and, since budget counters live in the same
Redis keyspace (`budget:{api_key_id}:{YYYY-MM}`), reset `demo-key`'s and
`bench-key`'s spend to zero. Run that one locally only.

Expect the overhead/throughput numbers measured this way to look *worse* than
a local docker-compose run, not better — Neon and Upstash are reached over the
public internet from the VM instead of over loopback, so every request now
pays two real round trips it didn't pay locally. That's an honest cost of this
deployment topology, not a gateway regression; see README's Benchmark Results
section for the actual figures and a full explanation.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `requested machine count exceeds organization limit` | No payment method on the Fly org | Add a card in the Fly dashboard, even for free-tier usage |
| `CREATE EXTENSION vector` fails | DB has no pgvector | Use Neon, not Fly Postgres |
| Machine crash-loops connecting to `127.0.0.1:5432` | Secrets were set to empty strings (see Step 2's atomicity note) | Redo `fly secrets set` with everything in one shell invocation, then `fly deploy` again |
| `fly secrets list` shows identical digests for two different secrets | Both were set to the same (likely empty) value | Same fix as above |
| `ValidationError: anthropic_api_key` | Secret not set | Run Step 2 with ANTHROPIC_API_KEY |
| 401 on completion | Wrong auth header | Use `Authorization: Bearer demo-key` (or `bench-key`/`dev-key`) |
| Cold start timeout | min_machines_running=0 | Normal — first request wakes the machine (~2s) |
| `fly logs` never returns | It streams indefinitely by design | Background it and `kill` after a few seconds, or use `fly logs` interactively in a real terminal |
| `missing provider secret: BENCH_MOCK_KEY` when running a bench script on the VM | `BENCH_MOCK_KEY` is a docker-compose-only env var, not a Fly secret | Set it as a temporary Fly secret for the bench run (see above), unset it after |
| Failover demo shows no failover, or shows the wrong provider after restoring | Exact- or semantic-cache hit, not a routing bug | Use unique content per request and `"cache": {"no_cache": true}` on every request (see Verify section) |
