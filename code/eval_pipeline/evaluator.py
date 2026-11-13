"""
DATA 260 - HW10 Part 2: Evaluator agent for the Planner -> Writer -> Reviewer pipeline.

A separate Kafka consumer (group s9275_evaluator) on three topics:
    s9275_tasks  -> the Planner's plan       (plus question, facts)
    s9275_drafts -> the Writer's draft
    s9275_final  -> the Reviewer's status / final answer
It joins the three messages on correlation_id (= trace_id). When all three are
in, it scores them with the local judge (judge.py) inside an "evaluation" span:
    Plan Quality        question + plan
    Writer Helpfulness  question + draft  (+ database facts as context)
    Final Helpfulness   question + final  (+ database facts as context)
    Final-vs-Draft      final score - draft score, with an interpretation
Each result (scores, reasons, the original texts and the Kafka topic/partition/
offset/timestamp of every source message) is one line of
reports/hw10/raw/eval_results.jsonl (env HW10_EVAL_OUT).

Bounded, so it never hangs:
    - a correlation_id that is still missing a message after EVAL_JOIN_TIMEOUT_S
      (default 120 s) is written as status "incomplete" with an error span
    - each judge call has the judge.py timeout (JUDGE_TIMEOUT_S, 90 s); a failed
      call is recorded for that metric and the evaluation span gets status=error
    - a message that is not JSON or has no correlation_id is logged and skipped

Run (start it BEFORE sending questions; a new group starts at the latest offset):
    python code/eval_pipeline/evaluator.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code" / "kafka_agents"))
sys.path.insert(0, str(ROOT / "code" / "eval_pipeline"))

from common import DRAFTS, FINAL, TASKS, log, make_consumer, span, write_span  # noqa: E402
from judge import (JUDGE_MODEL, JUDGE_OPTIONS, JudgeError, helpfulness_metric,  # noqa: E402
                   plan_quality_metric, score)

AGENT = "evaluator"
GROUP_ID = "s9275_evaluator"
JOIN_TIMEOUT_S = float(os.getenv("EVAL_JOIN_TIMEOUT_S", "120"))
OUT_FILE = Path(os.getenv("HW10_EVAL_OUT", ROOT / "reports/hw10/raw/eval_results.jsonl"))
ROLE = {TASKS: "plan", DRAFTS: "draft", FINAL: "final"}


def source(msg) -> dict:
    """Where a message came from, so the evaluation can be reproduced from Kafka."""
    return {"topic": msg.topic(), "partition": msg.partition(), "offset": msg.offset(),
            "kafka_ts_ms": msg.timestamp()[1]}


def interpret(draft: int | None, final: int | None, same_text: bool, status: str) -> str:
    if draft is None or final is None:
        return "not comparable: a judge call failed"
    diff = final - draft
    if same_text:
        base = ("the Reviewer returned the Writer's draft unchanged (it approves or "
                "rejects, it does not rewrite), so no improvement is possible by design")
        if diff == 0:
            return base + "; the judge gave both the same score"
        return base + f"; the {diff:+d} difference comes from the judge itself, not the text"
    if diff > 0:
        return f"the final answer improved on the draft by {diff}"
    if diff < 0:
        return f"the final answer is worse than the draft by {-diff}"
    return "the final answer differs from the draft but scored the same"


def judge_one(metric, question, text, facts) -> dict:
    try:
        return score(metric, question, text, facts)
    except JudgeError as exc:
        return {"score": None, "reason": None, "error": str(exc)}


def evaluate(cid: str, parts: dict, plan_m, help_m) -> dict:
    tasks, drafts, final = parts["plan"]["message"], parts["draft"]["message"], parts["final"]["message"]
    question, facts = tasks.get("question", ""), tasks.get("facts")
    plan_text = "\n".join(f"{i}. {s}" for i, s in enumerate(tasks.get("plan", []), 1))
    draft_text, final_text = drafts.get("draft", ""), final.get("answer", "")

    with span(cid, "evaluation", judge=JUDGE_MODEL) as s:
        plan_r = judge_one(plan_m, question, plan_text, None)
        draft_r = judge_one(help_m, question, draft_text, facts)
        final_r = judge_one(help_m, question, final_text, facts)
        failed = [n for n, r in (("plan", plan_r), ("draft", draft_r), ("final", final_r))
                  if r["score"] is None]
        d, f = draft_r["score"], final_r["score"]
        same = draft_text.strip() == final_text.strip()
        s.update(plan_quality=plan_r["score"], writer_helpfulness=d, final_helpfulness=f)
        if failed:
            s["status"], s["error"] = "error", f"judge failed for {failed}: " + \
                "; ".join(r["error"] for r in (plan_r, draft_r, final_r) if r.get("error"))

    return {
        "trace_id": cid, "status": "evaluated" if not failed else "judge_error",
        "question": question, "facts": facts,
        "plan": tasks.get("plan", []), "draft": draft_text, "final_answer": final_text,
        "review_status": final.get("status"), "review_reason": final.get("review"),
        "plan_quality": plan_r,
        "writer_helpfulness": draft_r,
        "final_helpfulness": final_r,
        "final_vs_draft": {"draft_score": d, "final_score": f,
                           "difference": None if d is None or f is None else f - d,
                           "final_identical_to_draft": same,
                           "interpretation": interpret(d, f, same, final.get("status", ""))},
        "sources": {role: p["source"] for role, p in parts.items()},
        "judge": {"model": JUDGE_MODEL, "options": JUDGE_OPTIONS, "scale": "1-5"},
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
    }


def save(record: dict) -> None:
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUT_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def expire(pending: dict, done: set) -> None:
    """Join timeout: give up on correlation_ids that are still missing a message."""
    now = time.time()
    for cid in [c for c, p in pending.items() if now - p["first_seen"] > JOIN_TIMEOUT_S]:
        p = pending.pop(cid)
        missing = [r for r in ("plan", "draft", "final") if r not in p["parts"]]
        write_span(cid, "evaluation", p["first_seen"], now, "error",
                   f"incomplete: no {', '.join(missing)} within {JOIN_TIMEOUT_S:.0f}s")
        save({"trace_id": cid, "status": "incomplete", "missing": missing,
              "sources": {r: v["source"] for r, v in p["parts"].items()},
              "evaluated_at": datetime.now().isoformat(timespec="seconds")})
        log(AGENT, "INCOMPLETE", f"cid={cid} missing={missing}", cid=cid)
        done.add(cid)


def main() -> None:
    consumer = make_consumer(GROUP_ID, [TASKS, DRAFTS, FINAL], offset_reset="latest",
                             auto_commit=True)
    joined_by = time.time() + 30              # join first, so no new message is missed
    while not consumer.assignment():
        if time.time() > joined_by:
            raise SystemExit("evaluator: no partitions assigned in 30 s - is Kafka up?")
        consumer.poll(0.5)
    plan_m, help_m = plan_quality_metric(), helpfulness_metric()
    log(AGENT, "READY", f"listening on {TASKS}, {DRAFTS}, {FINAL} (group {GROUP_ID}) "
                        f"judge={JUDGE_MODEL} join_timeout={JOIN_TIMEOUT_S:.0f}s -> {OUT_FILE}")
    pending: dict[str, dict] = {}
    done: set[str] = set()
    try:
        while True:
            expire(pending, done)
            msg = consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            try:
                message = json.loads(msg.value())
                cid = message["correlation_id"]
            except (ValueError, TypeError, KeyError) as exc:
                log(AGENT, "SKIPPED", f"malformed message on {msg.topic()} offset={msg.offset()}: "
                                      f"{type(exc).__name__}")
                continue
            if cid in done or message.get("order_test"):
                continue
            entry = pending.setdefault(cid, {"first_seen": time.time(), "parts": {}})
            entry["parts"][ROLE[msg.topic()]] = {"message": message, "source": source(msg)}
            log(AGENT, "RECEIVED", f"cid={cid} {ROLE[msg.topic()]} "
                                   f"({len(entry['parts'])}/3)", cid=cid)
            if len(entry["parts"]) < 3:
                continue

            pending.pop(cid)
            log(AGENT, "JUDGING", f"cid={cid} 3 judge calls ...", cid=cid)
            record = evaluate(cid, entry["parts"], plan_m, help_m)
            save(record)
            done.add(cid)
            v = record["final_vs_draft"]
            log(AGENT, "SCORED", f"cid={cid} plan={record['plan_quality']['score']} "
                                 f"draft={v['draft_score']} final={v['final_score']} "
                                 f"diff={v['difference']} status={record['status']}", cid=cid)
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
