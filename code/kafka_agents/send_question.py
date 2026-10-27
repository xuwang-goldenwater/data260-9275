"""
DATA 260 - HW8 Part 2: send one question into the pipeline and read the result.

  1. create a correlation_id once
  2. send {"correlation_id", "question"} to s9275_inbox
  3. wait on s9275_final for the message with that correlation_id
  4. print the journey (every agent's log lines for this id, in order) and
     the final JSON, and save the final JSON to reports/hw08/raw/

Planner, Writer and Reviewer must already be running in their own terminals.

Run:  python code/kafka_agents/send_question.py
      python code/kafka_agents/send_question.py "your own question"
"""

from __future__ import annotations

import json
import sys
import time
import uuid

from confluent_kafka import Consumer

from common import BOOTSTRAP, EVENTS_FILE, FINAL, INBOX, ROOT, log, make_producer, send

AGENT = "client"
DEFAULT_QUESTION = ("What should a grocery store do when it receives a recall notice "
                    "for peanut butter that may contain undeclared milk?")
TIMEOUT_S = 180   # three model calls on an 8 GB M1


def journey(cid: str) -> list[dict]:
    """Every logged event for this correlation_id, oldest first."""
    if not EVENTS_FILE.exists():
        return []
    events = []
    for line in EVENTS_FILE.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("cid") == cid:
            events.append(event)
    return sorted(events, key=lambda e: e["ts"])


def main() -> None:
    question = " ".join(sys.argv[1:]) or DEFAULT_QUESTION
    print("=== HW8 Part 2 pipeline - Xu Wang (SID4 9275, PREFIX s9275) ===", flush=True)

    # Join s9275_final before sending, so the answer cannot arrive unseen.
    consumer = Consumer({"bootstrap.servers": BOOTSTRAP,
                         "group.id": f"s9275_client_{uuid.uuid4().hex[:8]}",
                         "auto.offset.reset": "latest", "enable.auto.commit": True})
    consumer.subscribe([FINAL])
    while not consumer.assignment():
        consumer.poll(0.2)

    cid = str(uuid.uuid4())
    send(make_producer(), INBOX, {"correlation_id": cid, "question": question})
    log(AGENT, "SENT", f"cid={cid} -> {INBOX} question={question!r}", cid=cid)

    final = None
    deadline = time.time() + TIMEOUT_S
    while time.time() < deadline:
        msg = consumer.poll(1.0)
        if msg is None or msg.error():
            continue
        candidate = json.loads(msg.value())
        if candidate.get("correlation_id") == cid:
            final = candidate
            break
    consumer.close()
    if final is None:
        raise SystemExit(f"no result for {cid} after {TIMEOUT_S}s - are all three agents running?")
    log(AGENT, "FINAL", f"cid={cid} from {FINAL} status={final['status']}", cid=cid)

    print("\n--- Journey (all agents, ordered by time) ---")
    for e in journey(cid):
        print(f"{e['ts'][11:]} [{e['agent']:<9}] {e['stage']:<10} {e['text'][:110]}")

    print(f"\n--- Final message from {FINAL} ---")
    print(json.dumps(final, indent=2))
    print(f"\ncorrelation_id preserved end to end: {final['correlation_id'] == cid}")

    out = ROOT / "reports/hw08/raw/part2_final.json"
    out.write_text(json.dumps(final, indent=2), encoding="utf-8")
    print(f"saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
