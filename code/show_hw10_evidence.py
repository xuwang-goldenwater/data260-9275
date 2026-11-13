"""
DATA 260 HW10 - reprint saved results for screenshots (reads files only, runs nothing,
changes nothing). Used because the original terminal output was no longer available.

    python code/show_hw10_evidence.py evaluator   # 2.1 evaluator log for one trace (raw/agent_events.jsonl)
    python code/show_hw10_evidence.py judge       # 3.2 judge vs human + repeatability (part3/)
    python code/show_hw10_evidence.py traces      # 4.2 hit / miss / failed journeys (raw/trace_examples.json)
    python code/show_hw10_evidence.py latency     # 4.3 50-miss table (raw/latency_summary.json)
"""
import csv
import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1] / "reports/hw10"
HEADER = "Xu Wang | DATA 260 HW10 | PREFIX s9275 | reprint of saved evidence"


def load(p):
    return json.loads((R / p).read_text())


def evaluator(trace_id="0aaa45c3"):
    print(f"(saved evaluator log, reports/hw10/raw/agent_events.jsonl, trace {trace_id})\n")
    for line in (R / "raw/agent_events.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e["agent"] == "evaluator" and (e.get("cid", "").startswith(trace_id) or e["stage"] == "READY"):
            print(f"{e['ts'][11:23]} [{e['agent']:<8}] {e['stage']:<10} {e['text']}")
    r = next(json.loads(x) for x in (R / "raw/eval_results.jsonl").read_text().splitlines()
             if json.loads(x)["trace_id"].startswith(trace_id))
    print(f"\nquestion: {r['question']}")
    for k in ("plan_quality", "writer_helpfulness", "final_helpfulness"):
        print(f"  {k:<20} {r[k]['score']}  {r[k]['reason'][:110]}")
    print(f"  final_vs_draft       {r['final_vs_draft']}")
    print(f"  sources              {r['sources']}")


def judge():
    v = load("part3/judge_validation.json")
    print("(saved run, reports/hw10/part3/judge_runs.csv + judge_validation.json)\n")
    print(f"{'case':<5} {'kind':<11} {'human':>5} {'run1':>5} {'run2':>5} {'run3':>5}")
    for r in csv.DictReader((R / "part3/judge_runs.csv").open()):
        print(f"{r['case_id']:<5} {r['kind']:<11} {r['human_label'].strip():>5} {r['run1']:>5} "
              f"{r['run2']:>5} {r['run3']:>5}")
    print(f"\nlabels frozen in: {v['labels_commit']}\njudge: {v['judge']}")
    print(json.dumps({"vs_human (run1)": v["vs_human"]["run1"], "repeatability": v["repeatability"]}, indent=2))


def traces():
    ex = load("raw/trace_examples.json")
    print("(saved run, reports/hw10/raw/trace_examples.json)")
    for name in ("hit", "miss", "failed"):
        spans = ex[name]["spans"]
        order = {"gateway": 0, "evaluation": 2}
        spans = sorted(spans, key=lambda s: (order.get(s["stage"], 1), s["start_ts"]))
        print(f"\n== {name.upper()}  trace_id={ex[name]['trace_id']}")
        for s in spans:
            extra = s.get("hop") or s.get("cache") or s.get("review_status") or ""
            err = f"  ERROR: {s['error']}" if s.get("error") else ""
            print(f"  {s['start_ts'][11:]} -> {s['end_ts'][11:]}  {s['stage']:13s} {extra:8s} "
                  f"{s['duration_ms']:9.1f} ms  {s['status']}{err}")


def latency():
    s = load("raw/latency_summary.json")
    print("(saved run, reports/hw10/raw/latency_summary.json)\n")
    print(f"cache_lookup spans {s['cache_lookup_spans']}/{s['requests_planned']}, misses "
          f"{s['cache_lookup_misses']} -> all confirmed misses: {s['all_confirmed_misses']};  "
          f"complete ok: {s['complete_ok_misses']}")
    print(f"{'stage':18s} {'n':>3s} {'p50 ms':>10s} {'p95 ms':>10s} {'% of e2e':>9s}")
    for r in s["table"]:
        share = "" if r["pct_of_cache_miss_e2e"] is None else f"{r['pct_of_cache_miss_e2e']:.1f}"
        print(f"{r['stage']:18s} {r['n']:3d} {r['p50_ms']:10.1f} {r['p95_ms']:10.1f} {share:>9s}")
    print("queue wait by hop:", s["queue_wait_by_hop"])


if __name__ == "__main__":
    cmds = {"evaluator": evaluator, "judge": judge, "traces": traces, "latency": latency}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    print(HEADER)
    cmds[sys.argv[1]](*sys.argv[2:])
