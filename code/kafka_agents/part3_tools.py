"""
DATA 260 - HW8 Part 3: send the failure-test messages and check the results.

    python part3_tools.py replay           duplicate delivery: one task sent twice, same correlation_id
    python part3_tools.py slow             consumer death: one task for a Writer started with SLOW_SECONDS
    python part3_tools.py check <cid>      how many drafts in s9275_drafts carry this correlation_id
    python part3_tools.py poison           a task with no "question", then a normal task behind it
    python part3_tools.py dlq              print what is in s9275_dead_letter
    python part3_tools.py order nokey      ordering: 20 related tasks spread over both partitions
    python part3_tools.py order keyed      ordering: same 20 tasks, key = recall_notice_id
    python part3_tools.py analyze <run>    per-recall partitions and order violations for one run

The Writer(s) must be running. Results go to reports/hw08/raw/.
"""

from __future__ import annotations

import csv
import json
import random
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime

from confluent_kafka import Consumer

from common import (BOOTSTRAP, DEAD_LETTER, DRAFTS, ROOT, TASKS, VERIFY_SEED, log,
                    make_producer)

AGENT = "part3"
RAW = ROOT / "reports/hw08/raw"
STEPS = ["notice received", "lots verified", "shelves cleared", "customers notified",
         "recall closed"]

QUESTION = "What should a grocery store do with recalled peanut butter that may contain milk?"
PLAN = ["Pull the affected lots from shelves and back stock.",
        "Tell customers who bought it how to return it.",
        "Record the removed units and follow the firm's instructions."]


def task(cid: str, **extra) -> dict:
    return {"correlation_id": cid, "question": QUESTION, "plan": PLAN, **extra}


def produce(topic: str, message: dict, key: str | None = None, partition: int | None = None):
    producer = make_producer()
    kwargs = {"key": key, "value": json.dumps(message)}
    if partition is not None:
        kwargs["partition"] = partition
    producer.produce(topic, **kwargs)
    producer.flush(10)


def read_all(topic: str, timeout_s: float = 5.0) -> list:
    """Every message currently in a topic (fresh group, from the beginning)."""
    consumer = Consumer({"bootstrap.servers": BOOTSTRAP,
                         "group.id": f"s9275_check_{uuid.uuid4().hex[:8]}",
                         "auto.offset.reset": "earliest", "enable.auto.commit": False})
    consumer.subscribe([topic])
    out, idle_since = [], time.time()
    while time.time() - idle_since < timeout_s:
        msg = consumer.poll(0.5)
        if msg is None or msg.error():
            continue
        idle_since = time.time()
        out.append(msg)
    consumer.close()
    return out


def count_drafts(cid: str) -> int:
    return sum(1 for m in read_all(DRAFTS) if json.loads(m.value()).get("correlation_id") == cid)


def cmd_replay() -> None:
    cid = f"dup-{uuid.uuid4().hex[:8]}"
    message = task(cid)
    for n in (1, 2):
        produce(TASKS, message, key=cid)      # same key -> same partition, same Writer
        log(AGENT, "REPLAY", f"send #{n} cid={cid} -> {TASKS}", cid=cid)
    print(f"\nwait until the Writer is idle, then:  python part3_tools.py check {cid}")


def cmd_slow() -> None:
    cid = f"kill-{uuid.uuid4().hex[:8]}"
    produce(TASKS, task(cid), key=cid)
    log(AGENT, "SENT", f"cid={cid} -> {TASKS} (kill the Writer during its WORKING line)", cid=cid)
    print(f"\nafter the restart:  python part3_tools.py check {cid}")


def cmd_check(cid: str) -> None:
    n = count_drafts(cid)
    log(AGENT, "CHECK", f"cid={cid} drafts in {DRAFTS}: {n}", cid=cid, drafts=n)


def cmd_poison() -> None:
    bad = f"poison-{uuid.uuid4().hex[:8]}"
    good = f"after-poison-{uuid.uuid4().hex[:8]}"
    # Same key, so both land in one partition and the good one queues behind the bad one.
    produce(TASKS, {"correlation_id": bad, "plan": PLAN}, key="poison-test")
    log(AGENT, "SENT", f"POISON cid={bad} (no 'question' field) -> {TASKS}", cid=bad)
    produce(TASKS, task(good), key="poison-test")
    log(AGENT, "SENT", f"normal cid={good} queued behind it -> {TASKS}", cid=good)
    print(f"\nthen:  python part3_tools.py dlq   and   python part3_tools.py check {good}")


