# SHIP REVIEW — adversarial pre-ship verification of S1–S6

Date: 2026-07-13. Reviewer: independent pass; every claim below was exercised, not read.
Method: fresh re-runs of the sweep and benchmarks, live requests against
https://conductor-demo.fly.dev, deliberate breakage of the migration regression test,
full local regression (pytest / mypy --strict / tsc / clean `docker compose up` /
verbatim README quickstart), and a full-history secrets scan.

---

## 1. S1 — Threshold: **PASS (with one disclosed, unresolved gap)**

**Ran:** `python bench/cache_bench.py --mode=similarity` with the live embedding key;
diffed the regenerated report against the committed
`bench/reports/bench-20260713-similarity-threshold.md`.

**Observed:**
- Re-run output is **byte-identical** to the committed report (embeddings are
  deterministic for this eval set). Numbers are real, not typed in.
- Shipped code default `semantic_similarity_threshold = 0.95`
  (`gateway/core/config.py:36`) matches the report's recommendation.
- **FPR at 0.95 is 1.7%, not ≤1%.** The report says so explicitly and explains why no
  global threshold can meet the target (a numeric-ID near-miss trap at 0.9925 out-scores
  the strictest true duplicate at 0.9425). This is honest disclosure of a real
  limitation, not a cosmetic pass — but the ≤1% acceptance criterion is **not met**.
- Synthetic-data limitation: stated in the report; was **missing from the README**
  ("labeled eval set" with no synthetic disclosure) — fixed in this review
  (commit `docs(readme): state synthetic eval-set limitation`).

**Related finding, escalated to blocker list:** the live deployment overrides the
measured default — see item 8, landmine L1.

## 2. S2 — Benchmark: **PASS (local column); deployed column spot-checked**

**Ran (local, per bench/README.md as a stranger, clean docker compose):**
- `overhead.py`: p50 **3.67 ms** / p95 8.19 / p99 11.20 → README "~3.6 / ~8.0 / ~12.0" ✅
- `throughput.py`: peak **546.3 RPS mean** (trials 618/495/526, stdev 64), saturation
  ~10 concurrent → README "~634 RPS, saturation ~10". 546 vs 634 is −13.8%, inside the
  README's own ±15% reproducibility bar, but at its edge; trial 1 alone (618) is well
  within. Not a contradiction, but "~634" is the optimistic end of the spread.
- `cache_bench.py --mode=gateway`: **25.0% exact** (50/200) → README 25.0% ✅.
  Semantic hits 0% locally at the 0.95 default (README's 3.0% semantic figure was
  measured on the deployed instance at threshold **0.92** — see L1).
- `failover_bench.py`: **100% (200/200) depth=1** → README 100% ✅.

**Ran (deployed, per gateway/DEPLOY.md runbook):** re-ran `overhead.py` on the Fly VM
as `bench-key` — fresh result: **p50 485.5 ms / p95 501.0 / p99 585.4** (stdev 0.75 /
2.35 / 42.1) vs the README's 483.3 / 503.0 / 634.8. p50 and p95 agree within 0.5%;
p99 differs but both runs show large p99 stdev (42–125 ms) — tail noise, not a
contradiction. **The deployed headline number is real.** Throughput/cache/failover
deployed rows were not re-run on the VM (methodology and reports verified; local
equivalents reproduced) — overhead was chosen as the spot-check because it is the
headline claim.

**Bugs found while reproducing:**
- `cache_bench.py --mode=gateway` and `failover_bench.py` write **date-only filenames**
  (`bench-20260713-cache.md`), so a fresh run silently **overwrites the committed
  deployed-reference reports**. My run clobbered both; restored from git. Landmine L4.
- The cache report header hardcoded "threshold=0.92" regardless of the gateway's actual
  setting (my 0.95 run was labeled 0.92). Fixed in this review
  (commit `fix(bench): don't hardcode threshold=0.92`).
- `bench/README.md` says `FALLBACK_BACKOFF_BASE_MS=0 python bench/failover_bench.py`,
  but that env var configures the **gateway at compose-up time**, not the bench script —
  my run still paid the 500 ms backoff (p50 512.5 ms). Instruction is ineffective as
  written. Landmine L5.

