"""
DATA 260 - HW10 Part 4.3: stage-latency experiment on 50 confirmed cache misses.

    python code/eval_pipeline/latency_experiment.py prepare   # build + pre-check 50 questions
    python code/eval_pipeline/latency_experiment.py run       # send them, one at a time
    python code/eval_pipeline/latency_experiment.py analyze   # p50 / p95 table from spans.jsonl

prepare: 50 questions, random.Random(9275), saved with a trace_id each to
    reports/hw10/raw/latency_questions.json
    - 38 questions about real recall records (HW4 rows, id <= 5000) whose recall
      number has no entry in the semantic cache, 6 templates, some two-field
    - 6 about recall numbers that do not exist (not-found path)
    - 6 off-domain questions (refusal path)
  Each question is pre-checked against the cache (embed + KNN + recall guard);
  one that would hit is replaced, so the run is planned as 50 misses.
run: CACHE_STORE=0, so no answer is written to the cache during the run (a later
  question can never hit an earlier one). Requests are sent strictly one after
  another and the next one waits for the evaluator's "evaluation" span of the
  previous one: on this 8 GB Mac the judge (qwen3:4b) and the agents (qwen2.5:3b)
  share the GPU, and overlapping them would inflate the agent stage times.
  Re-running skips trace_ids that already have a gateway span (resumable).
analyze: verifies every cache_lookup span is a miss, then per stage p50 / p95
  and its share of cache-miss end-to-end time (= the gateway span), written to
  reports/hw10/raw/latency_summary.json.

Needs: Kafka, Redis, MySQL, planner/writer/reviewer AND evaluator.py running,
all with the same HW10_SPANS (default reports/hw10/raw/spans.jsonl).
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
os.environ["CACHE_STORE"] = "0"                                  # before semantic_cache is imported
os.environ.setdefault("CACHE_QUERY_LOG", str(ROOT / "reports/hw10/raw/latency_queries.jsonl"))
for sub in ("code", "code/auth_app", "code/cache_app", "code/observability"):
    sys.path.insert(0, str(ROOT / sub))

from tracing import SPANS_FILE, new_trace_id  # noqa: E402

RAW = ROOT / "reports/hw10/raw"
QUESTIONS = RAW / "latency_questions.json"
SUMMARY = RAW / "latency_summary.json"
SEED = 9275
EVAL_WAIT_S = 300

SINGLE = ["How many units were affected by recall {r}?",
          "Which firm issued recall {r}?",
          "When was recall {r} issued?",
          "What product was recalled under {r}?",
          "What is the recall category of {r}?",
          "In which state is the firm behind recall {r} located?"]
TWO_FIELD = ["Which firm issued recall {r}, and how many units were affected?",
             "What product was recalled under {r}, and when was it issued?"]
OFF_DOMAIN = ["What is the tallest mountain in Africa?",
              "How do I change a flat bicycle tyre?",
              "Who painted the ceiling of the Sistine Chapel?",
              "What is a good stretching routine before running?",
              "How many bones are in the adult human body?",
              "Which programming language should I learn first?"]
STAGES = ["cache_lookup", "facts_lookup", "planner", "writer", "reviewer"]


# ---------------------------------------------------------------- prepare
def prepare() -> None:
    from sqlalchemy import text
    from database import db_session_basede26
    from semantic_cache import RECALL_NUMBER, SemanticCache, recall_guard_ok

    cache = SemanticCache()
    cached = set()
    for key in cache.r.scan_iter(match="s9275:semcache:*"):
        q = cache.r.hget(key, "query")
        if q:
            cached |= {m.upper() for m in RECALL_NUMBER.findall(q.decode() if isinstance(q, bytes) else q)}
    with db_session_basede26() as db:
        rows = [r[0] for r in db.execute(text(
            "SELECT recall_number FROM recall_notices WHERE id <= 5000 ORDER BY id"))]
        taken = {r[0] for r in db.execute(text("SELECT recall_number FROM recall_notices"))}
    rng = random.Random(SEED)
    pool = [r for r in rows if r.upper() not in cached]
    rng.shuffle(pool)

    def would_hit(q: str) -> bool:
        best = cache.lookup(cache.embed(q))
        return bool(best and best["similarity"] >= cache.threshold
                    and recall_guard_ok(q, best["query"]))

    out, replaced = [], 0
    def add(kind, q):
        out.append({"n": len(out) + 1, "kind": kind, "question": q, "trace_id": new_trace_id()})

    while sum(o["kind"] == "record" for o in out) < 38:
        r = pool.pop()
        i = sum(o["kind"] == "record" for o in out)
        tmpl = TWO_FIELD[i % 2] if i % 5 == 4 else SINGLE[i % len(SINGLE)]
        q = tmpl.format(r=r)
        if would_hit(q):
            replaced += 1
            continue
        add("record", q)
    while sum(o["kind"] == "not_found" for o in out) < 6:
        num = f"F-{rng.randint(6000, 9999):04d}-{rng.choice([2022, 2023, 2024, 2025])}"
        q = rng.choice(SINGLE).format(r=num)
        if num in taken or would_hit(q):
            replaced += 1
            continue
        add("not_found", q)
    for q in OFF_DOMAIN:
        if would_hit(q):
            raise SystemExit(f"off-domain question would hit the cache, change it: {q!r}")
        add("off_domain", q)
    rng.shuffle(out)
    for i, o in enumerate(out, 1):
        o["n"] = i
    RAW.mkdir(parents=True, exist_ok=True)
    QUESTIONS.write_text(json.dumps({"seed": SEED, "cached_recall_numbers_excluded": sorted(cached),
                                     "replaced_by_precheck": replaced, "questions": out}, indent=2))
    print(f"{len(out)} questions -> {QUESTIONS}  (pre-check replaced {replaced}; "
          f"{len(cached)} cached recall numbers excluded)")


# ---------------------------------------------------------------- spans
def load_spans() -> list[dict]:
    if not SPANS_FILE.exists():
        return []
    return [json.loads(line) for line in SPANS_FILE.read_text().splitlines() if line.strip()]


def wait_for(trace_id: str, stage: str, timeout_s: float) -> dict | None:
    end = time.time() + timeout_s
    while time.time() < end:
        for s in load_spans():
            if s["trace_id"] == trace_id and s["stage"] == stage:
                return s
        time.sleep(2)
    return None


# ---------------------------------------------------------------- run
def run() -> None:
    from semantic_cache import SemanticCache
    plan = json.loads(QUESTIONS.read_text())["questions"]
    done = {s["trace_id"] for s in load_spans() if s["stage"] == "gateway"}
    cache = SemanticCache()
    t_start = time.time()
    for q in plan:
        if q["trace_id"] in done:
            print(f"[{q['n']:2d}/50] already done, skipped")
            continue
        try:
            r = cache.ask(q["question"], trace_id=q["trace_id"])
            line = f"{'HIT!' if r['is_cached'] else 'miss'} {r['latency_ms']:8.0f} ms {r.get('status')}"
        except Exception as exc:                       # recorded in the gateway span already
            line = f"ERROR {type(exc).__name__}: {exc}"
        ev = wait_for(q["trace_id"], "evaluation", EVAL_WAIT_S)
        ev_txt = "no evaluation span" if ev is None else f"eval {ev['duration_ms']/1000:.0f}s {ev['status']}"
        print(f"[{q['n']:2d}/50] {line} | {ev_txt} | {q['question'][:60]}  "
              f"({(time.time() - t_start)/60:.1f} min)", flush=True)


# ---------------------------------------------------------------- analyze
def pct(values, p):
    return round(float(np.percentile(values, p)), 1) if values else None


def analyze() -> None:
    plan = json.loads(QUESTIONS.read_text())["questions"]
    ids = {q["trace_id"] for q in plan}
    by_trace: dict[str, list[dict]] = {}
    for s in load_spans():
        if s["trace_id"] in ids:
            by_trace.setdefault(s["trace_id"], []).append(s)

    lookups = [s for t in by_trace.values() for s in t if s["stage"] == "cache_lookup"]
    misses = [s for s in lookups if s.get("cache") == "miss"]
    complete = [t for t, sp in by_trace.items()
                if any(s["stage"] == "gateway" and s["status"] == "ok" for s in sp)
                and any(s.get("cache") == "miss" for s in sp if s["stage"] == "cache_lookup")]

    rows: dict[str, list[float]] = {k: [] for k in STAGES + ["queue_wait_total", "gateway_overhead",
                                                             "end_to_end", "evaluation"]}
    hops: dict[str, list[float]] = {}
    for t in complete:
        sp = by_trace[t]
        d = {s["stage"]: s["duration_ms"] for s in sp if s["stage"] not in ("queue_wait",)}
        q = [s for s in sp if s["stage"] == "queue_wait"]
        for s in q:
            hops.setdefault(s["hop"], []).append(s["duration_ms"])
        qsum = sum(s["duration_ms"] for s in q)
        for st in STAGES:
            rows[st].append(d.get(st, 0.0))
        rows["queue_wait_total"].append(qsum)
        rows["end_to_end"].append(d["gateway"])
        rows["gateway_overhead"].append(d["gateway"] - qsum - sum(d.get(st, 0.0) for st in STAGES))
        if "evaluation" in d:
            rows["evaluation"].append(d["evaluation"])

    e2e_total = sum(rows["end_to_end"])
    table = []
    for name, vals in rows.items():
        share = None
        if name not in ("end_to_end", "evaluation") and e2e_total:
            share = round(100 * sum(vals) / e2e_total, 1)
        if name == "evaluation" and e2e_total and vals:
            share = round(100 * sum(vals) / e2e_total, 1)        # off the request path, see note
        table.append({"stage": name, "n": len(vals), "p50_ms": pct(vals, 50), "p95_ms": pct(vals, 95),
                      "pct_of_cache_miss_e2e": share})
    summary = {
        "requests_planned": len(plan), "traces_found": len(by_trace),
        "cache_lookup_spans": len(lookups), "cache_lookup_misses": len(misses),
        "all_confirmed_misses": len(lookups) == len(plan) == len(misses),
        "complete_ok_misses": len(complete),
        "table": table,
        "queue_wait_by_hop": {h: {"p50_ms": pct(v, 50), "p95_ms": pct(v, 95)} for h, v in hops.items()},
        "note": ("end_to_end = gateway span (ask() start to final received). Stage shares sum to "
                 "100% with gateway_overhead (consumer join, embedding, result logging). "
                 "evaluation runs after the final answer, off the request path; its share is "
                 "relative to the same end-to-end total for comparison only."),
    }
    SUMMARY.write_text(json.dumps(summary, indent=2))
    print(f"cache_lookup spans {len(lookups)}/{len(plan)}, misses {len(misses)} -> "
          f"all confirmed misses: {summary['all_confirmed_misses']};  complete ok: {len(complete)}")
    print(f"{'stage':18s} {'n':>3s} {'p50 ms':>10s} {'p95 ms':>10s} {'% of e2e':>9s}")
    for r in table:
        share = "" if r["pct_of_cache_miss_e2e"] is None else f"{r['pct_of_cache_miss_e2e']:.1f}"
        print(f"{r['stage']:18s} {r['n']:3d} {r['p50_ms'] or 0:10.1f} {r['p95_ms'] or 0:10.1f} {share:>9s}")
    print("queue wait by hop:", summary["queue_wait_by_hop"])
    print(f"-> {SUMMARY}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"prepare": prepare, "run": run, "analyze": analyze}.get(
        cmd, lambda: sys.exit(__doc__))()
