"""Cache benchmark — hit rate + threshold sensitivity.

Modes:
  --mode=gateway   Send 200 requests through the running gateway, read cache_status
                   from the requests table. Requires gateway + mock server running.
  --mode=similarity  Embed all prompts, compute cosine similarities between paraphrase
                   pairs, show hit rate at each threshold. Requires OPENAI_API_KEY.

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
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import asyncpg
import httpx
import redis.asyncio as aioredis

sys.path.insert(0, str(Path(__file__).parent))
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

# Which unique question each paraphrase belongs to (for similarity analysis).
# PARAPHRASES[2*i] and PARAPHRASES[2*i+1] are paraphrases of UNIQUE[i].
_PARA_PARENT: list[int] = [i for i in range(len(UNIQUE)) for _ in range(2)]

_THRESHOLDS = [0.85, 0.88, 0.90, 0.92, 0.94, 0.96]

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


async def run_gateway_mode(db_url: str, redis_url: str) -> None:
    conn = await asyncpg.connect(db_url)
    r = aioredis.from_url(redis_url)
    server = await start_mock_provider(_PORT)
    await seed_bench_provider(
        conn, provider_name=_PROVIDER_NAME, alias=_ALIAS, base_url=_MOCK_BASE_URL
    )

    # Flush caches so every run starts from zero.
    await conn.execute("DELETE FROM semantic_cache")
    await r.flushdb()

    start_ts = datetime.now(tz=timezone.utc)

    rows = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            print(f"Sending {len(CORPUS)} requests (unique→exact-dup→paraphrases)…")
            for i, prompt in enumerate(CORPUS):
                payload = _make_payload(prompt, _ALIAS)
                resp = await client.post(_GATEWAY_URL, json=payload)
                resp.raise_for_status()
                if (i + 1) % 50 == 0:
                    print(f"  {i + 1}/{len(CORPUS)}")
        rows = await conn.fetch(
            """
            SELECT cache_status, prompt_tokens, completion_tokens
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

    for row in rows:
        cs = row["cache_status"] or "miss"
        counts[cs] = counts.get(cs, 0) + 1
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
    report = f"""\
## Cache Benchmark — {date.today().isoformat()}

### Hit Rate (gateway mode, threshold=0.92)
Corpus: {len(UNIQUE)} unique + {len(UNIQUE)} exact-duplicate + {len(PARAPHRASES)} semantic-paraphrase = {len(CORPUS)} requests

| cache_status  | count | %     |
|---------------|-------|-------|
{chr(10).join(table_rows)}

Cost reduction: {cost_saved_cents:.2f}¢ saved on {hits} cache hits
(based on gpt-4o-mini pricing of $0.15/$0.60 per Mtok)

Methodology: paraphrase corpus hand-crafted to test semantic similarity;
gateway mode uses the live gateway with threshold from SEMANTIC_SIMILARITY_THRESHOLD env var.
"""
    _write_report("cache", report)


async def run_similarity_mode(api_key: str, api_base: str) -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        print(f"Embedding {len(UNIQUE)} unique questions…")
        unique_embeds = await embed_batch(client, UNIQUE, api_base, api_key)

        print(f"Embedding {len(PARAPHRASES)} paraphrases…")
        para_embeds = await embed_batch(client, PARAPHRASES, api_base, api_key)

    # Similarity for each paraphrase vs. its parent unique question.
    similarities = [
        cosine_similarity(para_embeds[j], unique_embeds[_PARA_PARENT[j]])
        for j in range(len(PARAPHRASES))
    ]

    threshold_rows = []
    for t in _THRESHOLDS:
        hits = sum(1 for s in similarities if s >= t)
        threshold_rows.append(f"| {t:.2f}      | {hits:<20} | {100.0 * hits / len(similarities):.1f}%     |")

    # Recommend: highest threshold where hit rate >= 70% (reasonable semantic recall).
    best = max(
        (t for t in _THRESHOLDS if sum(1 for s in similarities if s >= t) / len(similarities) >= 0.70),
        default=_THRESHOLDS[0],
    )

    report = f"""\
### Threshold Sensitivity (similarity mode)
Paraphrase pairs: {len(PARAPHRASES)} ({len(UNIQUE)} unique prompts × 2 paraphrases each)
Embedding model: text-embedding-3-small

| Threshold | Pairs that would hit | Hit rate |
|-----------|----------------------|----------|
{chr(10).join(threshold_rows)}

Recommended threshold: {best:.2f} (highest threshold with ≥70% paraphrase hit rate)

Methodology: paraphrase corpus hand-crafted to test semantic similarity;
similarity mode uses text-embedding-3-small via EMBEDDING_API_BASE.
"""
    _write_report("cache-similarity", report)


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
