"""
DATA 260 - HW8 Part 2: Reviewer agent.

Reads a draft from s9275_drafts, decides whether it answers the question,
and sends the final message to s9275_final:

    {"correlation_id", "status": "approved" | "rejected", "answer", "review", ...}

Two layers of review:
  1. deterministic checks (draft not empty, not over 150 words, not just a
     copy of the plan) - these alone
     can reject, so a broken draft never gets approved by a lenient model
  2. the model's verdict as JSON {"approved": bool, "reason": str}; if the
     model returns something unparseable, the deterministic result stands

HW9: when the message carries "facts", the Reviewer also gets them (prompt +
a rule that rejects numbers not found in the facts). Without "facts" nothing
changes from HW8.

Run:  python code/kafka_agents/reviewer.py
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from common import (DRAFTS, FINAL, add_trace, llm, log, make_consumer, make_producer,
                    record_queue_wait, send, span)

AGENT = "reviewer"
GROUP_ID = "s9275_reviewer"
MAX_WORDS = 150

SYSTEM = (
    "You are the Reviewer in a grocery recall-notice help desk. Decide whether "
    "the draft answers the question and follows the plan. Reply with JSON only: "
    '{"approved": true or false, "reason": "one short sentence"}'
)


COPY_THRESHOLD = 0.8   # draft this similar to the plan text = plan copied, not answered


def _norm(text: str) -> str:
    """Lowercase, drop list numbers and punctuation, squeeze spaces."""
    text = re.sub(r"^\s*\d+[.)]\s*", "", text, flags=re.M)
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def rule_check(draft: str, plan: list[str], facts: dict | None = None) -> str | None:
    """Return a rejection reason, or None if the draft passes the hard rules."""
    if not draft.strip():
        return "draft is empty"
    if len(draft.split()) > MAX_WORDS:
        return f"draft is longer than {MAX_WORDS} words"
    similarity = SequenceMatcher(None, _norm(draft), _norm(" ".join(plan))).ratio()
    if similarity >= COPY_THRESHOLD:
        return f"draft repeats the plan instead of answering (similarity {similarity:.2f})"
    if facts:                                   # HW9: answer must not invent numbers
        allowed = set(re.findall(r"\d+", " ".join(str(v) for v in facts.values())))
        invented = [n for n in re.findall(r"\d+", draft.replace(",", "")) if n not in allowed]
        if invented:
            return f"draft has numbers that are not in the database facts: {invented}"
    return None


def facts_text(facts: dict | None) -> str:
    """HW9: the same database facts the Writer saw, so the Reviewer can check against them."""
    if not facts:
        return ""
    if facts.get("not_found"):
        return (f"\n\nDatabase facts: recall {facts['not_found']} does not exist. "
                "Approve only if the draft says it was not found and invents nothing.")
    lines = "\n".join(f"- {k}: {v}" for k, v in facts.items())
    return ("\n\nDatabase facts (ground truth):\n" + lines +
            "\nApprove if the draft states the values the question asks about and they "
            "match these facts.")


def review(message: dict) -> tuple[str, str]:
    """Return (status, reason)."""
    draft = message.get("draft", "")
    problem = rule_check(draft, message.get("plan", []), message.get("facts"))
    if problem:
        return "rejected", f"rule check: {problem}"

    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(message.get("plan", []), 1))
    raw = llm(SYSTEM, f"Question: {message['question']}\n\nPlan:\n{steps}\n\nDraft:\n{draft}"
              + facts_text(message.get("facts")),
              max_tokens=120, json_mode=True)
    try:
        verdict = json.loads(raw)
        approved = verdict.get("approved") is True
        reason = str(verdict.get("reason", "")).strip() or "no reason given"
    except (ValueError, AttributeError):
        return "approved", "rule checks passed; model verdict unparseable"
    return ("approved" if approved else "rejected"), reason


def main() -> None:
    consumer = make_consumer(GROUP_ID, [DRAFTS])
    producer = make_producer()
    log(AGENT, "READY", f"listening on {DRAFTS} (group {GROUP_ID})")
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            message = json.loads(msg.value())
            cid = message.get("correlation_id")
            log(AGENT, "RECEIVED", f"cid={cid} from {DRAFTS} offset={msg.offset()}", cid=cid)
            record_queue_wait(cid, "drafts", msg)           # HW10: hop 3, Writer -> Reviewer

            with span(cid, "reviewer") as s:                # HW10: review + send
                status, reason = review(message)
                s["review_status"] = status                 # a rejection is an outcome, not an error
                log(AGENT, "REVIEWED", f"cid={cid} status={status} reason={reason!r}", cid=cid)

                out = {**message, "status": status, "answer": message.get("draft", ""),
                       "review": reason, "trace": add_trace(message, AGENT)}
                send(producer, FINAL, out)
            log(AGENT, "SENT", f"cid={cid} -> {FINAL}", cid=cid)
            consumer.commit(message=msg, asynchronous=False)
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
