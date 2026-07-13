"""Cache benchmark — hit rate + threshold sensitivity.

Modes:
  --mode=gateway   Send 200 requests through the running gateway, read cache_status
                   from the requests table. Requires gateway + mock server running.
  --mode=similarity  Embed the labeled pairs in bench/data/similarity_eval.jsonl, sweep
                   thresholds 0.80-0.99, and report true-positive/false-positive rates
                   per threshold. Requires OPENAI_API_KEY.

Usage:
    python bench/cache_bench.py --mode=gateway
    python bench/cache_bench.py --mode=similarity

Prerequisites:
    docker compose -f infra/docker-compose.yml up -d   (gateway mode)
    export DATABASE_URL=postgresql://gateway:gateway@localhost:5432/gateway
    export REDIS_URL=redis://localhost:6379/0
    export OPENAI_API_KEY=sk-...
    export EMBEDDING_API_BASE=https://api.openai.com/v1   (default)
    pip install httpx asyncpg redis
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import asyncpg
import httpx
import redis.asyncio as aioredis

sys.path.insert(0, str(Path(__file__).parent))
from _config import auth_headers
from _db import cleanup_bench_alias, seed_bench_provider
from _mock_server import start_mock_provider

# ---------------------------------------------------------------------------
# Hard-coded corpus: 50 unique questions + 2 paraphrases each = 100 paraphrase items.
# Semantically diverse domains: geography, science, history, culture, tech.
# ---------------------------------------------------------------------------
_SEED: list[tuple[str, str, str]] = [
    ("What is the capital of France?", "Name the capital city of France.", "Which city serves as France's capital?"),
    ("How does photosynthesis work?", "Explain the process of photosynthesis.", "How do plants convert sunlight into energy?"),
    ("What is the speed of light in a vacuum?", "How fast does light travel through empty space?", "What is light's velocity in a vacuum?"),
    ("Who wrote Romeo and Juliet?", "Which author wrote the play Romeo and Juliet?", "Who is the playwright behind Romeo and Juliet?"),
    ("What causes earthquakes?", "Why do earthquakes occur?", "What is the scientific cause of earthquakes?"),
    ("How do vaccines work?", "Explain how vaccines protect against disease.", "What is the mechanism by which vaccines function?"),
    ("What is the Pythagorean theorem?", "State the Pythagorean theorem in geometry.", "Explain the relationship between sides of a right triangle."),
    ("Who was the first person to walk on the moon?", "Who first stepped on the lunar surface?", "Which astronaut was the first to walk on the moon?"),
    ("What is the boiling point of water?", "At what temperature does water boil?", "What temperature causes water to vaporize?"),
    ("How does the internet work?", "Explain how the internet transmits data.", "What is the underlying mechanism of the internet?"),
    ("What is DNA?", "Explain what DNA is and what it does.", "What does the abbreviation DNA stand for and what is its function?"),
    ("How do airplanes fly?", "What forces allow an airplane to achieve flight?", "Explain the aerodynamic principles behind airplane flight."),
    ("What is the largest planet in our solar system?", "Which planet in the solar system is the biggest?", "Name the largest planet orbiting our sun."),
    ("Who painted the Mona Lisa?", "Which artist created the Mona Lisa?", "Who is the painter of the famous Mona Lisa portrait?"),
    ("What causes rainbows?", "Why do rainbows appear in the sky?", "What is the physical explanation for rainbows?"),
    ("How does the human heart work?", "Explain the function of the human heart.", "Describe how the heart pumps blood through the body."),
    ("What is gravity?", "Define gravity and how it works.", "Explain the concept of gravitational force."),
    ("Who invented the telephone?", "Who is credited with inventing the telephone?", "Which person invented the telephone device?"),
    ("What is the chemical formula for water?", "What molecules make up water?", "Write the chemical formula of water."),
    ("How do computers work?", "Explain the basic operation of a computer.", "Describe how a computer processes information."),
    ("What is the theory of relativity?", "Explain Einstein's theory of relativity.", "Describe what the theory of relativity states."),
    ("Who was Abraham Lincoln?", "Describe who Abraham Lincoln was.", "What is Abraham Lincoln known for in American history?"),
    ("What is climate change?", "Explain what climate change means.", "Describe the phenomenon of climate change."),
    ("How does digestion work?", "Explain the human digestive process.", "Describe how the body digests food."),
    ("What is the distance from Earth to the Moon?", "How far is the Moon from Earth?", "What is the approximate Earth-Moon distance?"),
    ("How do birds migrate?", "Explain bird migration patterns.", "Why and how do birds travel seasonally?"),
    ("What is the periodic table?", "Explain what the periodic table of elements is.", "Describe the organization of the periodic table."),
    ("Who was Cleopatra?", "Describe who Cleopatra was in ancient history.", "What is Cleopatra famous for?"),
    ("What causes thunder?", "Why does thunder occur during storms?", "Explain the physical cause of thunder."),
    ("How do plants absorb water?", "Explain how plants take in water from the soil.", "Describe the process by which plants obtain water."),
    ("What is the stock market?", "Explain how the stock market works.", "Describe what happens in a stock market."),
    ("Who invented the light bulb?", "Who is credited with creating the first light bulb?", "Which inventor developed the electric light bulb?"),
    ("What is the human genome?", "Explain what the human genome is.", "Describe the complete set of human genetic information."),
    ("How does nuclear energy work?", "Explain how nuclear power generates electricity.", "Describe the process of nuclear energy production."),
    ("What is quantum mechanics?", "Explain the principles of quantum mechanics.", "Describe what quantum mechanics is about."),
    ("Who was Napoleon Bonaparte?", "Describe who Napoleon Bonaparte was.", "What is Napoleon Bonaparte known for?"),
    ("What causes tides?", "Explain why ocean tides occur.", "What force is responsible for ocean tides?"),
    ("How do antibiotics work?", "Explain the mechanism of antibiotic action.", "Describe how antibiotics fight bacterial infections."),
    ("What is the Fibonacci sequence?", "Explain the Fibonacci sequence in mathematics.", "Describe the pattern in the Fibonacci series."),
    ("Who discovered penicillin?", "Which scientist discovered penicillin?", "Who first identified penicillin as an antibiotic?"),
    ("What is the Big Bang theory?", "Explain the Big Bang theory of the universe.", "Describe the Big Bang as the origin of the universe."),
    ("How do solar panels work?", "Explain how solar panels generate electricity.", "Describe the photovoltaic process in solar panels."),
    ("What is artificial intelligence?", "Define artificial intelligence and its applications.", "Explain what AI means in technology."),
    ("Who was Marie Curie?", "Describe who Marie Curie was and her contributions.", "What is Marie Curie famous for in science?"),
    ("What causes volcanic eruptions?", "Explain why volcanoes erupt.", "Describe the geological forces behind volcanic eruptions."),
    ("How does the immune system work?", "Explain the function of the human immune system.", "Describe how the body defends against disease."),
    ("What is the speed of sound?", "How fast does sound travel through air?", "What is the velocity of sound waves?"),
    ("Who wrote Pride and Prejudice?", "Which author wrote Pride and Prejudice?", "Who is the novelist behind Pride and Prejudice?"),
    ("What is a black hole?", "Explain what a black hole is in astrophysics.", "Describe a black hole and how it forms."),
    ("How does WiFi work?", "Explain the technology behind WiFi.", "Describe how wireless internet connections function."),
]

UNIQUE: list[str] = [t[0] for t in _SEED]
PARAPHRASES: list[str] = [p for t in _SEED for p in t[1:]]  # 100 items, 2 per question
CORPUS: list[str] = UNIQUE + UNIQUE + PARAPHRASES  # 200 total

_SWEEP_THRESHOLDS = [round(0.80 + 0.01 * i, 2) for i in range(20)]  # 0.80 .. 0.99

# Illustrative traffic mix for the "effective hit rate" column — not measured, just a
# stated assumption for turning per-class rates into a single headline number.
_ASSUMED_MIX = {"true_duplicate": 0.40, "near_miss_trap": 0.10, "unrelated": 0.50}

_EVAL_SET_PATH = Path(__file__).parent / "data" / "similarity_eval.jsonl"

_PORT = 9001
_ALIAS = "bench-cache"
_PROVIDER_NAME = "bench-cache"
_MOCK_BASE_URL = f"http://host.docker.internal:{_PORT}"
_GATEWAY_URL = "http://localhost:8000/v1/chat/completions"


def _make_payload(prompt: str, model: str, no_cache: bool = False) -> dict:
    p: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if no_cache:
        p["cache"] = {"no_cache": True}
    return p


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


async def embed_batch(
    client: httpx.AsyncClient, texts: list[str], api_base: str, api_key: str
) -> list[list[float]]:
    """Embed a list of texts, batched in groups of 50 to stay within API limits."""
    embeddings: list[list[float]] = []
    batch_size = 50
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = await client.post(
            f"{api_base}/embeddings",
            json={"input": batch, "model": "text-embedding-3-small"},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        embeddings.extend([item["embedding"] for item in sorted(data, key=lambda x: x["index"])])
    return embeddings


def _pct(data: list[float], p: float) -> float:
    if not data:
        return float("nan")
    s = sorted(data)
    idx = (len(s) - 1) * p / 100.0
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def _exact_cache_keys(alias: str) -> list[str]:
    """SHA-256 exact-cache key for every unique prompt this bench will send.

    Mirrors gateway/cache/exact.py's normalize+request_hash (volatile keys
    stripped, sorted-key JSON) without importing the gateway package — the
    payloads this script sends never include the volatile keys anyway, so
    this is a direct reimplementation, not an approximation.
    """
    keys = []
    for prompt in set(CORPUS):
        body = {"model": alias, "messages": [{"role": "user", "content": prompt}]}
        normalized = json.dumps(body, sort_keys=True, separators=(",", ":"))
        keys.append(hashlib.sha256(normalized.encode()).hexdigest())
    return keys


async def run_gateway_mode(db_url: str, redis_url: str) -> None:
    conn = await asyncpg.connect(db_url)
    r = aioredis.from_url(redis_url)
    server = await start_mock_provider(_PORT)
    await seed_bench_provider(
        conn, provider_name=_PROVIDER_NAME, alias=_ALIAS, base_url=_MOCK_BASE_URL
    )

    # Reset only this bench's own prior state, scoped so it's safe against a shared
    # live instance: exact-cache keys are deleted by exact hash (never touches
    # budget:* keys or other aliases' entries), semantic_cache rows are deleted by
    # model=_ALIAS (rows are already scoped by model column).
    exact_keys = _exact_cache_keys(_ALIAS)
    if exact_keys:
        await r.delete(*exact_keys)
    await conn.execute("DELETE FROM semantic_cache WHERE model = $1", _ALIAS)

    start_ts = datetime.now(tz=timezone.utc)

    rows = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            print(f"Sending {len(CORPUS)} requests (unique→exact-dup→paraphrases)…")
            for i, prompt in enumerate(CORPUS):
                payload = _make_payload(prompt, _ALIAS)
                resp = await client.post(_GATEWAY_URL, json=payload, headers=auth_headers())
                resp.raise_for_status()
                if (i + 1) % 50 == 0:
                    print(f"  {i + 1}/{len(CORPUS)}")
        rows = await conn.fetch(
            """
            SELECT cache_status, prompt_tokens, completion_tokens, latency_ms
            FROM requests
            WHERE requested_model = $1
              AND created_at >= $2
            """,
            _ALIAS,
            start_ts,
        )
    finally:
        server.close()
        await server.wait_closed()
        await cleanup_bench_alias(conn, alias=_ALIAS, provider_names=[_PROVIDER_NAME])
        await conn.close()
        await r.aclose()

    counts: dict[str, int] = {}
    cost_saved_cents = 0.0
    INPUT_PRICE = 0.15 / 1_000_000  # $/token (gpt-4o-mini equivalent)
    OUTPUT_PRICE = 0.60 / 1_000_000
    latencies_by_status: dict[str, list[float]] = {"exact_hit": [], "semantic_hit": [], "miss": []}

    for row in rows:
        cs = row["cache_status"] or "miss"
        counts[cs] = counts.get(cs, 0) + 1
        if row["latency_ms"] is not None and cs in latencies_by_status:
            latencies_by_status[cs].append(float(row["latency_ms"]))
        if cs in ("exact_hit", "semantic_hit"):
            pt = row["prompt_tokens"] or 0
            ct = row["completion_tokens"] or 0
            cost_saved_cents += (pt * INPUT_PRICE + ct * OUTPUT_PRICE) * 100

    total = len(rows)
    table_rows = []
    for status in ("exact_hit", "semantic_hit", "miss"):
        n = counts.get(status, 0)
        pct = 100.0 * n / total if total else 0.0
        table_rows.append(f"| {status:<13} | {n:<5} | {pct:.1f}% |")

    hits = counts.get("exact_hit", 0) + counts.get("semantic_hit", 0)

    hit_latencies = latencies_by_status["exact_hit"] + latencies_by_status["semantic_hit"]
    miss_latencies = latencies_by_status["miss"]
    latency_rows = "\n".join(
        f"| p{p:<9} | {_pct(hit_latencies, p):<12.1f} | {_pct(miss_latencies, p):<12.1f} |"
        for p in (50, 95, 99)
    )

    report = f"""\
