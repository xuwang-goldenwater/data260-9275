"""
DATA 260 - HW8 Part 1 IV: end-to-end request/response demo over Kafka.

This script is the Kafka client. It talks to Kafka directly (localhost:9092),
not through the FastAPI wrapper, and runs the ten steps from the assignment:

  CREATE_RECALL_NOTICE  -> wait for response -> take recall_notice_id
  GET_RECALL_NOTICE     -> wait for response -> show the record

Each request gets its own correlation_id, created once before sending and
never changed. After each response the script pulls the worker's log lines
for that correlation_id out of `docker logs s9275-worker`, so the whole
send -> receive -> process -> reply -> client-response sequence prints in order
in one terminal.

Run (Kafka and the worker container must be up):
    python code/kafka_app/homework_demo.py
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone

from confluent_kafka import Consumer, Producer

from recall_service import REQUEST_TOPIC, RESPONSE_TOPIC

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
WORKER_CONTAINER = "s9275-worker"
STUDENT = "Xu Wang (SID4 9275, PREFIX s9275)"

NOTICE = {
    "productName": "Sunrise Valley Creamy Peanut Butter, 16 oz jar",
    "recallingFirm": "Sunrise Valley Foods, Inc.",
    "submitterEmail": "quality@sunrisevalleyfoods.com",
    "category": "Undeclared Allergen",
    "description": ("Lots SV2451-SV2458, best-by 2027-03-11 to 2027-03-18, may contain "
                    "undeclared milk from a shared production line. Do not eat; "
                    "return to the store for a full refund."),
    "agreedToTerms": True,
}


def log(stage: str, text: str) -> None:
    now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"{now} [client] {stage:<9} {text}", flush=True)


def worker_lines(cid: str, since: str) -> list[str]:
    """Worker log lines that mention this correlation_id (empty if docker is unavailable)."""
    try:
        out = subprocess.run(["docker", "logs", "--since", since, WORKER_CONTAINER],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line for line in (out.stdout + out.stderr).splitlines() if cid in line]


def wait_for_assignment(consumer: Consumer, timeout: float = 15.0) -> None:
    """Join the response topic before sending, so the reply cannot be missed."""
    deadline = time.time() + timeout
    while not consumer.assignment():
        consumer.poll(0.2)
        if time.time() > deadline:
            raise RuntimeError(f"no partition assigned for {RESPONSE_TOPIC} - does the "
                               "topic exist? (docker compose up -d kafka-init)")


def call(producer: Producer, consumer: Consumer, operation: str, data: dict) -> dict:
    """One full request/response round trip, logged step by step."""
    # For `docker logs --since`; 2 s of slack in case the clocks differ slightly.
    started = (datetime.now(timezone.utc) - timedelta(seconds=2)).strftime("%Y-%m-%dT%H:%M:%S")
    cid = str(uuid.uuid4())
    log("CID", f"created correlation_id={cid}")

    request = {"correlation_id": cid, "reply_to": RESPONSE_TOPIC,
               "operation": operation, "data": data}
    # Log first: the worker can pick the message up before flush() returns.
    log("SENT", f"topic={REQUEST_TOPIC} {json.dumps(request)}")
    producer.produce(REQUEST_TOPIC, key=cid, value=json.dumps(request))
    producer.flush(10)

    response = None
    deadline = time.time() + 15
    while time.time() < deadline:
        msg = consumer.poll(0.5)
        if msg is None or msg.error():
            continue
        candidate = json.loads(msg.value())
        if candidate.get("correlation_id") == cid:
            response = candidate
            break
    if response is None:
        raise RuntimeError(f"no response for {cid} within 15s - is the worker running?")

    for line in worker_lines(cid, started + "Z"):
        print(line, flush=True)
    log("RECEIVED", f"topic={RESPONSE_TOPIC} {json.dumps(response)}")
    same = response.get("correlation_id") == cid
    log("CHECK", f"correlation_id preserved: {same}")
    return response


def main() -> None:
    print(f"=== HW8 Part 1 demo - {STUDENT} ===", flush=True)
    producer = Producer({"bootstrap.servers": BOOTSTRAP})
    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": f"s9275_demo_{uuid.uuid4().hex[:8]}",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
    })
    consumer.subscribe([RESPONSE_TOPIC])
    wait_for_assignment(consumer)

    print("\n--- CREATE_RECALL_NOTICE ---", flush=True)
    created = call(producer, consumer, "CREATE_RECALL_NOTICE", NOTICE)
    if not created.get("success"):
        raise SystemExit(f"create failed: {created}")
    notice_id = created["recall_notice_id"]
    log("EXTRACT", f"recall_notice_id={notice_id}")

    print("\n--- GET_RECALL_NOTICE ---", flush=True)
    fetched = call(producer, consumer, "GET_RECALL_NOTICE", {"recall_notice_id": notice_id})

    print("\n--- Result ---", flush=True)
    print(json.dumps(fetched.get("recall_notice"), indent=2), flush=True)
    log("CHECK", f"retrieved id matches created id: "
                 f"{fetched.get('recall_notice', {}).get('recall_notice_id') == notice_id}")
    consumer.close()


if __name__ == "__main__":
    main()
