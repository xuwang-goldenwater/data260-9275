"""
HW10 self-check (smoke test) -> reports/hw10/verification.json

    make verify-hw10

Needs nothing running: no Kafka, Redis, Ollama or agents. Everything that used a
model or Kafka is checked from the saved evidence in reports/hw10/; the tracing
module and the three dashboard pages are executed for real.

  Repo    no uncommitted changes outside reports/; eval_cases.json + human_labels.csv
          committed before any Part 3 judge result, labels never edited afterwards
  Part 4  span schema; one identifier (every agent/evaluator span belongs to a request
          that has a gateway span); tracing.span() records ok + error and re-raises;
          50 latency requests = 50 confirmed misses with the full stage path;
          p50/p95 table recomputed from spans.jsonl; hit / miss / failed examples
  Part 2  every evaluation has the four criteria on 1-5 with reasons, the original
          texts, Kafka sources for plan/draft/final, difference = final - draft;
          judge is local; the failed trace produced an "incomplete" evaluation
  Part 3  20 cases, 20 human labels 1-5, 3 judge runs; Spearman, MAD and
          repeatability recomputed from judge_runs.csv
  Part 1  dashboard uses st.cache_data + st.cache_resource; Summary, Evaluation and
          Trace pages run without exceptions on the saved evidence
"""
import csv
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code" / "observability"))

HW10 = ROOT / "reports" / "hw10"
RAW = HW10 / "raw"
P3 = HW10 / "part3"
SID4, SEED, VERIFY_SEED = 9275, 9275, 269275
AGENT_STAGES = {"planner", "writer", "reviewer", "queue_wait", "evaluation"}
checks = []


def check(name, ok, detail=""):
    checks.append({"name": name, "passed": bool(ok), "detail": str(detail)})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")
    return bool(ok)


def safe(name, fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        check(name, False, f"error: {type(exc).__name__}: {str(exc)[:200]}")


def git(*args):
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).rstrip("\n")
    except Exception:  # noqa: BLE001
        return None


def load(path):
    return json.loads(Path(path).read_text())


def jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def pct(values, p):
    import numpy as np
    return round(float(np.percentile(values, p)), 1)


# ---------------------------------------------------------------- repo
def repo_order():
    def first(path):
        out = git("log", "--diff-filter=A", "--format=%ct %h", "--", path) or ""
        return out.splitlines()[-1].split() if out else None
    labels, cases = first("reports/hw10/human_labels.csv"), first("reports/hw10/eval_cases.json")
    judge = first("reports/hw10/part3/judge_validation.json")
    check("Repo: eval_cases.json + human_labels.csv committed before the first Part 3 judge result",
          labels and cases and judge and int(labels[0]) < int(judge[0]) and int(cases[0]) < int(judge[0]),
          f"labels {labels}, cases {cases}, judge {judge}")
    edits = (git("log", "--format=%h", "--", "reports/hw10/human_labels.csv") or "").split()
    check("Repo: human_labels.csv never edited after it was committed", len(edits) == 1, edits)


