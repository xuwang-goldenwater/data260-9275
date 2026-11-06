"""
DATA 260 HW9 Part 2 - run 12 queries through the semantic cache (threshold 0.85)
and report hit rate and average latency, cached vs not cached.

The list mixes the three kinds the assignment asks for:
    new         first time a question is asked  -> expected MISS (agents run)
    duplicate   exact repeat of an earlier query -> expected HIT
    paraphrase  same meaning, different words    -> hoped HIT (0.85 may say no)
"kind" is only a label for the report; the cache never sees it.

Starts from an empty cache, runs in one process (the embedding model stays loaded),
writes reports/hw09/raw/part2_demo.json.

Needs Redis, MySQL, Kafka and the three HW8 agents running.
    python code/cache_app/part2_demo.py
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from semantic_cache import ROOT, SemanticCache

QUERIES = [
    ("new",        "How many units were affected by recall F-0001-2025?"),
    ("duplicate",  "How many units were affected by recall F-0001-2025?"),
    ("paraphrase", "For recall F-0001-2025, what was the number of units affected?"),
    ("new",        "Which firm issued recall F-0002-2021?"),
    ("paraphrase", "Which company is behind recall F-0002-2021?"),
    ("new",        "What should a grocery store do when it receives a recall notice for "
                   "peanut butter that may contain undeclared milk?"),
    ("paraphrase", "How should a grocery store respond to a recall notice for peanut "
                   "butter that may contain undeclared milk?"),
    ("duplicate",  "Which firm issued recall F-0002-2021?"),
    ("new",        "When was recall F-0003-2023 issued?"),
    ("duplicate",  "What should a grocery store do when it receives a recall notice for "
                   "peanut butter that may contain undeclared milk?"),
    ("new",        "How should a store dispose of recalled frozen vegetables?"),
    ("paraphrase", "What is the recall date of F-0003-2023?"),
]
OUT = ROOT / "reports/hw09/raw/part2_demo.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "huggingface_hub", "sentence_transformers", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    print("Xu Wang | DATA 260 HW9 Part 2 | semantic cache demo | PREFIX s9275")

    cache = SemanticCache(threshold=0.85)
    cache.reset()                     # empty cache: every run starts the same way
    cache.embed("warm-up")            # first encode is slow; keep it out of query 1

    rows = []
    for i, (kind, q) in enumerate(QUERIES, 1):
        print(f"\n--- Q{i:02d} [{kind}] {q}")
        r = cache.ask(q)
        r.update({"n": i, "kind": kind})
        rows.append(r)
        sim = "  -   " if r["similarity"] is None else f"{r['similarity']:.4f}"
        print(f"    is_cached={r['is_cached']}  similarity={sim}  latency={r['latency_ms']:.1f} ms")
        print(f"    answer: {r['answer'][:160]}")

    hits = [r for r in rows if r["is_cached"]]
    misses = [r for r in rows if not r["is_cached"]]

    def avg(rs):
        return sum(r["latency_ms"] for r in rs) / len(rs) if rs else 0.0

    print("\n=== Summary (threshold 0.85) ===")
    print(f"{'#':>3}  {'kind':<10} {'cached':<6} {'sim':>7} {'latency ms':>11}")
    for r in rows:
        sim = "-" if r["similarity"] is None else f"{r['similarity']:.4f}"
        print(f"{r['n']:>3}  {r['kind']:<10} {str(r['is_cached']):<6} {sim:>7} {r['latency_ms']:>11.1f}")
    print(f"\nCache hit rate : {len(hits)}/{len(rows)} = {100 * len(hits) / len(rows):.1f}%")
    print(f"Avg latency    : cached {avg(hits):.1f} ms (n={len(hits)})  |  "
          f"not cached {avg(misses):.1f} ms (n={len(misses)})")
    if hits and misses:
        print(f"Observed ratio : not-cached / cached = {avg(misses) / avg(hits):.0f}x")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"run_at": datetime.now().isoformat(timespec="seconds"),
                               "threshold": 0.85, "queries": rows,
                               "hit_rate": len(hits) / len(rows),
                               "avg_latency_cached_ms": avg(hits),
                               "avg_latency_not_cached_ms": avg(misses)}, indent=2))
    print(f"\nsaved {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
