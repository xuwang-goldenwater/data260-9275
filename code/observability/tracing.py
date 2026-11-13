"""
DATA 260 - HW10 Part 4: one structured JSON span per stage.

trace_id is the HW8 correlation_id. It is created once, at the start of
SemanticCache.ask(), before the cache lookup, so a cache hit has a trace too.
Every process (gateway, Planner, Writer, Reviewer, evaluator) appends its spans
to the same JSONL file; the Streamlit dashboard and the latency script read it.

One span = one line:
    {"trace_id", "stage", "start_ts", "end_ts", "duration_ms", "status",
     "error", "pid", ...extra fields such as cache="hit"/"miss" or hop="tasks"}

Usage:
    with span(trace_id, "writer") as s:
        s["model"] = "qwen2.5:3b"          # optional extra fields
        ...                                # an exception -> status="error", re-raised

    record_queue_wait(trace_id, "tasks", msg)   # right after consumer.poll() returns msg
"""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

ROOT = Path(__file__).resolve().parents[2]          # repo root
SPANS_FILE = Path(os.getenv("HW10_SPANS", ROOT / "reports/hw10/raw/spans.jsonl"))


def new_trace_id() -> str:
    """The only request identifier in the system (also used as correlation_id)."""
    return str(uuid.uuid4())


def _iso(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s).isoformat(timespec="milliseconds")


def write_span(trace_id: str, stage: str, start_s: float, end_s: float,
               status: str = "ok", error: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    """Append one span. Times are epoch seconds (time.time()), same clock in every process."""
    record = {"trace_id": trace_id, "stage": stage,
              "start_ts": _iso(start_s), "end_ts": _iso(end_s),
              "duration_ms": round((end_s - start_s) * 1000, 1),
              "status": status, "error": error, "pid": os.getpid(), **extra}
    try:
        SPANS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with SPANS_FILE.open("a", encoding="utf-8") as fh:   # one short line per write
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass  # tracing must never break the request itself
    return record


@contextmanager
def span(trace_id: str, stage: str, **extra: Any) -> Iterator[Dict[str, Any]]:
    """Time the block; on an exception record status=error with the message, then re-raise."""
    fields: Dict[str, Any] = dict(extra)
    start = time.time()
    try:
        yield fields
    except BaseException as exc:          # also Ctrl+C / SystemExit: an interrupted request still leaves a span
        write_span(trace_id, stage, start, time.time(), "error",
                   f"{type(exc).__name__}: {exc}", **fields)
        raise
    write_span(trace_id, stage, start, time.time(), fields.pop("status", "ok"),
               fields.pop("error", None), **fields)


def record_queue_wait(trace_id: str, hop: str, msg: Any) -> Dict[str, Any]:
    """Queue wait for one Kafka hop = now - the producer's CreateTime stamped on the message."""
    _, produced_ms = msg.timestamp()
    return write_span(trace_id, "queue_wait", produced_ms / 1000, time.time(), hop=hop)


if __name__ == "__main__":
    # Self-test: three spans (ok, extra field, error) into a scratch file.
    SPANS_FILE = Path("/tmp/spans_selftest.jsonl")
    SPANS_FILE.unlink(missing_ok=True)
    tid = new_trace_id()
    with span(tid, "cache_lookup") as s:
        time.sleep(0.05)
        s["cache"] = "miss"
    with span(tid, "planner"):
        time.sleep(0.02)
    try:
        with span(tid, "writer"):
            raise RuntimeError("injected failure")
    except RuntimeError:
        pass
    print(SPANS_FILE.read_text(), end="")
