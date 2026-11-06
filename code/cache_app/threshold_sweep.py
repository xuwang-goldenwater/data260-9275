"""
DATA 260 HW9 Part 3.2 - threshold sweep over reports/hw09/cache_cases.yaml.

Two phases, so the slow part runs once:

  prepare  (needs Kafka + the 3 HW8 agents, ~15 min)
     1. empty the cache, answer the 10 seeds with the agents, store them
     2. run the 30 non-exact cases through the agents once, without storing:
        this gives each case's own answer (the "correct answer" for 3.3) and its
        real miss latency. An exact case is the seed itself, so its miss
        latency is the seed's agent time.
     -> reports/hw09/raw/sweep_prepare.json

  sweep    (needs only Redis, seconds)
     the cache is frozen (10 seeds, nothing written back). For each threshold,
     every case is embedded and searched for real (KNN 1, timed). Then:
        hit  -> latency = measured embed + search (+ version check)
        miss -> latency = measured embed + search + that case's agent time
                from prepare (the agents are not re-run 5 x 40 times)
     -> reports/hw09/raw/sweep_cases.csv, sweep_summary.json

Labels and definitions come from cache_cases.yaml; nothing here relabels.

    python code/cache_app/threshold_sweep.py prepare
    python code/cache_app/threshold_sweep.py sweep
"""

from __future__ import annotations

import csv
import json
import logging
import sys
import time
from datetime import datetime

import yaml

from semantic_cache import ROOT, SemanticCache

CASES_FILE = ROOT / "reports/hw09/cache_cases.yaml"
RAW = ROOT / "reports/hw09/raw"
PREPARE_FILE = RAW / "sweep_prepare.json"
THRESHOLDS = [0.75, 0.80, 0.85, 0.90, 0.95]
MAX_SEED_TRIES = 3          # a seed the Reviewer rejects is asked again (never stored rejected)


def load_cases() -> dict:
    return yaml.safe_load(CASES_FILE.read_text())


def timed_agent(cache: SemanticCache, query: str) -> dict:
    facts, notice_id = cache.facts_for(query)
    t = time.perf_counter()
    final = cache.run_agent(query, facts)
    return {"answer": final.get("answer", ""), "status": final.get("status"),
            "agent_ms": round((time.perf_counter() - t) * 1000, 1),
            "notice_id": notice_id, "version": cache.current_version(notice_id)}


def prepare() -> None:
    data = load_cases()
    cache = SemanticCache()
    cache.reset()
    cache.embed("warm-up")
    seeds, answers = {}, {}

    print("\n=== 1. seeds -> agents -> cache ===")
    for s in data["seeds"]:
        for attempt in range(1, MAX_SEED_TRIES + 1):
            r = timed_agent(cache, s["query"])
            print(f"{s['id']:<4} try {attempt}  {r['status']:<8} {r['agent_ms']:>8.0f} ms  {s['query']}")
            if r["status"] == "approved":
                break
        if r["status"] != "approved":
            raise SystemExit(f"{s['id']} rejected {MAX_SEED_TRIES} times - fix before sweeping")
        key = cache.store(s["query"], cache.embed(s["query"]), r["answer"], r["notice_id"], r["version"])
        seeds[s["id"]] = {**r, "query": s["query"], "key": key, "tries": attempt}

    print("\n=== 2. non-exact cases -> agents (not stored) ===")
    for c in data["cases"]:
        if c["kind"] == "exact":
            answers[c["id"]] = {**seeds[c["seed"]], "from_seed": True}
            continue
        r = timed_agent(cache, c["query"])
        answers[c["id"]] = r
        print(f"{c['id']}  {r['status']:<8} {r['agent_ms']:>8.0f} ms  {c['query'][:70]}")

    RAW.mkdir(parents=True, exist_ok=True)
    PREPARE_FILE.write_text(json.dumps({
        "prepared_at": datetime.now().isoformat(timespec="seconds"),
        "seeds": seeds, "case_answers": answers}, indent=2))
    n = cache.r.ft("s9275:semcache_idx").info()["num_docs"]
    print(f"\ncache now holds {n} entries (expected 10); saved {PREPARE_FILE.relative_to(ROOT)}")


