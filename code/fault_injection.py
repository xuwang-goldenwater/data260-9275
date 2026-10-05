"""
HW5 Part 3 step 20 - reproducible fault injection on the storage layer.

    python code/fault_injection.py        # make fault-injection   (needs MySQL)

150 tool calls: the same 50 calls at each injected failure rate 0%, 20%, 50%.

    call_tool -> RetryingRepo -> FlakyRepo -> MySQLRepo -> MySQL
                 (Part 3 policy)  (this file)

FlakyRepo decides, before every storage attempt, whether that attempt fails.
The decisions come from random.Random(VERIFY_SEED), so the same seed gives the
same success/failure sequence on every run. Latency is real: it includes the
MySQL query and the backoff waits of the retry policy.

Writes reports/hw05/raw/fault_injection_calls.csv    (all 150 calls)
       reports/hw05/raw/fault_injection_summary.json (the table, policy, seed)
"""
import csv
import hashlib
import json
import logging
import math
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from domain_tools import MySQLRepo, call_tool, config
from retry_policy import DEFAULT_POLICY, RetryingRepo, TransientStorageError

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "reports" / "hw05" / "raw"

RATES = (0.0, 0.2, 0.5)
CALLS_PER_RATE = 50


class FlakyRepo:
    """A repo that fails on purpose. One random draw per storage attempt:
    below failure_rate the attempt raises, otherwise it goes to the real repo."""

    def __init__(self, inner, failure_rate: float, rng: random.Random):
        self.inner, self.failure_rate, self.rng = inner, failure_rate, rng
        self.injected = 0

    def _maybe_fail(self):
        if self.rng.random() < self.failure_rate:
            self.injected += 1
            raise TransientStorageError("injected failure")

    def search(self, query, category, limit):
        self._maybe_fail()
        return self.inner.search(query, category, limit)

    def get(self, recall_number):
        self._maybe_fail()
        return self.inner.get(recall_number)

    def summary(self, group_by, year):
        self._maybe_fail()
        return self.inner.summary(group_by, year)


def call_plan() -> list[tuple[str, dict]]:
    """The 50 calls, the same for every rate: the three tools in turn, all valid inputs."""
    queries = ["peanut butter", "hummus", "yogurt", "shrimp", "granola", "cookies", "spinach"]
    numbers = ["F-0001-2025", "F-0002-2021", "F-0003-2023", "F-0004-2026", "F-0005-2025"]
    summaries = [{"group_by": "category"}, {"group_by": "state", "year": 2025},
                 {"group_by": "year"}, {"group_by": "firm", "year": 2024}]
    plan = []
    for i in range(CALLS_PER_RATE):
        turn = i // 3
        if i % 3 == 0:
            plan.append(("search_notices", {"query": queries[turn % len(queries)], "limit": 5}))
        elif i % 3 == 1:
            plan.append(("get_notice", {"recall_number": numbers[turn % len(numbers)]}))
        else:
            plan.append(("recall_summary", summaries[turn % len(summaries)]))
    return plan


def expected_attempts(rate: float, seed: int) -> list[int]:
    """What the seed alone predicts, with no database involved: for each call,
    the attempt that succeeds (1, 2, 3) or 0 when all allowed attempts fail."""
    rng = random.Random(seed)
    outcome = []
    for _ in range(CALLS_PER_RATE):
        won = 0
        for attempt in range(1, DEFAULT_POLICY.max_attempts + 1):
            if rng.random() >= rate:
                won = attempt
                break
        outcome.append(won)
    return outcome


def p99(values: list[float]) -> float:
    """Nearest-rank 99th percentile: the smallest value with at least 99% of
    the sample at or below it. With 50 values that is the largest one."""
    ordered = sorted(values)
    return ordered[math.ceil(0.99 * len(ordered)) - 1]


