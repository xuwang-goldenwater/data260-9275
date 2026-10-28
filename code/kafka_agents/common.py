"""
DATA 260 - HW8 Part 2: pieces shared by planner.py, writer.py, reviewer.py
and send_question.py.

Flow (every arrow is a Kafka topic, no agent calls another agent):

    send_question -> s9275_inbox -> Planner -> s9275_tasks -> Writer
                  -> s9275_drafts -> Reviewer -> s9275_final

Every message is one JSON object that grows as it moves along. Each agent
copies what it received and adds its own field, so the final message still
carries the original correlation_id and question:

    {"correlation_id", "question", "entity_id", "plan", "draft",
     "status", "answer", "trace": [...]}
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from confluent_kafka import Consumer, Producer

ROOT = Path(__file__).resolve().parents[2]          # repo root
PREFIX = "s9275"
SEED = 9275
VERIFY_SEED = 260000 + SEED                          # 269275
BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
MODEL_NAME = os.getenv("HW8_MODEL", "qwen2.5:3b")

INBOX = f"{PREFIX}_inbox"
TASKS = f"{PREFIX}_tasks"
DRAFTS = f"{PREFIX}_drafts"
FINAL = f"{PREFIX}_final"
DEAD_LETTER = f"{PREFIX}_dead_letter"

# Machine-readable copy of every log line, for reports/hw08/raw/.
EVENTS_FILE = Path(os.getenv("HW8_EVENTS", ROOT / "reports/hw08/raw/agent_events.jsonl"))


def log(agent: str, stage: str, text: str, **fields: Any) -> None:
    """Print one timestamped line and append the same event as JSON."""
    now = datetime.now()
    print(f"{now.strftime('%H:%M:%S.%f')[:-3]} [{agent:<8}] {stage:<10} {text}", flush=True)
    event = {"ts": now.isoformat(timespec="milliseconds"), "agent": agent,
             "stage": stage, "text": text, **fields}
    try:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with EVENTS_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
    except OSError:
        pass  # logging to file is best-effort; the console line is already out


def make_producer() -> Producer:
    return Producer({"bootstrap.servers": BOOTSTRAP})


def make_consumer(group_id: str, topics: List[str], offset_reset: str = "earliest",
                  auto_commit: bool = False) -> Consumer:
    """Consumer with manual commits: an agent commits only after its output is sent.

    auto_commit=True exists only for the HW8 Part 3 "before fix" run: Kafka then
    commits every second in the background, whether or not processing finished.
    """
    config = {
        "bootstrap.servers": BOOTSTRAP,
        "group.id": group_id,
        "auto.offset.reset": offset_reset,
        "enable.auto.commit": auto_commit,
        # A killed consumer is noticed after 10 s instead of the default 45 s,
        # so its partitions move to the restarted consumer quickly.
        "session.timeout.ms": 10000,
    }
    if auto_commit:
        config["auto.commit.interval.ms"] = 1000
    consumer = Consumer(config)
    consumer.subscribe(topics)
    return consumer


def send(producer: Producer, topic: str, message: Dict[str, Any], key: Optional[str] = None) -> None:
    """Produce one JSON message and wait until Kafka has it."""
    producer.produce(topic, key=key, value=json.dumps(message))
    producer.flush(10)


def add_trace(message: Dict[str, Any], agent: str) -> List[Dict[str, str]]:
    """Return the trace list with one more hop, so the final message shows its path."""
    trace = list(message.get("trace", []))
    trace.append({"agent": agent, "at": datetime.now().isoformat(timespec="seconds")})
    return trace


_client = None


def llm(system: str, user: str, max_tokens: int = 400, json_mode: bool = False) -> str:
    """One call to the local model through the HW1 adapter, src/model_client.py."""
    global _client
    if _client is None:
        sys.path.insert(0, str(ROOT / "src"))
        from model_client import ModelClient
        _client = ModelClient(model=MODEL_NAME, temperature=0.0,
                              options={"num_ctx": 4096, "seed": SEED})
    reply = _client.complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
        response_format="json" if json_mode else None,
    )
    return reply.text.strip()