# ---------------------------------------------------------------- Part 4
def part4():
    spans = jsonl(RAW / "spans.jsonl")
    need = {"trace_id", "stage", "start_ts", "end_ts", "duration_ms", "status", "error"}
    check("P4.1: every span has trace_id, stage, start, end, duration, status, error",
          all(need <= s.keys() for s in spans), f"{len(spans)} spans")
    gateway_ids = {s["trace_id"] for s in spans if s["stage"] == "gateway"}
    orphans = {s["trace_id"] for s in spans if s["stage"] in AGENT_STAGES} - gateway_ids
    check("P4.1: one identifier - every agent/evaluator span belongs to a request with a gateway span",
          not orphans, f"{len(gateway_ids)} requests, orphans={sorted(orphans)[:3]}")
    check("P4.1: cache_lookup span on every request, hit/miss recorded",
          gateway_ids <= {s["trace_id"] for s in spans if s["stage"] == "cache_lookup"
                          and s.get("cache") in ("hit", "miss")})

    import tracing
    tmp = Path(tempfile.mkdtemp()) / "spans.jsonl"
    tracing.SPANS_FILE = tmp
    with tracing.span("t-verify", "planner") as s:
        s["x"] = 1
    raised = False
    try:
        with tracing.span("t-verify", "writer"):
            raise RuntimeError("boom")
    except RuntimeError:
        raised = True
    got = jsonl(tmp)
    check("P4.1: tracing.span() writes ok and error spans and re-raises the error",
          raised and [g["status"] for g in got] == ["ok", "error"] and "boom" in got[1]["error"]
          and got[0]["x"] == 1, [(g["stage"], g["status"]) for g in got])

    plan = load(RAW / "latency_questions.json")["questions"]
    ids = {q["trace_id"] for q in plan}
    by = {}
    for s in spans:
        if s["trace_id"] in ids:
            by.setdefault(s["trace_id"], []).append(s)
    path = {"cache_lookup", "facts_lookup", "planner", "writer", "reviewer", "gateway", "evaluation"}
    full = [t for t, sp in by.items() if path <= {s["stage"] for s in sp}
            and sorted(s["hop"] for s in sp if s["stage"] == "queue_wait") == ["drafts", "final", "inbox", "tasks"]]
    misses = [t for t, sp in by.items() if any(s["stage"] == "cache_lookup" and s["cache"] == "miss" for s in sp)]
    check("P4.3: 50 latency requests, 50 confirmed cache misses", len(plan) == 50 and len(misses) == 50,
          f"{len(misses)}/{len(plan)}")
    check("P4.3: each has the full path (4 queue hops + evaluation)", len(full) == 50, len(full))
    summ = {r["stage"]: r for r in load(RAW / "latency_summary.json")["table"]}
    ok = True
    for st in ("planner", "writer", "reviewer", "cache_lookup"):
        vals = [s["duration_ms"] for t in full for s in by[t] if s["stage"] == st]
        ok &= summ[st]["p50_ms"] == pct(vals, 50) and summ[st]["p95_ms"] == pct(vals, 95)
    qtot = [sum(s["duration_ms"] for s in by[t] if s["stage"] == "queue_wait") for t in full]
    ok &= summ["queue_wait_total"]["p50_ms"] == pct(qtot, 50)
    check("P4.3: p50/p95 table recomputed from spans.jsonl", ok,
          f"planner p50 {summ['planner']['p50_ms']} ms, {summ['planner']['pct_of_cache_miss_e2e']}% of e2e")

    ex = load(RAW / "trace_examples.json")
    hit = {s["stage"]: s for s in ex["hit"]["spans"]}
    check("P4.2: hit trace = cache_lookup(hit) + gateway, no agent stage",
          hit.get("cache_lookup", {}).get("cache") == "hit" and not AGENT_STAGES & hit.keys(), sorted(hit))
    miss = ex["miss"]["spans"]
    check("P4.2: miss trace completes the agent path, all ok",
          path <= {s["stage"] for s in miss} and all(s["status"] == "ok" for s in miss), len(miss))
    fail = {s["stage"]: s for s in ex["failed"]["spans"]}
    check("P4.2: failed trace - writer error identified, gateway error",
          fail["writer"]["status"] == "error" and "injected failure" in fail["writer"]["error"]
          and fail["gateway"]["status"] == "error", fail["writer"]["error"][:70])


# ---------------------------------------------------------------- Part 2
def part2():
    rows = jsonl(RAW / "eval_results.jsonl")
    ev = [r for r in rows if r["status"] == "evaluated"]
    crit = ("plan_quality", "writer_helpfulness", "final_helpfulness")
    ok = all(all(1 <= r[c]["score"] <= 5 and r[c]["reason"] for c in crit) for r in ev)
    check("P2.2: every evaluation has plan / draft / final scores on 1-5 with reasons", ok and ev, len(ev))
    check("P2.2: final-vs-draft saves both scores, difference = final - draft, interpretation",
          all(r["final_vs_draft"]["difference"] == r["final_vs_draft"]["final_score"] -
              r["final_vs_draft"]["draft_score"] and r["final_vs_draft"]["interpretation"] for r in ev))
    check("P2.1: original texts and Kafka sources (topic/offset) kept for plan, draft, final",
          all(r["draft"] and r["final_answer"] and r["plan"] and
              {"plan", "draft", "final"} <= r["sources"].keys() and
              all("offset" in v for v in r["sources"].values()) for r in ev))
    check("P2.1: judge is a local model", all("qwen" in r["judge"]["model"] for r in ev),
          ev[0]["judge"] if ev else "")
    failed_id = load(RAW / "trace_examples.json")["failed"]["trace_id"]
    check("P2.1: evaluator is bounded - the failed trace was closed as incomplete",
          any(r["trace_id"] == failed_id and r["status"] == "incomplete" for r in rows))