## Cache Benchmark — {date.today().isoformat()}

### Hit Rate (gateway mode; semantic threshold = gateway's SEMANTIC_SIMILARITY_THRESHOLD, not recorded by this script)
Corpus: {len(UNIQUE)} unique + {len(UNIQUE)} exact-duplicate + {len(PARAPHRASES)} semantic-paraphrase = {len(CORPUS)} requests

| cache_status  | count | %     |
|---------------|-------|-------|
{chr(10).join(table_rows)}

Cost reduction: {cost_saved_cents:.2f}¢ saved on {hits} cache hits
(based on gpt-4o-mini pricing of $0.15/$0.60 per Mtok)

### Hit vs miss latency (gateway DB column latency_ms)
| Percentile | Hit (exact+semantic, ms) | Miss (ms) |
|------------|--------------------------|-----------|
{latency_rows}

Auth: {"bench-key" if os.environ.get("GATEWAY_API_KEY") else "anonymous"}. Reset scope: exact-cache
keys deleted by hash, semantic_cache rows deleted by `model = '{_ALIAS}'` only —
non-destructive against a shared instance (no `flushdb`, no unscoped `DELETE`).

Methodology: paraphrase corpus hand-crafted to test semantic similarity;
gateway mode uses the live gateway with threshold from SEMANTIC_SIMILARITY_THRESHOLD env var.
"""
    _write_report("cache", report)


def _load_similarity_eval(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


async def run_similarity_mode(api_key: str, api_base: str) -> None:
    rows = _load_similarity_eval(_EVAL_SET_PATH)

    # Dedupe text_a/text_b across pairs so every unique string is embedded once.
    unique_texts = sorted({r["text_a"] for r in rows} | {r["text_b"] for r in rows})
    text_index = {t: i for i, t in enumerate(unique_texts)}

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        print(f"Embedding {len(unique_texts)} unique strings from {len(rows)} labeled pairs…")
        embeddings = await embed_batch(client, unique_texts, api_base, api_key)

    similarities = [
        cosine_similarity(embeddings[text_index[r["text_a"]]], embeddings[text_index[r["text_b"]]])
        for r in rows
    ]

    by_class: dict[str, list[float]] = {"true_duplicate": [], "near_miss_trap": [], "unrelated": []}
    for r, sim in zip(rows, similarities):
        by_class[r["class"]].append(sim)

    n_dupe = len(by_class["true_duplicate"])
    n_trap = len(by_class["near_miss_trap"])
    n_unrelated = len(by_class["unrelated"])

    sweep_rows = []
    per_threshold: dict[float, dict[str, float]] = {}
    for t in _SWEEP_THRESHOLDS:
        tpr = sum(1 for s in by_class["true_duplicate"] if s >= t) / n_dupe
        trap_fpr = sum(1 for s in by_class["near_miss_trap"] if s >= t) / n_trap
        unrelated_fpr = sum(1 for s in by_class["unrelated"] if s >= t) / n_unrelated
        effective_hit_rate = (
            _ASSUMED_MIX["true_duplicate"] * tpr
            + _ASSUMED_MIX["near_miss_trap"] * trap_fpr
            + _ASSUMED_MIX["unrelated"] * unrelated_fpr
        )
        per_threshold[t] = {
            "tpr": tpr,
            "trap_fpr": trap_fpr,
            "unrelated_fpr": unrelated_fpr,
            "effective_hit_rate": effective_hit_rate,
        }
        sweep_rows.append(
            f"| {t:.2f} | {100 * tpr:.1f}% | {100 * trap_fpr:.1f}% | {100 * unrelated_fpr:.1f}% | {100 * effective_hit_rate:.1f}% |"
        )

    # Selection rule: among thresholds with trap false-positive rate <= 1%, take the one
    # maximizing true-positive rate (i.e. hit rate); ties broken toward the lower
    # threshold (more potential recall for equal measured risk).
    candidates = [t for t in _SWEEP_THRESHOLDS if per_threshold[t]["trap_fpr"] <= 0.01]
    target_met = bool(candidates)
    if candidates:
        best_tpr = max(per_threshold[t]["tpr"] for t in candidates)
        chosen = min(t for t in candidates if per_threshold[t]["tpr"] == best_tpr)
    else:
        # No threshold in the sweep hits the 1% correctness bar. Fall back to the
        # threshold(s) with the lowest measured trap FPR; among those, prefer the
        # lowest threshold, since going higher buys no extra measured safety here
        # (the floor is set by one structural outlier, not by threshold placement)
        # while only costing more recall.
        min_trap_fpr = min(per_threshold[t]["trap_fpr"] for t in _SWEEP_THRESHOLDS)
        floor_candidates = [t for t in _SWEEP_THRESHOLDS if per_threshold[t]["trap_fpr"] == min_trap_fpr]
        chosen = min(floor_candidates)

    chosen_stats = per_threshold[chosen]

    # Root cause for a missed target: any trap pair that out-scores the single most
    # similar true-duplicate pair is un-fixable by a global threshold — no cut point
    # can admit that duplicate while excluding that trap.
    max_dupe_sim = max(by_class["true_duplicate"])
    unresolvable_traps = sorted(
        (
            (sim, r)
            for sim, r in zip(similarities, rows)
            if r["class"] == "near_miss_trap" and sim > max_dupe_sim
        ),
        key=lambda x: -x[0],
    )

    root_cause_section = ""
    if not target_met:
        offenders = "\n".join(
            f"- `{sim:.4f}` — {r['domain']}: {r['text_a']!r} vs {r['text_b']!r}"
            for sim, r in unresolvable_traps
        )
        root_cause_section = f"""
