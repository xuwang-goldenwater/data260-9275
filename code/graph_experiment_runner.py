"""
DATA 260 - Homework 2, Part 4: the loop-safety experiments.

Four experiments, all against the same model settings:

  schema30     30 runs on the frozen input at the default ceiling, classified
               as valid first attempt / after 1 retry / after 2+ retries /
               abandoned at the ceiling                              (Part 4.3)
  ceiling2     20 runs on the same input with turn ceiling 2         (Part 4.4)
  ceiling10    20 runs on the same input with turn ceiling 10        (Part 4.4)
  adversarial  5 runs on the adversarial input                       (Part 4.5)

Every finished run is appended to reports/hw02/raw/graph_runs.jsonl as soon as
it completes, and the runner skips runs that are already in that file. A run
interrupted with Ctrl-C therefore loses at most the run in flight: start it
again and it picks up where it stopped. On an 8 GB laptop the full set takes
roughly an hour, which is long enough that this matters.

Usage:
    python graph_experiment_runner.py --all
    python graph_experiment_runner.py --experiment ceiling2
    python graph_experiment_runner.py --all --restart      # ignore earlier runs
    python graph_experiment_runner.py --summarize          # recompute tables only
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_graph import DEFAULT_CEILING, DEFAULT_MODEL, run_once  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = REPO_ROOT / "reports" / "hw02" / "cases"
RAW_DIR = REPO_ROOT / "reports" / "hw02" / "raw"

RUNS_JSONL = RAW_DIR / "graph_runs.jsonl"
RUNS_CSV = RAW_DIR / "graph_runs.csv"
METRICS_JSON = RAW_DIR / "hw02_metrics.json"

OUTCOMES = [
    "valid first attempt",
    "valid after 1 retry",
    "valid after 2+ retries",
    "hit turn ceiling",
]

# name -> (case file, turn ceiling, number of runs)
EXPERIMENTS: Dict[str, Dict[str, Any]] = {
    "schema30": {"case": "schema_input.json", "ceiling": DEFAULT_CEILING, "runs": 30},
    "ceiling2": {"case": "schema_input.json", "ceiling": 2, "runs": 20},
    "ceiling10": {"case": "schema_input.json", "ceiling": 10, "runs": 20},
    "adversarial": {"case": "adversarial_input.json", "ceiling": DEFAULT_CEILING, "runs": 5},
}


def load_case(name: str) -> Dict[str, str]:
    data = json.loads((CASES_DIR / name).read_text(encoding="utf-8"))
    return {"title": data["title"], "content": data["content"], "case_id": data["case_id"]}


def load_existing() -> List[Dict[str, Any]]:
    if not RUNS_JSONL.exists():
        return []
    rows = []
    for line in RUNS_JSONL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def append_run(record: Dict[str, Any]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with RUNS_JSONL.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# running
# ---------------------------------------------------------------------------


def run_experiment(name: str, model: str, temperature: float, done: set) -> None:
    spec = EXPERIMENTS[name]
    case = load_case(spec["case"])
    total = spec["runs"]

    print()
    print("=" * 72)
    print(f"EXPERIMENT {name}: {total} runs, ceiling {spec['ceiling']}, case {case['case_id']}")
    print("=" * 72)

    elapsed: List[float] = []

    for index in range(1, total + 1):
        if (name, index) in done:
            print(f"[{name} {index}/{total}] already recorded, skipping")
            continue

        started = time.perf_counter()
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        print(f"\n[{name} {index}/{total}] {stamp}")

        record = run_once(
            title=case["title"],
            content=case["content"],
            turn_ceiling=spec["ceiling"],
            model=model,
            temperature=temperature,
            stream=False,
        )
        record.update(
            {
                "experiment": name,
                "run_index": index,
                "case_id": case["case_id"],
                "started_at": stamp,
            }
        )
        append_run(record)

        seconds = time.perf_counter() - started
        elapsed.append(seconds)
        remaining = (total - index) * (sum(elapsed) / len(elapsed))
        print(
            f"[{name} {index}/{total}] {record['outcome']} "
            f"({record['turn_count']} turns, {seconds:.1f}s) "
            f"- about {remaining / 60:.1f} min left in this experiment"
        )


# ---------------------------------------------------------------------------
# summarising
# ---------------------------------------------------------------------------


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return round(statistics.mean(values), 1) if values else 0.0


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_experiment: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_experiment[row["experiment"]].append(row)

    summary: Dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "experiments": {},
    }

    for name, runs in by_experiment.items():
        counts = Counter(r["outcome"] for r in runs)
        completed = [r for r in runs if r["status"] == "complete"]
        latencies = [r["latency_ms"] for r in runs]

        summary["experiments"][name] = {
            "runs": len(runs),
            "turn_ceiling": runs[0]["turn_ceiling"],
            "case_id": runs[0].get("case_id"),
            "model": runs[0]["model"],
            "temperature": runs[0]["temperature"],
            "outcomes": {outcome: counts.get(outcome, 0) for outcome in OUTCOMES},
            "completion_rate": round(len(completed) / len(runs), 4),
            "mean_latency_ms": mean(latencies),
            "mean_latency_ms_completed": mean(r["latency_ms"] for r in completed),
            "median_latency_ms": round(statistics.median(latencies), 1),
            "mean_turns": mean(r["turn_count"] for r in runs),
            "mean_planner_attempts": mean(r["planner_attempts"] for r in runs),
            "mean_llm_calls": mean(r["llm_calls"] for r in runs),
            "distinct_tag_sets": len({tuple(sorted((r.get("planner_proposal") or {}).get("tags", []))) for r in completed}),
        }

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def write_csv(rows: List[Dict[str, Any]]) -> None:
    fields = [
        "experiment", "run_index", "case_id", "started_at", "outcome", "status",
        "turn_count", "turn_ceiling", "planner_attempts", "reviewer_attempts",
        "llm_calls", "latency_ms", "input_tokens", "output_tokens",
        "model", "temperature", "tags", "summary", "summary_word_count",
        "first_validation_error",
    ]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with RUNS_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            proposal = row.get("planner_proposal") or {}
            summary_text = proposal.get("summary", "")
            first_error = next(
                (h.get("error", "") for h in row.get("history", []) if h.get("valid") is False),
                "",
            )
            writer.writerow(
                {
                    **{k: row.get(k, "") for k in fields if k in row},
                    "tags": " | ".join(proposal.get("tags", [])),
                    "summary": summary_text,
                    "summary_word_count": len(summary_text.split()),
                    "first_validation_error": first_error,
                }
            )


def print_tables(summary: Dict[str, Any]) -> None:
    experiments = summary["experiments"]

    if "schema30" in experiments:
        block = experiments["schema30"]
        print()
        print(f"Part 4.3 - {block['runs']} runs on the frozen input, ceiling {block['turn_ceiling']}")
        print(f"{'Outcome over ' + str(block['runs']) + ' runs':<26}{'Count':>7}{'Mean latency (ms)':>22}")
        rows = [r for r in RUNS_BY_EXPERIMENT.get("schema30", [])]
        for outcome in OUTCOMES:
            matching = [r["latency_ms"] for r in rows if r["outcome"] == outcome]
            print(f"{outcome:<26}{block['outcomes'][outcome]:>7}{(mean(matching) if matching else 0):>22}")

    if "ceiling2" in experiments and "ceiling10" in experiments:
        print()
        print("Part 4.4 - turn ceiling comparison, same input and model settings")
        print(f"{'Metric':<30}{'ceiling 2':>14}{'ceiling 10':>14}")
        a, b = experiments["ceiling2"], experiments["ceiling10"]
        for label, key, fmt in [
            ("runs", "runs", "{}"),
            ("completion rate", "completion_rate", "{:.0%}"),
            ("mean latency (ms)", "mean_latency_ms", "{}"),
            ("mean latency, completed (ms)", "mean_latency_ms_completed", "{}"),
            ("mean turns used", "mean_turns", "{}"),
            ("mean planner attempts", "mean_planner_attempts", "{}"),
            ("mean model calls", "mean_llm_calls", "{}"),
        ]:
            print(f"{label:<30}{fmt.format(a[key]):>14}{fmt.format(b[key]):>14}")

    if "adversarial" in experiments:
        block = experiments["adversarial"]
        print()
        print(f"Part 4.5 - adversarial input, {block['runs']} runs, ceiling {block['turn_ceiling']}")
        for outcome in OUTCOMES:
            print(f"{outcome:<26}{block['outcomes'][outcome]:>7}")
        print(f"{'completion rate':<26}{block['completion_rate']:>7.0%}")


RUNS_BY_EXPERIMENT: Dict[str, List[Dict[str, Any]]] = defaultdict(list)


def main() -> int:
    parser = argparse.ArgumentParser(description="HW2 Part 4 experiments")
    parser.add_argument("--all", action="store_true", help="run every experiment")
    parser.add_argument("--experiment", choices=sorted(EXPERIMENTS), default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--restart", action="store_true", help="ignore runs already recorded")
    parser.add_argument("--summarize", action="store_true", help="only rebuild the tables")
    args = parser.parse_args()

    existing = load_existing()
    done = set() if args.restart else {(r["experiment"], r["run_index"]) for r in existing}

    if not args.summarize:
        names = sorted(EXPERIMENTS) if args.all else ([args.experiment] if args.experiment else [])
        if not names:
            parser.error("pass --all, --experiment NAME, or --summarize")
        # deterministic, cheapest-first order so a short session still finishes
        # whole experiments rather than leaving several half done
        order = ["schema30", "ceiling2", "ceiling10", "adversarial"]
        for name in [n for n in order if n in names]:
            run_experiment(name, args.model, args.temperature, done)

    rows = load_existing()
    if not rows:
        print("no runs recorded yet")
        return 1

    for row in rows:
        RUNS_BY_EXPERIMENT[row["experiment"]].append(row)

    write_csv(rows)
    summary = summarize(rows)
    print_tables(summary)

    print()
    print(f"raw runs   : {RUNS_JSONL}")
    print(f"flat table : {RUNS_CSV}")
    print(f"aggregates : {METRICS_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
