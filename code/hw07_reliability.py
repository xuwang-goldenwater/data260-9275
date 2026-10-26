"""
HW7 Part 2-III - tool-use reliability over the three fixed tasks.

    python code/hw07_reliability.py            (make reliability-hw07, ~10-15 min)
    python code/hw07_reliability.py 2          (2 attempts per task, quick try)

21 attempts = 7 per task (A, B, C). Same settings for every attempt:
qwen2.5:3b, temperature 0.7, num_ctx 8192, MAX_ITERATIONS 6, MAX_REPAIRS 2.
Attempt i uses seed SEED + i, so the whole batch can be replayed.

Call-level metrics ("slot" = one call the model had to get right; a retry
after a repair prompt is the same slot):
    well-formed rate before repair = slots right on the first try / all slots
    well-formed rate after repair  = slots right after the repair path / all slots
Failure types:
    malformed_arguments, unknown_tool, text_when_tool_required  (per failed slot)
    lost_multi_step_chain  (per attempt: the run ended without the required
                            tool sequence, judged by the task's deterministic check)

Writes reports/hw07/raw/reliability_attempts.csv, reliability_runs.jsonl and
reliability_summary.json.
"""
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from agent_hw07 import MAX_ITERATIONS, MAX_REPAIRS, MODEL_NAME, default_model, run_agent
from domain_tools import config
from hw07_tasks import TASKS

RAW = Path(__file__).resolve().parent.parent / "reports" / "hw07" / "raw"
TEMPERATURE = 0.7
CALL_FAILURES = ("malformed_arguments", "unknown_tool", "text_when_tool_required")


def slot_counts(run: dict) -> dict:
    """First-try slots, how many were right first time, how many failed / got repaired."""
    first_try_calls = [c for c in run["calls"] if not c["repair_turn"]]
    first_try_ok = sum(c["well_formed"] for c in first_try_calls)
    failed_slots = {}
    for f in run["failures"]:
        failed_slots.setdefault(f["slot"], f)            # first failure of each slot = its type
    # a failed first-try *call* is already in first_try_calls; a text reply is an extra slot
    text_slots = sum(1 for f in failed_slots.values() if f["type"] == "text_when_tool_required")
    return {"slots": len(first_try_calls) + text_slots,
            "first_try_ok": first_try_ok,
            "repaired": sum(1 for f in failed_slots.values() if f["repaired"]),
            "failed_by_type": Counter(f["type"] for f in failed_slots.values())}


def main() -> None:
    per_task = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    print(f"{config.DEMO_NAME} | DATA 260 HW7 Part 2 | reliability | model {MODEL_NAME} | "
          f"temperature {TEMPERATURE} | {per_task} attempts x {len(TASKS)} tasks | "
          f"{datetime.now():%Y-%m-%d %H:%M:%S}")
    RAW.mkdir(parents=True, exist_ok=True)
    rows, attempt = [], 0
    runs_file = (RAW / "reliability_runs.jsonl").open("w", encoding="utf-8")
    for round_no in range(per_task):
        for key, task in TASKS.items():
            attempt += 1
            seed = config.SEED + attempt
            print(f"\n--- attempt {attempt} | task {key} | seed {seed}")
            run = run_agent(task["question"], model=default_model(TEMPERATURE, seed))
            check = task["verify"](run)
            counts = slot_counts(run)
            lost_chain = not check["chain_ok"] and run["stop_reason"] != "repair_failed"
            row = {"attempt": attempt, "task": key, "seed": seed,
                   "stop_reason": run["stop_reason"], "tool_calls": run["tool_calls_total"],
                   "slots": counts["slots"], "first_try_ok": counts["first_try_ok"],
                   "repaired": counts["repaired"],
                   **{t: counts["failed_by_type"].get(t, 0) for t in CALL_FAILURES},
                   "lost_multi_step_chain": int(lost_chain), "chain_ok": check["chain_ok"],
                   "task_passed": check["passed"], "tokens": run["tokens"],
                   "latency_ms": run["latency_ms"], "check": "; ".join(check["reasons"])}
            rows.append(row)
            print(f"    check: {'PASS' if check['passed'] else 'FAIL'} - {row['check']}")
            runs_file.write(json.dumps({"attempt": attempt, "task": key, "check": check, "run": run},
                                       default=str) + "\n")
            runs_file.flush()
    runs_file.close()

    with (RAW / "reliability_attempts.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    slots = sum(r["slots"] for r in rows)
    first_ok = sum(r["first_try_ok"] for r in rows)
    repaired = sum(r["repaired"] for r in rows)
    summary = {
        "model": MODEL_NAME, "temperature": TEMPERATURE, "num_ctx": 8192,
        "max_iterations": MAX_ITERATIONS, "max_repairs": MAX_REPAIRS,
        "seeds": f"{config.SEED + 1}..{config.SEED + attempt}", "attempts": len(rows),
        "call_slots": slots,
        "well_formed_before_repair": first_ok, "well_formed_after_repair": first_ok + repaired,
        "rate_before_repair": round(first_ok / slots, 3) if slots else None,
        "rate_after_repair": round((first_ok + repaired) / slots, 3) if slots else None,
        "failures": {**{t: sum(r[t] for r in rows) for t in CALL_FAILURES},
                     "lost_multi_step_chain": sum(r["lost_multi_step_chain"] for r in rows)},
        "task_success": {k: f"{sum(r['task_passed'] for r in rows if r['task'] == k)}/"
                            f"{sum(1 for r in rows if r['task'] == k)}" for k in TASKS},
        "task_success_total": f"{sum(r['task_passed'] for r in rows)}/{len(rows)}",
        "total_tool_calls": sum(r["tool_calls"] for r in rows),
    }
    (RAW / "reliability_summary.json").write_text(json.dumps(summary, indent=2))

    print("\n================ reliability summary ================")
    print(f"attempts: {len(rows)}   call slots: {slots}   total tool calls: {summary['total_tool_calls']}")
    print(f"well-formed before repair: {first_ok}/{slots} = {summary['rate_before_repair']}")
    print(f"well-formed after repair:  {first_ok + repaired}/{slots} = {summary['rate_after_repair']}")
    for name, n in summary["failures"].items():
        print(f"  {name:<26} {n}")
    print(f"task success: {summary['task_success']}  total {summary['task_success_total']}")
    print(f"wrote {RAW}/reliability_attempts.csv, reliability_runs.jsonl, reliability_summary.json")


if __name__ == "__main__":
    main()
