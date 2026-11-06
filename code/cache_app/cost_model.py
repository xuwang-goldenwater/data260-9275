"""
DATA 260 HW9 Part 3.4 - cost model on top of the threshold sweep.

    total cost = misses x MISS_COST + false hits x FALSE_HIT_COST

MISS_COST = 1        one full HW8 pipeline run (Planner + Writer + Reviewer, 3 calls
                     to qwen2.5:3b; measured mean 18.4 s of local model time in prepare).
                     Every miss pays it, whether or not the miss was the right call.
FALSE_HIT_COST = 20  a store gets recall facts for the WRONG recall (wrong date, firm,
                     units, product). It may pull the wrong product or keep selling the
                     recalled one: a support ticket plus a food-safety exposure, far more
                     than 20 s of compute. A correct hit costs 0.

Two configurations, same 40 cases, same measured similarities and agent times:
    threshold only            the sweep as run (sweep_cases.csv)
    threshold + recall guard  a hit is allowed only if the incoming question and the
                              cached question name the same recall number
                              (semantic_cache.recall_guard_ok); a guarded-out hit
                              becomes a miss and pays that case's measured agent time.

    python code/cache_app/cost_model.py
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict

import yaml

from semantic_cache import ROOT, recall_guard_ok

MISS_COST = 1
FALSE_HIT_COST = 20
RAW = ROOT / "reports/hw09/raw"


def evaluate(rows: list[dict], seed_query: dict, guard: bool) -> dict:
    hits = false = correct = 0
    latency = 0.0
    for r in rows:
        is_hit = r["outcome"] in ("correct_hit", "FALSE_HIT")
        lat = float(r["latency_ms"])
        outcome = r["outcome"]
        if is_hit and guard and not recall_guard_ok(r["query"], seed_query[r["nearest_seed"]]):
            is_hit = False
            lat += float(r["agent_ms_if_miss"])        # now it runs the agents
            outcome = "missed_hit" if r["expect"] == "hit" else "correct_miss"
        if is_hit:
            hits += 1
            correct += outcome == "correct_hit"
            false += outcome == "FALSE_HIT"
        latency += lat
    n = len(rows)
    misses = n - hits
    return {"hits": hits, "correct_hits": correct, "false_hits": false, "misses": misses,
            "hit_rate": hits / n, "false_hit_rate": false / hits if hits else 0.0,
            "mean_latency_ms": latency / n,
            "total_cost": misses * MISS_COST + false * FALSE_HIT_COST}


def main() -> None:
    print("Xu Wang | DATA 260 HW9 Part 3.4 | cost model | PREFIX s9275")
    data = yaml.safe_load((ROOT / "reports/hw09/cache_cases.yaml").read_text())
    seed_query = {s["id"]: s["query"] for s in data["seeds"]}
    prep = json.loads((RAW / "sweep_prepare.json").read_text())
    by_t = defaultdict(list)
    with (RAW / "sweep_cases.csv").open() as fh:
        for r in csv.DictReader(fh):
            r["agent_ms_if_miss"] = prep["case_answers"][r["case"]]["agent_ms"]
            by_t[float(r["threshold"])].append(r)

    print(f"\nMISS_COST = {MISS_COST}   FALSE_HIT_COST = {FALSE_HIT_COST}")
    results = []
    for guard in (False, True):
        label = "threshold + recall guard" if guard else "threshold only (required table)"
        print(f"\n=== {label} ===")
        print(f"{'thresh':>6} {'hit rate':>9} {'false-hit rate':>15} {'mean latency ms':>16}"
              f" {'misses':>7} {'false':>6} {'total cost':>11}")
        for t in sorted(by_t):
            e = evaluate(by_t[t], seed_query, guard)
            results.append({"threshold": t, "recall_guard": guard, **e})
            print(f"{t:>6.2f} {e['hit_rate']:>9.1%} {e['false_hit_rate']:>15.1%} "
                  f"{e['mean_latency_ms']:>16.1f} {e['misses']:>7} {e['false_hits']:>6} "
                  f"{e['total_cost']:>11}")

    best = min(results, key=lambda r: (r["total_cost"], -r["hits"]))
    print(f"\nLowest total cost: threshold {best['threshold']:.2f}"
          f"{' + recall guard' if best['recall_guard'] else ''} "
          f"(cost {best['total_cost']}, {best['correct_hits']} correct hits, "
          f"{best['false_hits']} false hits)")

    # How sensitive is the choice to FALSE_HIT_COST? (threshold only)
    plain = [r for r in results if not r["recall_guard"]]
    print("\nSensitivity, threshold only - cheapest threshold for each false-hit cost:")
    for fc in (1, 2, 3, 4, 5, 10, 20, 50):
        pick = min(plain, key=lambda r: r["misses"] * MISS_COST + r["false_hits"] * fc)
        print(f"  FALSE_HIT_COST={fc:>3} -> {pick['threshold']:.2f}")

    (RAW / "cost_model.json").write_text(json.dumps(
        {"miss_cost": MISS_COST, "false_hit_cost": FALSE_HIT_COST,
         "results": results, "chosen": best}, indent=2))
    print("\nsaved reports/hw09/raw/cost_model.json")


if __name__ == "__main__":
    main()
