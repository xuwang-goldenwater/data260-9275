"""
DATA 260 - HW10 Part 4.2: the three required trace examples.

    hit     - a question already in the semantic cache: cache_lookup (hit) + gateway, no Kafka
    miss    - an approved cache miss from the 50-request latency run (full agent path + evaluation)
    failed  - a new cache miss sent with {"fail_at": "writer"}: the Writer raises, retries 3 times,
              sends the message to s9275_dead_letter, and its span is status=error; the gateway
              gives up after AGENT_TIMEOUT_S (60 s here) and its span is status=error too;
              the evaluator never gets a draft and writes an "incomplete" evaluation span.

Writes reports/hw10/raw/trace_examples.json (the three trace_ids + their spans in stage
order), which the Streamlit Trace page and the report use.

Needs the same processes as the latency run (planner, writer, reviewer, evaluator).
    python code/eval_pipeline/trace_examples.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["CACHE_STORE"] = "0"                       # the failed/hit demos must not change the cache
os.environ["AGENT_TIMEOUT_S"] = "60"
os.environ.setdefault("CACHE_QUERY_LOG", str(ROOT / "reports/hw10/raw/trace_example_queries.jsonl"))
for sub in ("code", "code/auth_app", "code/cache_app", "code/observability"):
    sys.path.insert(0, str(ROOT / sub))

from latency_experiment import load_spans, wait_for  # noqa: E402
from semantic_cache import SemanticCache  # noqa: E402

RAW = ROOT / "reports/hw10/raw"
OUT = RAW / "trace_examples.json"
HIT_QUESTION = "Which firm issued recall F-0002-2021?"       # cached since HW9
FAIL_QUESTION = "How many units were affected by recall F-1000-2022?"


def journey(trace_id: str) -> list[dict]:
    spans = [s for s in load_spans() if s["trace_id"] == trace_id]
    return sorted(spans, key=lambda s: (s["start_ts"], s["end_ts"]))


def show(label: str, trace_id: str) -> None:
    print(f"\n== {label}  trace_id={trace_id}")
    for s in journey(trace_id):
        extra = s.get("hop") or s.get("cache") or s.get("review_status") or ""
        err = f"  ERROR: {s['error']}" if s.get("error") else ""
        print(f"  {s['start_ts'][11:]} -> {s['end_ts'][11:]}  {s['stage']:13s} {extra:8s} "
              f"{s['duration_ms']:9.1f} ms  {s['status']}{err}")


def main() -> None:
    cache = SemanticCache()

    hit = cache.ask(HIT_QUESTION)
    if not hit["is_cached"]:
        raise SystemExit(f"{HIT_QUESTION!r} was not a cache hit - pick a question that is cached")
    hit_id = hit["trace_id"]

    miss_id = next(json.loads(line)["trace_id"]
                   for line in (RAW / "eval_results.jsonl").read_text().splitlines()
                   if json.loads(line).get("review_status") == "approved")

    try:
        failed = cache.ask(FAIL_QUESTION, extra={"fail_at": "writer"})
        raise SystemExit(f"expected a failure, got {failed}")
    except TimeoutError as exc:
        print(f"failed request, as intended: {exc}")
    failed_id = next(s["trace_id"] for s in reversed(load_spans())
                     if s["stage"] == "gateway" and s["status"] == "error")
    print("waiting for the evaluator's join timeout on the failed trace ...")
    wait_for(failed_id, "evaluation", 200)

    for label, tid in (("CACHE HIT", hit_id), ("CACHE MISS (approved)", miss_id), ("FAILED", failed_id)):
        show(label, tid)
    OUT.write_text(json.dumps({
        "hit": {"trace_id": hit_id, "question": HIT_QUESTION, "spans": journey(hit_id)},
        "miss": {"trace_id": miss_id, "spans": journey(miss_id)},
        "failed": {"trace_id": failed_id, "question": FAIL_QUESTION, "injected": {"fail_at": "writer"},
                   "spans": journey(failed_id)},
    }, indent=2))
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
