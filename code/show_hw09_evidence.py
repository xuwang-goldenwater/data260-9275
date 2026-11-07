"""
DATA 260 HW9 - reprint saved results for screenshots (reads files only, runs nothing,
changes nothing). Used when the original terminal output had scrolled past the name line.

    python code/show_hw09_evidence.py part2     # Part 2 summary  (reports/hw09/raw/part2_demo.json)
    python code/show_hw09_evidence.py sweep     # 3.2 table + false hits (raw/sweep_summary.json, sweep_cases.csv)
    python code/show_hw09_evidence.py train05   # 4.1 controlled revision (part4/results/train.json)
    python code/show_hw09_evidence.py train07   # 4.2 lesson creation + lessons.json
    python code/show_hw09_evidence.py reuse     # 4.2 lesson_001 loaded on later questions (validate.json, test.json)
    python code/show_hw09_evidence.py test      # 4.4 table (part4/results/test.json)
"""
import csv
import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1] / "reports/hw09"


def load(p):
    return json.loads((R / p).read_text())


def part2():
    d = load("raw/part2_demo.json")
    print(f"(saved run {d['run_at']}, reports/hw09/raw/part2_demo.json)\n")
    print("=== Summary (threshold 0.85) ===")
    print(f"{'#':>3}  {'kind':<10} {'cached':<6} {'sim':>7} {'latency ms':>11}")
    for r in d["queries"]:
        sim = "-" if r["similarity"] is None else f"{r['similarity']:.4f}"
        print(f"{r['n']:>3}  {r['kind']:<10} {str(r['is_cached']):<6} {sim:>7} {r['latency_ms']:>11.1f}")
    hits = sum(r["is_cached"] for r in d["queries"])
    print(f"\nCache hit rate : {hits}/{len(d['queries'])} = {100 * d['hit_rate']:.1f}%")
    print(f"Avg latency    : cached {d['avg_latency_cached_ms']:.1f} ms  |  "
          f"not cached {d['avg_latency_not_cached_ms']:.1f} ms")


def sweep():
    s = load("raw/sweep_summary.json")
    print(f"(saved run {s['run_at']}, reports/hw09/raw/sweep_summary.json + sweep_cases.csv)\n")
    print("=== Threshold sweep (40 cases, cache frozen at 10 seeds) ===")
    print(f"{'thresh':>6} {'hits':>5} {'correct':>8} {'false':>6} {'missed':>7} "
          f"{'hit rate':>9} {'false-hit rate':>15} {'mean latency ms':>16}")
    for x in s["thresholds"]:
        print(f"{x['threshold']:>6.2f} {x['hits']:>5} {x['correct_hits']:>8} {x['false_hits']:>6} "
              f"{x['missed_hits']:>7} {x['hit_rate']:>9.1%} {x['false_hit_rate']:>15.1%} "
              f"{x['mean_latency_ms']:>16.1f}")
    print("\nFALSE HITS:")
    with (R / "raw/sweep_cases.csv").open() as fh:
        for r in csv.DictReader(fh):
            if r["outcome"] == "FALSE_HIT":
                print(f"  t={float(r['threshold']):.2f}  {r['case']} ({r['kind']}) -> {r['nearest_seed']}  "
                      f"sim {float(r['similarity']):.4f}  {r['query']}")


def block(qid):
    t = load("part4/results/train.json")
    print(f"(saved training run {t['run_at']}, reports/hw09/part4/results/train.json)\n")
    r = next(x for x in t["rows"] if x["id"] == qid)
    print(f"=== {r['id']}: {r['question']}")
    print(f"    features: {r['features']}   lessons loaded: {r['lessons_loaded'] or 'none'}")
    if qid == "train_05":
        print("    CONTROLLED CASE: 'units_affected' hidden from the record on attempt 1")
    for a in r["attempts"]:
        print(f"  attempt {a['attempt']} answer : {a['answer']}")
        print(f"  evaluator        : {a['result']} - {a['explanation']}")
        if a["feedback"]:
            print(f"  feedback         : {a['feedback']}")
    print(f"  FINAL: {r['final_result']} after {r['n_attempts']} attempt(s)")
    return t


def train05():
    block("train_05")


def train07():
    t = block("train_07")
    print("\nlessons created in this training run:")
    for x in t["lessons"]:
        print(f"  {x['lesson_id']} [{x['failure_type']}, from {x['created_from']}] created_at={x['created_at']}")
        print(f"    failure_pattern: {x['failure_pattern']}\n    correction     : {x['correction']}")


def reuse():
    v, t = load("part4/results/validate.json"), load("part4/results/test.json")
    print(f"(saved validation run {v['run_at']}, test run {t['run_at']})\n")
    print("=== Validation: same question without / with the stored lesson (1 attempt) ===")
    before = {r["id"]: r for r in v["baseline_without_new_lessons"]}
    for r in v["report"][0]["after"]:
        if r["lessons_loaded"]:
            b = before[r["id"]]
            print(f"{r['id']}  \"{r['question']}\"")
            print(f"  without lesson : {b['final_answer']}  -> {b['final_result']}")
            print(f"  loaded {r['lessons_loaded']}: {r['final_answer']}  -> {r['final_result']}")
    print("\n=== Test (held out): test_10 in each variant ===")
    for variant, rows in t["rows"].items():
        r = next(x for x in rows if x["id"] == "test_10")
        print(f"{variant:<22} lessons={r['lessons_loaded'] or '[]'}  attempts={r['n_attempts']}  "
              f"{r['final_result']}")
        print(f"    final answer: {r['final_answer'][:110]}")


def test():
    t = load("part4/results/test.json")
    print(f"(saved test run {t['run_at']}, reports/hw09/part4/results/test.json)\n")
    print("=== Part 4.4 results on test_data.json (12 questions) ===")
    print(f"{'Variant':<22} {'Correct':>8} {'Incorrect':>10} {'Avg attempts':>13} {'Avg latency':>12}")
    for x in t["table"]:
        print(f"{x['variant']:<22} {x['correct']:>8} {x['incorrect']:>10} "
              f"{x['avg_attempts']:>13.2f} {x['avg_latency_ms'] / 1000:>10.2f} s")


if __name__ == "__main__":
    which = sys.argv[1]
    print(f"Xu Wang | DATA 260 HW9 | saved evidence: {which} | PREFIX s9275")
    {"part2": part2, "sweep": sweep, "train05": train05, "train07": train07, "reuse": reuse, "test": test}[which]()