def run_rate(rate: float, mysql: MySQLRepo) -> list[dict]:
    flaky = FlakyRepo(mysql, rate, random.Random(config.VERIFY_SEED))
    repo = RetryingRepo(flaky, DEFAULT_POLICY)
    rows = []
    for number, (tool, inputs) in enumerate(call_plan(), start=1):
        injected_before = flaky.injected
        started = time.perf_counter()
        envelope = call_tool(tool, inputs, repo)
        latency_ms = (time.perf_counter() - started) * 1000
        rows.append({
            "failure_rate": rate,
            "call_no": number,
            "tool": tool,
            "inputs": json.dumps(inputs),
            "ok": envelope["ok"],
            "attempts": len(repo.last_attempts),
            "injected_failures": flaky.injected - injected_before,
            "latency_ms": round(latency_ms, 3),
            "error": envelope["error"] or "",
        })
    return rows


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.CRITICAL)   # failures are expected here
    print(f"{config.DEMO_NAME} | DATA 260 HW5 Part 3 | {config.PREFIX} | fault injection | "
          f"{datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"VERIFY_SEED {config.VERIFY_SEED} | {CALLS_PER_RATE} calls per rate | "
          f"policy: {DEFAULT_POLICY.describe()}")

    mysql = MySQLRepo()
    mysql.get("F-0001-2025")            # open the connection first, so call 1 is not timed with it

    all_rows, summary_rows = [], []
    print("\nper call: 1/2/3 = succeeded on that attempt, X = failed after every allowed attempt")
    for rate in RATES:
        rows = run_rate(rate, mysql)
        all_rows += rows
        strip = "".join(str(r["attempts"]) if r["ok"] else "X" for r in rows)
        predicted = "".join(str(a) if a else "X" for a in expected_attempts(rate, config.VERIFY_SEED))
        latencies = [r["latency_ms"] for r in rows]
        succeeded = sum(r["ok"] for r in rows)
        summary_rows.append({
            "failure_rate": rate,
            "calls": len(rows),
            "succeeded": succeeded,
            "success_rate_pct": round(100 * succeeded / len(rows), 1),
            "mean_latency_ms": round(sum(latencies) / len(latencies), 2),
            "p99_latency_ms": round(p99(latencies), 2),
            "max_latency_ms": round(max(latencies), 2),
            "storage_attempts": sum(r["attempts"] for r in rows),
            "injected_failures": sum(r["injected_failures"] for r in rows),
            "sequence": strip,
            "matches_seed_prediction": strip == predicted,
        })
        print(f"{rate:>4.0%}  {strip}  {'= seed prediction' if strip == predicted else '!= seed prediction: ' + predicted}")

    signature = hashlib.sha256(
        json.dumps([[r["failure_rate"], r["call_no"], r["attempts"], r["ok"]] for r in all_rows]).encode()
    ).hexdigest()

    print("\nInjected failure rate | Success rate | Mean latency (ms) | p99 latency (ms) | attempts | injected")
    for s in summary_rows:
        print(f"{s['failure_rate']:>21.0%} | {s['success_rate_pct']:>10.1f} % | {s['mean_latency_ms']:>17.2f} | "
              f"{s['p99_latency_ms']:>16.2f} | {s['storage_attempts']:>8} | {s['injected_failures']:>8}")
    print(f"\nsequence signature (same seed -> same value): {signature[:16]}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    calls_file = RAW_DIR / "fault_injection_calls.csv"
    with calls_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)
    summary_file = RAW_DIR / "fault_injection_summary.json"
    summary_file.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "verify_seed": config.VERIFY_SEED,
        "calls_per_rate": CALLS_PER_RATE,
        "policy": {"max_attempts": DEFAULT_POLICY.max_attempts, "timeout_s": DEFAULT_POLICY.timeout_s,
                   "base_delay_s": DEFAULT_POLICY.base_delay_s, "multiplier": DEFAULT_POLICY.multiplier,
                   "max_delay_s": DEFAULT_POLICY.max_delay_s},
        "p99_method": "nearest rank; with 50 values it equals the maximum",
        "storage": f"MySQL {config.DB_NAME}",
        "sequence_signature_sha256": signature,
        "rates": summary_rows,
    }, indent=2), encoding="utf-8")
    print(f"wrote {calls_file.relative_to(ROOT)} ({len(all_rows)} rows)")
    print(f"wrote {summary_file.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
