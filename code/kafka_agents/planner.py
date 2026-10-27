"""
DATA 260 - HW8 Part 2: Planner agent.

Reads a question from s9275_inbox, asks the model for a short plan, and sends
{..., "plan": [...]} to s9275_tasks. It never calls the Writer; the Writer
picks the plan up from Kafka whenever it is ready.

Run:  python code/kafka_agents/planner.py
"""

from __future__ import annotations

import json
import re

from common import INBOX, TASKS, add_trace, llm, log, make_consumer, make_producer, send

AGENT = "planner"
GROUP_ID = "s9275_planner"

SYSTEM = (
    "You are the Planner in a grocery recall-notice help desk. "
    "Break the user's question into exactly 3 short steps that a writer should "
    "cover to answer it. Output only the 3 steps, one per line, numbered 1. 2. 3. "
    "Do not answer the question yourself."
)


def parse_steps(text: str) -> list[str]:
    """Keep numbered lines; fall back to non-empty lines. At most 3 steps."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    numbered = [re.sub(r"^\d+[.)]\s*", "", ln) for ln in lines if re.match(r"^\d+[.)]", ln)]
    steps = numbered or lines
    return steps[:3] or ["Answer the question directly."]


def main() -> None:
    consumer = make_consumer(GROUP_ID, [INBOX])
    producer = make_producer()
    log(AGENT, "READY", f"listening on {INBOX} (group {GROUP_ID})")
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            message = json.loads(msg.value())
            cid = message.get("correlation_id")
            log(AGENT, "RECEIVED", f"cid={cid} from {INBOX} offset={msg.offset()} "
                                   f"question={message.get('question')!r}", cid=cid)

            steps = parse_steps(llm(SYSTEM, message["question"], max_tokens=200))
            log(AGENT, "PLANNED", f"cid={cid} steps={steps}", cid=cid)

            out = {**message, "plan": steps, "trace": add_trace(message, AGENT)}
            send(producer, TASKS, out)
            log(AGENT, "SENT", f"cid={cid} -> {TASKS}", cid=cid)
            consumer.commit(message=msg, asynchronous=False)
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
