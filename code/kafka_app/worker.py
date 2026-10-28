"""
DATA 260 - HW8 Part 1: RecallNotice worker.

Consumes s9275_recall_notice_requests, runs handle_request() from
recall_service.py, and produces the response to the topic named in the
request's reply_to field, echoing correlation_id unchanged.

Entities live in a plain dict (STORE) inside this process, as the assignment
asks. Restarting the worker empties it.

Offsets are committed by hand, only after the response has been delivered to
Kafka, so a crash between "received" and "replied" means the request is read
again on restart instead of being silently dropped.

Run in Docker (see docker-compose.yml) or on the Mac:
    python code/kafka_app/worker.py
"""

from __future__ import annotations

import json
import os
import signal
import sys
from datetime import datetime

from confluent_kafka import Consumer, Producer

from recall_service import REQUEST_TOPIC, RESPONSE_TOPIC, handle_request

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
GROUP_ID = "s9275_recall_worker"

STORE: dict = {}
running = True


def log(stage: str, text: str) -> None:
    """One timestamped log line; flush so `docker logs` shows it at once."""
    now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"{now} [worker] {stage:<9} {text}", flush=True)


def stop(signum, frame) -> None:  # noqa: ARG001
    global running
    running = False


def main() -> None:
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": GROUP_ID,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    producer = Producer({"bootstrap.servers": BOOTSTRAP})
    consumer.subscribe([REQUEST_TOPIC])
    log("START", f"bootstrap={BOOTSTRAP} topic={REQUEST_TOPIC} group={GROUP_ID}")
    log("READY", "Consumer is ready and listening...")

    while running:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            log("ERROR", str(msg.error()))
            continue

        raw = msg.value().decode("utf-8", errors="replace")
        log("RECEIVED", f"partition={msg.partition()} offset={msg.offset()} {raw}")

        try:
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise ValueError("request is not a JSON object")
        except ValueError as exc:
            # Unparseable message: nobody to reply to, so log it and move past it.
            log("SKIPPED", f"bad JSON at offset {msg.offset()}: {exc}")
            consumer.commit(message=msg, asynchronous=False)
            continue

        response = handle_request(request, STORE)
        log("PROCESSED", f"cid={response['correlation_id']} op={request.get('operation')} "
                         f"success={response['success']} store_size={len(STORE)}")

        reply_to = request.get("reply_to") or RESPONSE_TOPIC
        producer.produce(reply_to, key=str(response["correlation_id"]),
                         value=json.dumps(response))
        producer.flush(10)
        log("SENT", f"topic={reply_to} {json.dumps(response)}")

        consumer.commit(message=msg, asynchronous=False)

    log("STOP", "closing consumer")
    consumer.close()


if __name__ == "__main__":
    sys.exit(main())
