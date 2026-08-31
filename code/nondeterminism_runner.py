"""
DATA 260 - Homework 1, Part 3: measuring non-determinism.

Runs the agents_demo pipeline on one frozen input N times at each temperature
and reports how much the output varies.

Every run is appended to a JSONL file as soon as it finishes, so a crash or an
interrupt loses at most one run. Re-running the script resumes from where it
stopped instead of starting over.

Usage:
    python nondeterminism_runner.py
    python nondeterminism_runner.py --runs 20 --temperatures 0.7 0.0
    python nondeterminism_runner.py --report-only
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents_demo import run_pipeline  # noqa: E402
from model_client import DEFAULT_MODEL  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = REPO_ROOT / "reports" / "hw01" / "cases" / "nondeterminism_input.json"
RAW_DIR = REPO_ROOT / "reports" / "hw01" / "raw"
JSONL_PATH = RAW_DIR / "nondeterminism_runs.jsonl"
CSV_PATH = RAW_DIR / "nondeterminism_runs.csv"
METRICS_PATH = RAW_DIR / "nondeterminism_metrics.json"


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_completed() -> List[Dict[str, Any]]:
    if not JSONL_PATH.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in JSONL_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def append_run(row: Dict[str, Any]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with JSONL_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def percentile(values: List[float], p: float) -> float:
    """Nearest-rank percentile. Stable for small samples such as n = 20."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100.0 * len(ordered)))
    return ordered[rank - 1]


def summarize(rows: List[Dict[str, Any]], temperature: float) -> Dict[str, Any]:
    subset = [r for r in rows if r["temperature"] == temperature]
    n = len(subset)
    if n == 0:
        return {"temperature": temperature, "runs": 0}

    # A tag set is compared without regard to order.
    tag_sets = [tuple(sorted(r["tags"])) for r in subset]
    distinct = len(set(tag_sets))

    per_tag_runs = Counter()
    for r in subset:
        for tag in set(r["tags"]):
            per_tag_runs[tag] += 1

    in_all = sorted(t for t, c in per_tag_runs.items() if c == n)
    in_exactly_one = sorted(t for t, c in per_tag_runs.items() if c == 1)

    latencies = [r["latency_ms"] for r in subset]

    return {
        "temperature": temperature,
        "runs": n,
        "distinct_tag_sets": distinct,
        "tags_in_all_runs": in_all,
        "tags_in_exactly_one_run": in_exactly_one,
        "distinct_tags_seen": len(per_tag_runs),
        "tag_frequency": dict(per_tag_runs.most_common()),
        "latency_ms": {
            "p50": round(percentile(latencies, 50), 1),
            "p95": round(percentile(latencies, 95), 1),
            "p99": round(percentile(latencies, 99), 1),
            "min": round(min(latencies), 1),
            "max": round(max(latencies), 1),
            "mean": round(sum(latencies) / n, 1),
        },
        "reviewer_changed_count": sum(1 for r in subset if r["reviewer_changed"]),
        "distinct_summaries": len({r["summary"] for r in subset}),
    }


