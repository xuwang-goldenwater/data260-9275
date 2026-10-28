"""
DATA 260 - HW8 Part 2 + Part 3: Writer agent.

Part 2: reads a plan from s9275_tasks, asks the model to write the answer
following that plan, and sends {..., "draft": "..."} to s9275_drafts.

s9275_tasks has 2 partitions, so up to two Writers can share the work: start
a second one with the same group and Kafka splits the partitions between them.
WRITER_ID only labels the log lines so the two instances can be told apart.

Part 3: each fix has its own switch, all on by default. A "before fix" run
turns off exactly one of them, so each failure test changes one thing:

    FIX_IDEMPOTENCY=0    duplicate delivery: no check for an already-processed id
    FIX_MANUAL_COMMIT=0  consumer death: Kafka auto-commits every second
    FIX_DLQ=0            poison message: no retries, an exception kills the Writer

Test helpers (only used by part3_tools.py):
    SLOW_SECONDS=20      wait this long before writing, so the Writer can be killed mid-work
    "order_test" field   fake 0.1-0.6 s of work instead of a model call and log
                         the processing order to reports/hw08/raw/ordering_<run>.csv

Run:  python code/kafka_agents/writer.py
      WRITER_ID=w2 python code/kafka_agents/writer.py     (second instance)
      FIX_DLQ=0 python code/kafka_agents/writer.py         (poison test, before fix)
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import time
from datetime import datetime

from common import (DRAFTS, ROOT, TASKS, add_trace, llm, log, make_consumer,
                    make_producer, send)
from reliability import MAX_ATTEMPTS, ProcessedStore, run_with_retries, to_dead_letter

WRITER_ID = os.getenv("WRITER_ID", "w1")
AGENT = f"writer-{WRITER_ID}"
GROUP_ID = "s9275_writer"

FIX_IDEMPOTENCY = os.getenv("FIX_IDEMPOTENCY", "1") == "1"
FIX_MANUAL_COMMIT = os.getenv("FIX_MANUAL_COMMIT", "1") == "1"
FIX_DLQ = os.getenv("FIX_DLQ", "1") == "1"
SLOW_SECONDS = float(os.getenv("SLOW_SECONDS", "0"))

SYSTEM = (
    "You are the Writer in a grocery recall-notice help desk. "
    "Write the answer to the user's question as one paragraph of 3 to 5 full "
    "sentences, under 120 words. Use the plan only as an outline: for each step "
    "say concretely what the store should do and why. Do not copy the plan "
    "lines, do not use a numbered list, no headings."
)


def write_draft(message: dict) -> str:
    """The real work. A message without 'question' raises KeyError (the poison case)."""
    if SLOW_SECONDS:
        log(AGENT, "WORKING", f"cid={message.get('correlation_id')} "
                              f"pid={os.getpid()} sleeping {SLOW_SECONDS:.0f}s - kill window")
        time.sleep(SLOW_SECONDS)
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(message.get("plan", []), 1))
    prompt = f"Question: {message['question']}\n\nPlan:\n{steps}"
    return llm(SYSTEM, prompt, max_tokens=300)


def order_test_work(message: dict, msg) -> str:
    """Ordering test: fixed fake work time per message, then one CSV row."""
    work_key = f"{message['recall_notice_id']}-{message['seq']}"
    digest = hashlib.sha256(work_key.encode()).digest()
    time.sleep(0.1 + (digest[0] / 255) * 0.5)          # 0.1-0.6 s, same every run
    path = ROOT / f"reports/hw08/raw/ordering_{message['run']}.csv"
    new_file = not path.exists()
    with path.open("a", newline="") as fh:
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(["processed_at", "writer", "partition", "offset",
                             "recall_notice_id", "seq", "correlation_id"])
        writer.writerow([datetime.now().isoformat(timespec="milliseconds"), WRITER_ID,
                         msg.partition(), msg.offset(), message["recall_notice_id"],
                         message["seq"], message["correlation_id"]])
    return f"order-test {message['recall_notice_id']} step {message['seq']}"


def main() -> None:
    consumer = make_consumer(GROUP_ID, [TASKS], auto_commit=not FIX_MANUAL_COMMIT)
    producer = make_producer()
    store = ProcessedStore("writer")

    def commit(msg) -> None:
        if FIX_MANUAL_COMMIT:
            consumer.commit(message=msg, asynchronous=False)
            log(AGENT, "COMMITTED", f"partition={msg.partition()} offset={msg.offset() + 1}")

    log(AGENT, "READY", f"listening on {TASKS} (group {GROUP_ID}) pid={os.getpid()} "
                        f"fixes: idempotency={FIX_IDEMPOTENCY} manual_commit={FIX_MANUAL_COMMIT} "
                        f"dlq={FIX_DLQ}")
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            raw = msg.value()
            message = json.loads(raw)
            cid = message.get("correlation_id")
            log(AGENT, "RECEIVED", f"cid={cid} from {TASKS} partition={msg.partition()} "
                                   f"offset={msg.offset()}", cid=cid, partition=msg.partition(),
                offset=msg.offset())

            # Duplicate delivery fix: an id that already produced a draft is skipped.
            if FIX_IDEMPOTENCY and store.seen(cid):
                log(AGENT, "DUPLICATE", f"cid={cid} already processed - skipped, no new draft",
                    cid=cid)
                commit(msg)
                continue

            work = (lambda m: order_test_work(m, msg)) if message.get("order_test") else write_draft

            if FIX_DLQ:
                ok, result, attempts = run_with_retries(
                    work, message,
                    on_retry=lambda n, exc: log(AGENT, "RETRY", f"cid={cid} attempt {n}/"
                                                f"{MAX_ATTEMPTS} failed: {type(exc).__name__}: {exc}",
                                                cid=cid))
                if not ok:
                    to_dead_letter(producer, raw, msg, AGENT, result, attempts)
                    log(AGENT, "DEAD_LTR", f"cid={cid} -> s9275_dead_letter after {attempts} "
                                           f"attempts ({result})", cid=cid)
                    commit(msg)
                    continue
                draft = result
            else:
                draft = work(message)        # before fix: an exception ends the process

            if message.get("order_test"):
                log(AGENT, "ORDERED", f"cid={cid} {draft}", cid=cid,
                    recall_notice_id=message["recall_notice_id"], seq=message["seq"])
            else:
                log(AGENT, "WROTE", f"cid={cid} draft={len(draft.split())} words", cid=cid)
                out = {**message, "draft": draft, "trace": add_trace(message, AGENT)}
                send(producer, DRAFTS, out)
                log(AGENT, "SENT", f"cid={cid} -> {DRAFTS}", cid=cid)

            store.mark(cid)      # after the output is in Kafka
            commit(msg)          # last: only now is this message done
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