def cmd_dlq() -> None:
    records = [json.loads(m.value()) for m in read_all(DEAD_LETTER)]
    print(f"{len(records)} message(s) in {DEAD_LETTER}")
    for r in records:
        print(json.dumps(r, indent=2))
    (RAW / "dead_letter.json").write_text(json.dumps(records, indent=2), encoding="utf-8")


def build_order_messages() -> list:
    """20 related tasks from VERIFY_SEED: 4 recalls x 5 steps, interleaved, steps in order."""
    rng = random.Random(VERIFY_SEED)
    recalls = [f"RN-{rng.randrange(16**6):06x}" for _ in range(4)]
    next_step = {r: 0 for r in recalls}
    messages = []
    while len(messages) < 20:
        r = rng.choice([x for x in recalls if next_step[x] < len(STEPS)])
        seq = next_step[r] + 1
        next_step[r] = seq
        messages.append({"recall_notice_id": r, "seq": seq, "step": STEPS[seq - 1]})
    return messages


def cmd_order(run: str) -> None:
    if run not in ("nokey", "keyed"):
        raise SystemExit("run must be nokey or keyed")
    processed = RAW / f"ordering_{run}.csv"
    if processed.exists():
        processed.unlink()                    # fresh result file for this run
    stamp = datetime.now().strftime("%H%M%S")
    producer = make_producer()
    sent_rows = []
    for i, m in enumerate(build_order_messages()):
        cid = f"ord-{run}-{i:02d}-{stamp}"
        message = task(cid, order_test=True, run=run, **m)
        if run == "keyed":
            # Fix: key by the related entity -> one partition per recall -> order kept.
            producer.produce(TASKS, key=m["recall_notice_id"], value=json.dumps(message))
        else:
            # Before: no key; spread round-robin over the 2 partitions.
            producer.produce(TASKS, value=json.dumps(message), partition=i % 2)
        sent_rows.append([i, cid, m["recall_notice_id"], m["seq"]])
    producer.flush(10)
    with (RAW / f"ordering_{run}_sent.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["send_index", "correlation_id", "recall_notice_id", "seq"])
        w.writerows(sent_rows)
    log(AGENT, "ORDER", f"run={run} sent 20 tasks (VERIFY_SEED={VERIFY_SEED}) -> {TASKS}")
    print(f"\nwhen both Writers are idle:  python part3_tools.py analyze {run}")


def cmd_analyze(run: str) -> None:
    rows = list(csv.DictReader((RAW / f"ordering_{run}.csv").open()))
    rows.sort(key=lambda r: r["processed_at"])
    by_recall = defaultdict(list)
    for r in rows:
        by_recall[r["recall_notice_id"]].append(r)
    summary = {"run": run, "verify_seed": VERIFY_SEED, "processed": len(rows), "recalls": {}}
    print(f"run={run}: {len(rows)} of 20 processed")
    print(f"{'recall':<10} {'partitions':<11} {'writers':<8} {'seq in processing order':<26} violations")
    total = 0
    for recall, items in sorted(by_recall.items()):
        seqs = [int(r["seq"]) for r in items]
        violations = sum(1 for i in range(1, len(seqs)) if seqs[i] < max(seqs[:i]))
        total += violations
        parts = sorted({r["partition"] for r in items})
        writers = sorted({r["writer"] for r in items})
        summary["recalls"][recall] = {"partitions": parts, "writers": writers,
                                      "seq_order": seqs, "violations": violations}
        print(f"{recall:<10} {','.join(parts):<11} {','.join(writers):<8} "
              f"{str(seqs):<26} {violations}")
    summary["total_violations"] = total
    print(f"total order violations: {total}")
    (RAW / f"ordering_{run}_summary.json").write_text(json.dumps(summary, indent=2))


def main() -> None:
    print("=== HW8 Part 3 - Xu Wang (SID4 9275, PREFIX s9275) ===", flush=True)
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    cmd, rest = args[0], args[1:]
    if cmd == "replay":
        cmd_replay()
    elif cmd == "slow":
        cmd_slow()
    elif cmd == "check" and rest:
        cmd_check(rest[0])
    elif cmd == "poison":
        cmd_poison()
    elif cmd == "dlq":
        cmd_dlq()
    elif cmd == "order" and rest:
        cmd_order(rest[0])
    elif cmd == "analyze" and rest:
        cmd_analyze(rest[0])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