# ---------------------------------------------------------------- Part 3
def part3():
    from scipy.stats import spearmanr
    cases = load(HW10 / "eval_cases.json")["cases"]
    labels = list(csv.DictReader((HW10 / "human_labels.csv").open()))
    check("P3.1: 20 frozen cases and 20 human labels in 1..5",
          len(cases) == 20 and len(labels) == 20 and all(r["human_label"].strip() in {"1", "2", "3", "4", "5"} for r in labels))
    runs = list(csv.DictReader((P3 / "judge_runs.csv").open()))
    val = load(P3 / "judge_validation.json")
    h = [int(r["human_label"]) for r in runs]
    j = [int(r["run1"]) for r in runs]
    rho = round(float(spearmanr(h, j)[0]), 3)
    mad = round(sum(abs(a - b) for a, b in zip(h, j)) / len(h), 3)
    check("P3.2: Spearman and MAD recomputed from judge_runs.csv",
          rho == val["vs_human"]["run1"]["spearman_rho"] and mad == val["vs_human"]["run1"]["mean_abs_diff"],
          f"rho={rho} MAD={mad}")
    changed = sum(len({r["run1"], r["run2"], r["run3"]}) > 1 for r in runs)
    check("P3.3: 3 runs per draft, repeatability recomputed",
          all(r["run1"] and r["run2"] and r["run3"] for r in runs)
          and changed == val["repeatability"]["cases_with_any_change"], f"{changed}/20 changed")


# ---------------------------------------------------------------- Part 1
def part1():
    app = ROOT / "code" / "ops_dashboard" / "app.py"
    src = app.read_text()
    check("P1: dashboard uses st.cache_data and st.cache_resource",
          "@st.cache_data" in src and "@st.cache_resource" in src)
    from streamlit.testing.v1 import AppTest
    body = src[:src.index("st.set_page_config(")].replace(
        "ROOT = Path(__file__).resolve().parents[2]", f'ROOT = Path(r"{ROOT}")')
    tmp = Path(tempfile.mkdtemp())
    results = {}
    for page in ("summary_page", "evaluation_page", "trace_page"):
        f = tmp / f"{page}.py"
        f.write_text(body + f"\n{page}()\n")
        at = AppTest.from_file(str(f), default_timeout=60)
        if page == "trace_page":
            at.session_state["tid"] = load(RAW / "trace_examples.json")["failed"]["trace_id"]
        at.run()
        results[page] = [e.value for e in at.exception]
    check("P1: Summary, Evaluation and Trace pages run without exceptions",
          not any(results.values()), results)


def main():
    print(f"Xu Wang | DATA 260 HW10 self-check | {datetime.now():%Y-%m-%d %H:%M:%S}")
    dirty = [line for line in (git("status", "--porcelain") or "").splitlines()
             if line[3:] and not line[3:].startswith("reports/")]
    check("Repo: no uncommitted changes outside reports/", not dirty, dirty[:5])
    for name, fn in [("Repo", repo_order), ("P4", part4), ("P2", part2), ("P3", part3), ("P1", part1)]:
        safe(name, fn)
    passed = sum(c["passed"] for c in checks)
    result = {"student": "Xu Wang", "homework": "HW10", "sid4": SID4,
              "run_at": datetime.now().isoformat(timespec="seconds"),
              "commit": git("rev-parse", "--short", "HEAD"),
              "agents": "qwen2.5:3b (Ollama, temperature 0, seed 9275) - HW8 Planner/Writer/Reviewer",
              "judge": "qwen3:4b (Ollama, local, temperature 0, seed 9275), DeepEval GEval 1-5",
              "seed": SEED, "verify_seed": VERIFY_SEED,
              "passed": passed, "failed": len(checks) - passed, "checks": checks}
    (HW10 / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n{passed} passed, {len(checks) - passed} failed -> reports/hw10/verification.json")
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