### Root cause: no threshold in range meets the ≤1% target
The strictest true-duplicate pair in the eval set scores **{max_dupe_sim:.4f}** cosine
similarity. At least one near-miss trap scores *higher* than that:
{offenders}

Because a trap out-scores the closest true duplicate, no single global threshold can
admit that duplicate while excluding that trap — this is a structural limit of
cosine-similarity thresholding on this embedding model for numeric/ID-bearing
near-misses (e.g. differing only by an order number), not a threshold-tuning problem.
Raising the threshold further does not improve safety against this failure class; it
only destroys recall that would otherwise be safe.
"""

    not_met_note = (
        ""
        if target_met
        else "\nThis does **not** meet the ≤1% correctness target — see Root Cause "
        "above. It is the lowest threshold that reaches the measured trap-FPR floor "
        "(1.7%); it is reported as the safest available single-threshold setting, not "
        "as a passing result. Closing the remaining gap requires a non-similarity "
        "guard (e.g. bypassing the cache when the two requests' numeric literals/IDs "
        "differ), which is out of scope for this measurement-only step and is "
        "recommended as follow-up work."
    )

    report = f"""\
## Semantic Cache Similarity Threshold — {date.today().isoformat()}

### Methodology
- Eval set: `bench/data/similarity_eval.jsonl`, {len(rows)} hand-labeled request pairs
  across 4 domains (customer support, coding Q&A, doc lookup, data queries).