## 3. S3 — Deploy: **PASS (after one README correction)**

**Ran against https://conductor-demo.fly.dev with the OpenAI SDK:**
- Non-streamed completion (`model="fast"` → served `gpt-4o-mini-2024-07-18`): ✅ 4197 ms cold.
- Streamed completion: ✅ full SSE stream ("1, 2, 3, 4, 5.").
- Exact-cache repeat of the same request: ✅ **identical response id and content**, 979 ms
  vs 4197 ms — a real cache hit, not a re-generation.
- Anthropic path: `model="claude-sonnet-5"` → ✅ real Claude response.
- **Budget hard-block:** created a `hard_limit_cents=0` test key directly in the deployed
  DB (via `fly ssh`), called the live endpoint → **`402 {"detail":"budget exceeded: spent
  0 cents, limit 0 cents"}`**. Enforcement path is real, DB-driven, and the upstream is
  never called. Test key deleted afterward.
- **README said the block is a 429; the code and live instance return 402.** Fixed
  (commit `docs(readme): budget hard-block returns 402, not 429`).

**Secrets:** `.env` untracked and gitignored; full-history grep for `sk-proj|sk-ant`
across all revisions: clean (only `sk-ant-test` in CI env and a documented placeholder).
Image contains no `.env` (`fly ssh` ls of `/app`; Docker build context is `gateway/`,
which has no env file). `fly logs` grep for key fragments / `Bearer `: zero hits.

## 4. S4 — Auth: **PASS**

**Ran:** all six deployed observability endpoints (`spend cache latency savings
failovers keys`) with no token and with a wrong token → **401 in all 12 cases**.
Proxy routes unaffected (all S3 completions above succeeded with only the per-key
auth). Token committed nowhere: repo grep finds only variable *names*; the built
dashboard bundle (`npm run build`, grep of `.next/static`) contains only the literal
`"Bearer "` header prefix with no value — `dashboard/.env.local` holds no token, so a
build cannot bake one.

## 5. S5 — CI: **FAIL as specified (no CI run exists); mechanics verified locally**

**Observed:** the repo has **no git remote** — it has never been pushed, so there is no
CI run to read. `.github/workflows/ci.yml` is well-formed (pgvector service container,
`DATABASE_URL` set, pytest + mypy, dashboard tsc), but "read the latest CI run" is
unsatisfiable today. Landmine L2.

**Verified locally under CI-equivalent env:**
- Full suite: **111 passed, 0 skipped** — the `test_migrate.py` skip guards exist but do
  not fire when a DB is present, and CI's env provides one.
- Migration-chain tests ran (verbose run shows both `test_migrations_apply_idempotently`
  and `test_seeded_model_aliases_resolve_to_current_provider_models` PASSED, executing
  real `CREATE DATABASE` → migrate → drop).
- **Deliberate break:** edited `008_update_anthropic_models.sql` to seed
  `provider_model='claude-totally-fake-9'` → the regression test **FAILED** as designed
  (`by_alias == _EXPECTED_PROVIDER_MODELS` mismatch). Reverted; suite green again.

## 6. S6 — Refactor: **PASS**

**Ran:** `git show f4b8013 -- gateway/core/pipeline.py`; grepped current pipeline.py for
raw cache primitives; ran the cache test matrix; overhead trial (item 2).

**Observed:** genuinely single-path, not moved-and-duplicated: `exact.get` /
`semantic.lookup` appear **only** inside `_cache_lookup`, `exact.put` /
`semantic.store` only inside `_cache_write`, and both the non-streaming
(`pipeline.py:310,362`) and streaming (`pipeline.py:395,467`) branches call the same
helpers. The commit deleted 135 lines of duplicated logic and added 292 lines of tests.
Cache matrix (exact hit, semantic hit, miss, no_cache bypass, write-back, on both
paths): **65 tests passed**. Fresh overhead p50 3.67 ms is consistent with the pre-S6
dev-laptop figure (~3.6 ms) — no regression from the refactor.

## 7. Whole-repo regression: **PASS**

