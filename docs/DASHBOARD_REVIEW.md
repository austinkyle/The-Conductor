# Dashboard Redesign Review — D1 (dark theme, cc20d2f) + D2 (motion layer, 538f63c)

Reviewed 2026-07-13 against baseline 1c01f86 (commit before D1). Everything below was
verified by **running** — clean install, production build, live local stack
(docker compose gateway + postgres + redis), 52 real requests driven through the
gateway via `bench/cache_bench.py --mode=gateway`, and scripted Playwright sessions
(headless Chromium 1440×1000, normal and `prefers-reduced-motion: reduce`).

**Verdict: SHIP** (after the one blocker fix below, applied in this review as 5f1620a).

---

## 1. Build integrity — PASS

- `npm ci` from deleted `node_modules`/`.next`: clean.
- `npx tsc --noEmit` (tsconfig `strict: true`): no errors.
- `next build` production: compiled clean, lint clean, 4/4 static pages.
- **Bundle delta vs 1c01f86** (baseline rebuilt from a worktree with `npm ci`):
  - First Load JS for `/`: 220 kB → 252 kB (+32 kB, Next's uncompressed metric).
  - All static chunks, gzipped: 339.0 KB → 370.5 KB = **+31.5 KB gzip**.
  - Attributable to framer-motion (the only new dependency). Under the ~40 KB
    flag threshold — **not flagged**, but it is the majority of the page's own
    chunk growth; worth revisiting if more motion code lands.

## 2. Grep audits

| Check | Result |
|---|---|
| (a) Hardcoded hex in components | **FAIL → FIXED.** One violation: `MotionCard.tsx` `whileHover` used raw `#34344a`. Promoted to `--border-hover` token in globals.css and referenced via `var()` — commit 5f1620a. Hover verified live afterward: border rgb(38,38,58) → rgb(52,52,74). All other component color usage routes through tokens (`globals.css` is the only file containing hex, which is its job). |
| (b) localStorage/sessionStorage/cookies | **PASS.** Zero usages; the only match is the comment in `lib/api.ts` explaining that the token is memory-only. |
| (c) No gateway/ changes | **PASS.** `git diff --name-only 1c01f86..538f63c` touches only `dashboard/` and `docs/architecture/DECISIONS.md`. |
| (d) Bearer token never persisted/logged | **PASS.** Token lives in a module-level variable in `lib/api.ts`, sent only as an `Authorization` header. No `console.*` in dashboard code, token never appears in URLs (verified against 12 live requests), input is `type="password"`, `.env.local` contains only the gateway URL (no `NEXT_PUBLIC_DASHBOARD_AUTH_TOKEN` baked into the served bundle). |

## 3. Functional regression — PASS (all live, scripted)

Gateway was restarted with `DASHBOARD_AUTH_TOKEN=review-test-token-123` via a
compose override for the gating tests, then restored to the ungated dev default.

- **Token gating**: before Apply, 6 API calls returned 401 and zero metric cards
  rendered. After filling the input and clicking Apply, requests carried
  `Authorization: Bearer …` and data rendered. PASS.
- **Time-range switching**: clicking "24 hours" fired exactly 6 fresh requests, all
  with `window=24h`. PASS.
- **Per-key table**: renders real rows (`dev-key`, 2 requests, 17 tokens, 0.0007¢)
  from the live requests table. PASS.
- **Auto-refresh**: 6 network calls (one full fetch cycle) observed during a 35 s
  watch of the request stream — the 30 s interval fires. PASS.
- **Copy-on-click**: clipboard read back `dev-key`, exactly the key name, not the
  row text or "copied" suffix. PASS.

## 4. Visual/UX audit

Contrast ratios computed (WCAG relative luminance), not eyeballed:

| Pair | Ratio | AA |
|---|---|---|
| `--text-secondary` #8a8a9e on surface #111118 | 5.56 | pass |
| `--text-secondary` on page #0a0a0f | 5.84 | pass |
| `--text-primary` on surface | 16.11 | pass |
| `--success` / `--warn` / `--error` on surface | 9.78 / 11.26 / 6.80 | pass |
| `--accent` #8b5cf6 on surface | **4.44** | **fail for small text** (needs 4.5) |
| `--accent` on elevated pill #1a1a24 | **4.07** | **fail for small text** |

- **[SHOULD-FIX] Accent small-text contrast.** The accent passes as a graphic
  (3:1) and as large text (the 32 px metric suffixes), but it is also used for
  small text: the active segmented label (13 px, on the elevated pill, 4.07:1)
  and the "copied" tag (11 px, 4.44:1). A dedicated small-text accent —
  e.g. #a78bfa (6.9:1 surface / 6.3:1 pill) — for those two usages fixes it
  without touching the brand accent. Not auto-fixed: it's a palette decision.
- **tabular-nums**: computed style `font-variant-numeric: tabular-nums` confirmed
  on metric values; count-up digits were watched at 70 ms sampling with no layout
  jitter. PASS.
- **Zero states**: all five empty states are intentional (dot + one calm sentence,
  no giant illustrations). PASS, with one copy defect:
- **[SHOULD-FIX] Savings hint copy is false under real conditions.** Live state
  observed: cache card shows 96.2% hit rate / 50 exact hits, while the savings
  card says "**No cache hits yet in this window**" — because `SavingsCard` keys
  the hint on `cost_saved_cents === 0`, and saved cost can be 0 with plenty of
  hits (zero-priced/mock models; also plausible with very cheap models and
  rounding). The hint should key on hits, or say "No cost avoided yet".
  Behavioral copy/logic change — left for the author.
- **Accent discipline**: accent appears only as live dot, refresh sweep, chart
  line/fill, metric suffixes, active pill text, key names, focus ring. Well
  under ~10% of pixels. PASS.
- **Charts on dark**: grid dashed at `--border`, axis text `--text-secondary`
  (5.56:1), tooltip on surface with border. Legible. PASS.
- **[POLISH]** p50 latency bar renders 0 px wide when p50 = 0 ms (real cache-hit
  data) — indistinguishable from "no bar". A 2 px min-width keeps it honest and
  visible. The numeric "0 ms" label does carry the value.
- **[POLISH]** `--accent-fill` (#5e0ed7) is defined but unused (2.26:1 — unsafe
  for anything but fills). Remove it or comment it as fill-only.
- **[POLISH]** Zero savings renders as "0.0000¢" — four decimal places of zero
  reads odd; an em-dash or plain "0¢" would be calmer.

## 5. Motion audit — PASS

Full inventory (code + CSS): card entrance fade/rise with 70 ms stagger, card
hover lift, count-up, latency bar draw-in, segmented-control pill spring,
copy-tick fade, 30 s refresh-sweep progress bar, LIVE dot pulse.

- **Reduced motion** (Playwright `reducedMotion: 'reduce'`, production build):
  count-up instant (value identical at t=0 and t=1.2 s), LIVE dot
  `animation-duration: 0.01ms` (the global RM kill switch at globals.css:416),
  latency bars at final width by t+100 ms with no draw-in, entrances collapse to
  a 0.2 s opacity fade, sweep duration 0. PASS.
- **Count-up first-load-only**: on first load the hit-rate metric eased
  16.8 → 96.2% over ~600 ms; during a 35 s watch spanning an auto-refresh, values
  never dipped or re-counted. PASS.
- **One flourish**: latency bar draw-in is the only flourish. Nothing floats;
  the only pulse is the LIVE dot. PASS, with one judgment call to name:
  the **refresh sweep** is a second persistent motion element (a 2 px linear
  progress line at the viewport top, restarting every 30 s). It encodes real
  information (time to next refresh) rather than decoration, and it collapses
  under reduced motion, so I'm not counting it as a flourish violation — but if
  the brief's discipline is read strictly, it's the first thing to cut.

## 6. The screenshot test — PASS

Captured at 1440×1000 with 52 real gateway requests on the board (screenshots
exercised both gated and ungated modes; full-page captures show the fixed
refresh sweep mid-page — that's a capture artifact, not a UI bug; viewport
captures render it correctly at the top edge).

Skeptical read: this lands in the Linear/Vercel register, not themed-template.
What sells it: uppercase micro-labels, tabular mono numerals right-aligned in
real tables, honest sub-cent cost precision (0.0007¢), a latency card where p99
red at 1259 ms visually dominates two ~0 ms percentiles (that's information),
and quiet zero states. Nothing reads as pure decoration.

What still reads slightly demo: the spend chart with one lonely data point
floating in an empty plot (data-thin, not a code defect), and the contradictory
savings copy from §4 — that one *is* the kind of detail a skeptical engineer
catches in ten seconds, fix it before showing anyone.

---

## Findings summary

| Severity | Finding | Status |
|---|---|---|
| [BLOCKER] | Hardcoded `#34344a` in MotionCard hover (theme-token contract violation) | **Fixed** — 5f1620a |
| [SHOULD-FIX] | Savings hint says "No cache hits yet" when hits exist but saved cost is 0 | Open |
| [SHOULD-FIX] | Accent small text below AA: 4.44:1 (surface) / 4.07:1 (pill) on segmented label + copied tag | Open |
| [POLISH] | p50 bar invisible at 0 ms — add 2 px min-width | Open |
| [POLISH] | Unused `--accent-fill` token | Open |
| [POLISH] | "0.0000¢" zero-savings rendering | Open |

**Verdict: SHIP.** Both open SHOULD-FIXes are 10-line changes with no
architectural implications; neither gates the release, though the savings copy
should land before the dashboard is demoed with cheap/mock models.