def write_csv(rows: List[Dict[str, Any]]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    fields = [
        "run_index", "temperature", "timestamp", "model",
        "tag_1", "tag_2", "tag_3", "tag_set",
        "summary", "summary_word_count",
        "reviewer_changed", "latency_ms", "total_tokens",
    ]
    with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            tags = list(r["tags"]) + ["", "", ""]
            writer.writerow({
                "run_index": r["run_index"],
                "temperature": r["temperature"],
                "timestamp": r["timestamp"],
                "model": r.get("model", ""),
                "tag_1": tags[0],
                "tag_2": tags[1],
                "tag_3": tags[2],
                "tag_set": " | ".join(sorted(r["tags"])),
                "summary": r["summary"],
                "summary_word_count": r.get("summary_word_count", ""),
                "reviewer_changed": r["reviewer_changed"],
                "latency_ms": r["latency_ms"],
                "total_tokens": r.get("total_tokens", ""),
            })


def print_report(rows: List[Dict[str, Any]], temperatures: List[float]) -> Dict[str, Any]:
    metrics = {
        "generated_at": now(),
        "case_file": str(CASE_PATH.relative_to(REPO_ROOT)),
        "by_temperature": {str(t): summarize(rows, t) for t in temperatures},
    }

    print()
    print("=" * 78)
    print("PART 3 RESULTS")
    print("=" * 78)

    labels = [f"Temp {t}" for t in temperatures]
    col = 26
    print(f"{'Metric':<30}" + "".join(f"{l:<{col}}" for l in labels))
    print("-" * (30 + col * len(labels)))

    def row(name: str, getter) -> None:
        cells = []
        for t in temperatures:
            s = metrics["by_temperature"][str(t)]
            cells.append(str(getter(s)) if s.get("runs") else "-")
        print(f"{name:<30}" + "".join(f"{c:<{col}}" for c in cells))

    row("Runs completed", lambda s: s["runs"])
    row("Distinct tag sets", lambda s: s["distinct_tag_sets"])
    row("Tags in all runs", lambda s: len(s["tags_in_all_runs"]))
    row("Tags in exactly 1 run", lambda s: len(s["tags_in_exactly_one_run"]))
    row("Distinct summaries", lambda s: s["distinct_summaries"])
    row("Reviewer changed (count)", lambda s: s["reviewer_changed_count"])
    row("Latency p50 (ms)", lambda s: s["latency_ms"]["p50"])
    row("Latency p95 (ms)", lambda s: s["latency_ms"]["p95"])
    row("Latency p99 (ms)", lambda s: s["latency_ms"]["p99"])

    for t in temperatures:
        s = metrics["by_temperature"][str(t)]
        if not s.get("runs"):
            continue
        print()
        print(f"--- Temperature {t} ---")
        print(f"  tags present in all {s['runs']} runs : {s['tags_in_all_runs'] or 'none'}")
        print(f"  tags present in exactly 1 run     : {s['tags_in_exactly_one_run'] or 'none'}")
        print("  tag frequency (tag: runs out of %d)" % s["runs"])
        for tag, count in s["tag_frequency"].items():
            print(f"      {count:>3}  {tag}")

    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print()
    print(f"raw per-run JSONL : {JSONL_PATH.relative_to(REPO_ROOT)}")
    print(f"raw per-run CSV   : {CSV_PATH.relative_to(REPO_ROOT)}")
    print(f"metrics JSON      : {METRICS_PATH.relative_to(REPO_ROOT)}")
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Part 3 non-determinism experiment")
    parser.add_argument("--runs", type=int, default=20, help="runs per temperature")
    parser.add_argument("--temperatures", type=float, nargs="+", default=[0.7, 0.0])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--report-only", action="store_true",
                        help="recompute the tables from existing raw data")
    args = parser.parse_args()

    case = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    title, content = case["title"], case["content"]

    rows = load_completed()

    if not args.report_only:
        print(f"[{now()}] case file : {CASE_PATH.relative_to(REPO_ROOT)}")
        print(f"[{now()}] model     : {args.model}")
        print(f"[{now()}] plan      : {args.runs} runs at each of {args.temperatures}")
        print(f"[{now()}] already completed: {len(rows)} runs")
        print()

        for temperature in args.temperatures:
            done = sum(1 for r in rows if r["temperature"] == temperature)
            for i in range(done, args.runs):
                started = time.perf_counter()
                try:
                    record = run_pipeline(
                        title=title, content=content,
                        temperature=temperature, model=args.model,
                        verbose=False,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"[{now()}] temp={temperature} run={i + 1} FAILED: {exc}")
                    continue

                row = {
                    "run_index": i + 1,
                    "temperature": temperature,
                    "timestamp": now(),
                    "model": args.model,
                    "tags": record["publish"]["tags"],
                    "summary": record["publish"]["summary"],
                    "summary_word_count": record["summary_word_count"],
                    "reviewer_changed": record["reviewer_changed"],
                    "grounding": record["grounding"],
                    "latency_ms": record["latency_ms"],
                    "total_tokens": record["tokens"]["total"],
                }
                append_run(row)
                rows.append(row)

                elapsed = time.perf_counter() - started
                print(
                    f"[{now()}] temp={temperature} run={i + 1:>2}/{args.runs} "
                    f"{elapsed:6.1f}s  changed={str(row['reviewer_changed']):<5} "
                    f"tags={row['tags']}"
                )

    write_csv(rows)
    print_report(rows, args.temperatures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
