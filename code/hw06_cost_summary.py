"""HW6 Part 3: turn the raw run data into the METRICS tables and the cost estimate.

Reads   reports/hw06/raw/part3_turns.jsonl         (hw06_memory_cost.py)
        reports/hw06/raw/part3_probe_scores.csv    (score column filled by hand)
Writes  reports/hw06/raw/part3_summary.json
Prints  markdown tables to paste into METRICS.md

For each setting only the LATEST complete run (35 turns) is used, so a crashed or
repeated run does not mix into the numbers.

Cost model (assignment): $1 per million input tokens, $5 per million output tokens,
10,000 conversations of 30 turns. Two views are reported:
  chat only        the 30 chat calls per conversation
  chat + upkeep    plus the memory-maintenance calls each turn caused
                   (fact extraction every turn, summaries every 4th user message)
Probe turns are excluded from cost: they are the measurement, not the conversation.

Run:  make memory-summary
"""
import csv
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "reports" / "hw06" / "raw"
ORDER = ["N4", "N12", "N30", "N30_comp"]
LABEL = {"N4": "SHORT_TERM_N=4", "N12": "SHORT_TERM_N=12", "N30": "SHORT_TERM_N=30",
         "N30_comp": "Compression: N=30, assistant replies cut to 1st sentence"}
PRICE_IN, PRICE_OUT = 1.0 / 1e6, 5.0 / 1e6
CONVERSATIONS, TURNS_PER_CONV = 10_000, 30


def latest_runs():
    rows = [json.loads(line) for line in open(RAW / "part3_turns.jsonl", encoding="utf-8")]
    by_run = defaultdict(list)
    for r in rows:
        by_run[r["run_id"]].append(r)
    chosen = {}
    for run_id, turns in by_run.items():
        if len(turns) != 35:
            continue
        setting = turns[0]["setting"]
        if setting not in chosen or run_id > chosen[setting][0]:
            chosen[setting] = (run_id, sorted(turns, key=lambda t: t["turn"]))
    return chosen


def scores(run_ids):
    out = defaultdict(dict)
    path = RAW / "part3_probe_scores.csv"
    for r in csv.DictReader(open(path, encoding="utf-8")):
        if r["run_id"] in run_ids and r["score"].strip():
            out[r["setting"]][r["probe_id"]] = int(r["score"])
    return out


def main() -> None:
    runs = latest_runs()
    missing = [s for s in ORDER if s not in runs]
    if missing:
        print(f"[warn] no complete run for {missing}")
    sc = scores({run_id for run_id, _ in runs.values()})
    summary = {}
    for s in ORDER:
        if s not in runs:
            continue
        run_id, turns = runs[s]
        conv = [t for t in turns if t["kind"] == "conversation"]
        probe_scores = sc.get(s, {})
        mean = lambda key, rows=conv: st.mean(t[key] for t in rows)
        upkeep_in = sum(t["extract_input_tokens"] + t["summary_input_tokens"] for t in conv)
        upkeep_out = sum(t["extract_output_tokens"] + t["summary_output_tokens"] for t in conv)
        chat_in = sum(t["prompt_tokens"] for t in conv)
        chat_out = sum(t["completion_tokens"] for t in conv)
        cost_chat = (chat_in * PRICE_IN + chat_out * PRICE_OUT) * CONVERSATIONS
        cost_all = ((chat_in + upkeep_in) * PRICE_IN + (chat_out + upkeep_out) * PRICE_OUT) * CONVERSATIONS
        summary[s] = {
            "run_id": run_id, "label": LABEL[s],
            "mean_prompt_tokens": round(mean("prompt_tokens"), 1),
            "mean_completion_tokens": round(mean("completion_tokens"), 1),
            "mean_chat_latency_ms": round(mean("chat_latency_ms"), 1),
            "mean_total_latency_ms": round(mean("total_latency_ms"), 1),
            "mean_tokens_by_section": {k: round(mean(f"tokens_{k}"), 1) for k in
                                       ("system_primer", "long_term_summary", "short_term_window",
                                        "current_message", "episodic_facts")},
            "mean_template_overhead": round(mean("template_overhead"), 1),
            "probe_scores": probe_scores,
            "mean_probe_score": round(st.mean(probe_scores.values()), 2) if len(probe_scores) == 5 else None,
            "per_conversation_tokens": {"chat_in": chat_in, "chat_out": chat_out,
                                        "upkeep_in": upkeep_in, "upkeep_out": upkeep_out},
            "cost_10k_conversations_usd": {"chat_only": round(cost_chat, 2),
                                           "chat_plus_upkeep": round(cost_all, 2)},
        }
    json.dump(summary, open(RAW / "part3_summary.json", "w"), indent=2)

    print("Xu Wang | DATA 260 HW6 Part 3 | memory cost summary\n")
    print("| Setting | Mean prompt tokens/turn | Mean latency (ms) | Probe quality (1-5) |")
    print("|---|---|---|---|")
    for s, v in summary.items():
        q = v["mean_probe_score"] if v["mean_probe_score"] is not None else "(score CSV)"
        print(f"| {v['label']} | {v['mean_prompt_tokens']} | {v['mean_total_latency_ms']:.0f} | {q} |")

    print("\nMean tokens per prompt section (conversation turns):\n")
    print("| Setting | primer | long-term summary | short-term window | current msg | episodic facts | template |")
    print("|---|---|---|---|---|---|---|")
    for s, v in summary.items():
        t = v["mean_tokens_by_section"]
        print(f"| {s} | {t['system_primer']} | {t['long_term_summary']} | {t['short_term_window']} | "
              f"{t['current_message']} | {t['episodic_facts']} | {v['mean_template_overhead']} |")

    if "N30" in summary and "N30_comp" in summary:
        a, b = summary["N30"], summary["N30_comp"]
        saved = 1 - b["mean_prompt_tokens"] / a["mean_prompt_tokens"]
        print(f"\nCompression vs N=30: prompt tokens {a['mean_prompt_tokens']} -> "
              f"{b['mean_prompt_tokens']} ({saved:.1%} saved); probe score "
              f"{a['mean_probe_score']} -> {b['mean_probe_score']}")

    print(f"\nCost of {CONVERSATIONS:,} conversations x {TURNS_PER_CONV} turns "
          "($1/M input, $5/M output):\n")
    print("| Setting | chat in/out tokens per conv | chat only (USD) | + memory upkeep (USD) |")
    print("|---|---|---|---|")
    for s, v in summary.items():
        p = v["per_conversation_tokens"]
        c = v["cost_10k_conversations_usd"]
        print(f"| {s} | {p['chat_in']:,} / {p['chat_out']:,} | {c['chat_only']:,.2f} | "
              f"{c['chat_plus_upkeep']:,.2f} |")
    print(f"\nwritten {(RAW / 'part3_summary.json').relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