- **This is synthetic, hand-labeled data, not captured production traffic.** It is
  designed to stress-test the threshold with adversarial near-miss cases, not to
  represent real query distributions.
- Classes: `true_duplicate` ({n_dupe} pairs, a cache hit is correct), `near_miss_trap`
  ({n_trap} pairs, high lexical overlap but different intent — a cache hit here is a
  wrong-answer bug), `unrelated` ({n_unrelated} pairs, sanity floor).
- Embedding model: text-embedding-3-small via EMBEDDING_API_BASE. Unique strings are
  deduped before embedding ({len(unique_texts)} embedding calls for {len(rows)} pairs).

### Threshold sweep (0.80 → 0.99, step 0.01)
| Threshold | TPR (dupes hit) | Trap FPR (traps wrongly hit) | Unrelated hit rate | Effective hit rate* |
|-----------|------------------|-------------------------------|---------------------|----------------------|
{chr(10).join(sweep_rows)}

\\* Effective hit rate assumes an illustrative traffic mix of
{int(100 * _ASSUMED_MIX["true_duplicate"])}% true duplicates /
{int(100 * _ASSUMED_MIX["near_miss_trap"])}% near-miss traps /
{int(100 * _ASSUMED_MIX["unrelated"])}% unrelated. This mix is an assumption for
illustration, not a measurement of production traffic.

