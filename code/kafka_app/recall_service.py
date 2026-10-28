"""
DATA 260 - HW8 Part 1: RecallNotice request handling, with no Kafka in it.

The worker (worker.py) reads a request message from Kafka and passes it to
handle_request(). This file only decides what the response is, so it can be
tested without a broker. Standard library only, so the worker image stays small.

Request : {"correlation_id", "reply_to", "operation", "data"}
Response: {"correlation_id", "success", ...} - correlation_id is always echoed,
          on errors too.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict

PREFIX = "s9275"
REQUEST_TOPIC = f"{PREFIX}_recall_notice_requests"
RESPONSE_TOPIC = f"{PREFIX}_recall_notice_responses"

CATEGORIES = (
    "Undeclared Allergen",
    "Bacterial Contamination",
    "Foreign Material",
    "Mislabeling",
)
TEXT_FIELDS = ("productName", "recallingFirm", "submitterEmail", "description")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_notice(data: Dict[str, Any]) -> str | None:
    """Return an error message, or None when the record is valid.

    Same rules as DOMAIN_SCHEMA.md, so the Kafka path accepts exactly what
    the HW2 API accepts.
    """
    for name in TEXT_FIELDS:
        value = data.get(name)
        if value is None:
            return f"Missing field: {name}"
        if not isinstance(value, str) or not value.strip():
            return f"Field must be a non-empty string: {name}"
    if not EMAIL_RE.match(data["submitterEmail"].strip()):
        return "Invalid field: submitterEmail is not a valid email"
    if len(data["description"].strip()) <= 25:
        return "Invalid field: description must be longer than 25 characters"
    if data.get("category") not in CATEGORIES:
        return f"Invalid field: category must be one of {list(CATEGORIES)}"
    if data.get("agreedToTerms") is not True:
        return "Invalid field: agreedToTerms must be true"
    return None


def handle_request(message: Dict[str, Any], store: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Process one request against the in-memory store and build the response."""
    cid = message.get("correlation_id")
    operation = message.get("operation")
    data = message.get("data")

    def error(text: str) -> Dict[str, Any]:
        return {"correlation_id": cid, "success": False, "error": text}

    if not cid:
        return error("Missing correlation_id")
    if not isinstance(data, dict):
        return error("Field 'data' must be an object")

    if operation == "CREATE_RECALL_NOTICE":
        problem = validate_notice(data)
        if problem:
            return error(problem)
        notice_id = str(uuid.uuid4())
        record = {"recall_notice_id": notice_id}
        for name in TEXT_FIELDS:
            record[name] = data[name].strip()
        record["category"] = data["category"]
        record["agreedToTerms"] = True
        if data.get("submissionDate"):
            record["submissionDate"] = data["submissionDate"]
        store[notice_id] = record
        return {"correlation_id": cid, "success": True,
                "recall_notice_id": notice_id, "message": "Recall notice created"}

    if operation == "GET_RECALL_NOTICE":
        notice_id = data.get("recall_notice_id")
        if not isinstance(notice_id, str) or not notice_id.strip():
            return error("Missing field: recall_notice_id")
        record = store.get(notice_id.strip())
        if record is None:
            return error("Recall notice not found")
        return {"correlation_id": cid, "success": True, "recall_notice": record}

    return error("Unknown operation")
