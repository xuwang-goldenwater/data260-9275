"""
DATA 260 - HW8 Part 3: the fixes for duplicate delivery and poison messages.

ProcessedStore     - idempotency. Remembers which correlation_ids this agent
                     has already finished, in a file, so a replayed message
                     (or a redelivery after a restart) is skipped instead of
                     producing a second draft.
run_with_retries   - bounded retries. Calls the processing function up to
                     MAX_ATTEMPTS times with a short backoff.
to_dead_letter     - after the last failed attempt, the original message and
                     the error go to s9275_dead_letter, so the agent can commit
                     and move on to the next message.

Order inside the agent (writer.py) when fixes are on:
    poll -> already processed? skip+commit -> run_with_retries
         -> success: send result, mark processed, commit
         -> failure: send to dead letter, commit
The offset is committed last in every branch, after the output is in Kafka.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Callable, Dict, Tuple

from common import DEAD_LETTER, ROOT, send

MAX_ATTEMPTS = 3
BACKOFF_S = 0.5
STATE_DIR = ROOT / "var"          # runtime state, git-ignored


class ProcessedStore:
    """Set of finished correlation_ids, kept in an append-only file.

    The file survives restarts, which matters: after a crash the redelivered
    message must still be recognised if its output was already sent.
    """

    def __init__(self, name: str) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.path = STATE_DIR / f"{name}_processed.txt"
        self.ids = set()
        if self.path.exists():
            self.ids = {ln.strip() for ln in self.path.read_text().splitlines() if ln.strip()}

    def seen(self, cid: str) -> bool:
        return cid in self.ids

    def mark(self, cid: str) -> None:
        """Call only after the output has been sent."""
        self.ids.add(cid)
        with self.path.open("a") as fh:
            fh.write(cid + "\n")


def run_with_retries(fn: Callable[[Dict[str, Any]], Any], message: Dict[str, Any],
                     on_retry: Callable[[int, Exception], None]) -> Tuple[bool, Any, int]:
    """Return (ok, result_or_error_text, attempts_used)."""
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return True, fn(message), attempt
        except Exception as exc:  # noqa: BLE001 - any failure counts as a failed attempt
            last_error = exc
            on_retry(attempt, exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(BACKOFF_S * attempt)
    return False, f"{type(last_error).__name__}: {last_error}", MAX_ATTEMPTS


def to_dead_letter(producer, raw: bytes, msg, agent: str, error: str, attempts: int) -> Dict[str, Any]:
    """Send the failed message, unchanged, plus why it failed, to the dead-letter topic."""
    try:
        original: Any = json.loads(raw)
    except ValueError:
        original = raw.decode("utf-8", errors="replace")
    record = {
        "correlation_id": original.get("correlation_id") if isinstance(original, dict) else None,
        "failed_agent": agent,
        "source_topic": msg.topic(),
        "source_partition": msg.partition(),
        "source_offset": msg.offset(),
        "attempts": attempts,
        "error": error,
        "failed_at": datetime.now().isoformat(timespec="seconds"),
        "original": original,
    }
    send(producer, DEAD_LETTER, record)
    return record