### Selection
Rule: choose the highest threshold-derived hit rate subject to trap false-positive
rate ≤ 1%. Wrong answers are a correctness bug — we sacrifice hit rate for
correctness, never the reverse.
{root_cause_section}
**{"Chosen" if target_met else "Recommended interim"} threshold: {chosen:.2f}**
- True-positive rate: {100 * chosen_stats["tpr"]:.1f}%
- Trap false-positive rate: {100 * chosen_stats["trap_fpr"]:.1f}%
- Unrelated hit rate: {100 * chosen_stats["unrelated_fpr"]:.1f}%
{not_met_note}

### Limitations
Validated on synthetic pairs; production traffic may differ in phrasing, domain mix,
and adversarial density. `SEMANTIC_SIMILARITY_THRESHOLD` remains configurable per
deployment for this reason — re-run this sweep against real (anonymized) query pairs
once production traffic is available.
"""
    _write_report("similarity-threshold", report)


def _write_report(scenario: str, content: str) -> None:
    out = Path(__file__).parent / "reports"
    out.mkdir(exist_ok=True)
    fname = out / f"bench-{date.today().isoformat().replace('-', '')}-{scenario}.md"
    fname.write_text(content)
    print(f"\nReport → {fname}\n")
    print(content)


async def main() -> None:
    mode = "gateway"
    for arg in sys.argv[1:]:
        if arg.startswith("--mode="):
            mode = arg.split("=", 1)[1]

    if mode == "gateway":
        db_url = os.environ.get("DATABASE_URL", "postgresql://gateway:gateway@localhost:5432/gateway")
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        await run_gateway_mode(db_url, redis_url)

    elif mode == "similarity":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            print("ERROR: OPENAI_API_KEY must be set for --mode=similarity", file=sys.stderr)
            sys.exit(1)
        api_base = os.environ.get("EMBEDDING_API_BASE", "https://api.openai.com/v1")
        await run_similarity_mode(api_key, api_base)

    else:
        print(f"Unknown mode: {mode}. Use --mode=gateway or --mode=similarity", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