- `pytest`: 111 passed, 0 skipped, 0 failed.
- `mypy --strict` (`strict = true` in pyproject): **no issues in 41 source files**
  (requires the documented `pip install ".[dev]"` for asyncpg-stubs).
- Dashboard `tsc --noEmit`: clean. `npm run build`: succeeds.
- `docker compose down -v && up` from clean volumes: gateway healthy
  (`{"status":"ok","db":true,"redis":true}`), migrations applied on boot.
- README quickstart, verbatim, as a stranger: returns a real completion
  ("Hello! How can I assist you today?").

## 8. Buyer test — claims NOT fully backed by verification (the landmines)

- **[BLOCKER] L1 — The live deployment does not run the measured threshold.**
  `gateway/fly.toml:16` pins `SEMANTIC_SIMILARITY_THRESHOLD='0.92'` on conductor-demo,
  while the sweep, the README, and the code default all say **0.95**. At 0.92 the
  measured trap false-positive rate is **8.3%** — roughly 1 in 12 adversarial near-miss
  queries served a *wrong cached answer* on the flagship demo a buyer will poke at. The
  README's "3.0% semantic hit" deployed figure was earned at this unsafe setting. This
  is a behavioral config change (and would shift the deployed cache numbers), so it is
  **not fixed in this review** — decide: set fly.toml to 0.95 and re-run the deployed
  cache bench, or document the 0.92 override with its measured FPR. Silence is the one
  option that isn't honest.
- **[BLOCKER] L2 — No remote, no CI, no pushed history.** Every "CI passes" implication
  is untestable until the repo is pushed and a run is green. (S5's machinery is verified
  locally; the claim "CI runs this" is not.)
- **L3 — ADR-004 "low single-digit milliseconds p50"** is true only for the loopback
  topology; the deployed reference is 483 ms. The section does link to Benchmark Results,
  but a skeptical reader will call the sentence cherry-picked. Suggest "3–4 ms added on
  a loopback stack; see Benchmark Results for the deployed topology."
- **L4 — Bench reports are self-clobbering.** `cache`/`failover` reports use date-only
  filenames; any same-day re-run overwrites the committed reference evidence (happened
  during this review). Add timestamps like the other two benches.
- **L5 — `bench/README.md` failover instruction is ineffective** (`FALLBACK_BACKOFF_BASE_MS=0`
  must be set when the gateway starts, not when the bench runs).
- **L6 — ADR-003 "sub-millisecond on a warm index"** — not measured anywhere in the repo.
- **L7 — "~634 RPS" is the top of the local spread**; an independent run landed at 546
  mean. Within the stated ±15%, but quote the mean±stdev, not the best trial.
- **L8 — Throughput/README numbers are single-machine (`GATEWAY_WORKERS=1`)**; README
  says "not load-tested" for horizontal scale — honest, keep it.
- Verified and clean: live demo works (both providers, streaming, caching), budget cap
  enforces at 402, observability auth enforced on the deployed instance, no secrets in
  repo/history/image/logs/bundle, quickstart works verbatim, suite/typecheck green.

---

## Fixes applied during this review (one commit each, all docs/report-honesty only)

1. `docs(readme): state synthetic eval-set limitation in Future Work section`
2. `docs(readme): budget hard-block returns 402, not 429 (verified live)`
3. `fix(bench): don't hardcode threshold=0.92 in cache report header`

## Verdict: **DO-NOT-SHIP (two items stand in the way)**

1. **L1** — align the deployed threshold with the measured recommendation (set
   `SEMANTIC_SIMILARITY_THRESHOLD=0.95` in fly.toml + redeploy + re-run the deployed
   cache bench and update the README's semantic-hit figure), **or** document the 0.92
   override and its 8.3% measured trap-FPR wherever the demo is advertised. Behavioral —
   left to the owner.
2. **L2** — push the repo, get one green CI run, link it. Until then "CI enforces this"
   is an untested claim.

Everything else verified is real: the remediations were substantive, not cosmetic.
Fix L1 and L2 and this ships. L3–L7 are pre-diligence polish, not gates.