def sweep() -> None:
    data = load_cases()
    prep = json.loads(PREPARE_FILE.read_text())
    key_to_seed = {v["key"]: k for k, v in prep["seeds"].items()}
    cache = SemanticCache()
    n = int(cache.r.ft("s9275:semcache_idx").info()["num_docs"])
    if n != len(key_to_seed):
        raise SystemExit(f"cache has {n} entries, prepare stored {len(key_to_seed)} - run prepare again")
    cache.embed("warm-up")

    rows, summary = [], []
    for th in THRESHOLDS:
        hits = correct = false = missed = 0
        lat = []
        for c in data["cases"]:
            t0 = time.perf_counter()
            best = cache.lookup(cache.embed(c["query"]))
            sim = best["similarity"]
            is_hit = sim >= th
            if is_hit:
                cache.current_version(best["notice_id"])          # the check a real hit pays for
            lookup_ms = (time.perf_counter() - t0) * 1000
            matched = key_to_seed.get(best["key"])
            agent_ms = 0.0 if is_hit else prep["case_answers"][c["id"]]["agent_ms"]
            latency = lookup_ms + agent_ms

            should_hit = c["expect"] == "hit"
            if is_hit:
                hits += 1
                if should_hit and matched == c["seed"]:
                    outcome = "correct_hit"
                    correct += 1
                else:
                    outcome = "FALSE_HIT"
                    false += 1
            else:
                outcome = "missed_hit" if should_hit else "correct_miss"
                missed += should_hit
            lat.append(latency)
            rows.append({"threshold": th, "case": c["id"], "kind": c["kind"], "expect": c["expect"],
                         "seed": c["seed"], "nearest_seed": matched, "similarity": round(sim, 4),
                         "outcome": outcome, "lookup_ms": round(lookup_ms, 2),
                         "agent_ms": agent_ms, "latency_ms": round(latency, 1),
                         "query": c["query"]})
        total = len(data["cases"])
        summary.append({"threshold": th, "hits": hits, "correct_hits": correct, "false_hits": false,
                        "missed_hits": missed, "misses": total - hits,
                        "hit_rate": hits / total,
                        "false_hit_rate": (false / hits) if hits else 0.0,
                        "mean_latency_ms": sum(lat) / total})

    with (RAW / "sweep_cases.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (RAW / "sweep_summary.json").write_text(json.dumps(
        {"run_at": datetime.now().isoformat(timespec="seconds"),
         "prepared_at": prep["prepared_at"], "thresholds": summary}, indent=2))

    print("\n=== Similarity of each case to its nearest seed (same at every threshold) ===")
    for r in rows[:len(data["cases"])]:
        print(f"{r['case']}  {r['kind']:<10} expect {r['expect']:<4}  nearest {str(r['nearest_seed']):<4}"
              f" sim {r['similarity']:.4f}   {r['query'][:60]}")
    print("\n=== Threshold sweep (40 cases, cache frozen at 10 seeds) ===")
    print(f"{'thresh':>6} {'hits':>5} {'correct':>8} {'false':>6} {'missed':>7} "
          f"{'hit rate':>9} {'false-hit rate':>15} {'mean latency ms':>16}")
    for s in summary:
        print(f"{s['threshold']:>6.2f} {s['hits']:>5} {s['correct_hits']:>8} {s['false_hits']:>6} "
              f"{s['missed_hits']:>7} {s['hit_rate']:>9.1%} {s['false_hit_rate']:>15.1%} "
              f"{s['mean_latency_ms']:>16.1f}")
    print("\nFALSE HITS:")
    for r in rows:
        if r["outcome"] == "FALSE_HIT":
            print(f"  t={r['threshold']:.2f}  {r['case']} ({r['kind']}) -> {r['nearest_seed']}  "
                  f"sim {r['similarity']:.4f}  {r['query']}")
    print("\nsaved reports/hw09/raw/sweep_cases.csv, sweep_summary.json")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    print("Xu Wang | DATA 260 HW9 Part 3.2 | threshold sweep | PREFIX s9275")
    {"prepare": prepare, "sweep": sweep}[sys.argv[1] if len(sys.argv) > 1 else "sweep"]()
