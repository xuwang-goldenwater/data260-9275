"""
DATA 260 - Homework 2, Part 2: FastAPI backend for the RecallNotice entity.

Runs on PORT_BASE = 8000 + (9275 mod 900) = 8275 and serves both the JSON API
and the Part 1 front end, so the whole application is one process on one port.

    python code/api_server.py
    # or:  make run-api

Endpoints
    GET    /                      the Part 1 page (code/web_application/)
    GET    /api/notices           list, optional ?q= search           (Part 2.4)
    GET    /api/notices/{id}      one record
    POST   /api/notices           add a record                       (Part 2.1)
    PUT    /api/notices/{id}      replace a record                   (Part 2.2)
    DELETE /api/notices/{id}      remove a record                    (Part 2.3)

Storage is a JSON file, code/data/recall_notices.json, created from
recall_notices.seed.json the first time the server starts. Deleting the runtime
file and restarting returns the application to a known state, which is what
makes the screenshots in the report reproducible.

Two environment variables exist only to make the required UI states
photographable; both default to off and neither changes the API contract:

    DEMO_DELAY_MS=1500   sleep before answering GET /api/notices  (loading state)
    DEMO_FAIL_LIST=1     make GET /api/notices return 500          (error state)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

# --- Section 0 configuration -------------------------------------------------
SID4 = 9275
PORT_BASE = 8000 + SID4 % 900          # 8275
PREFIX = f"s{SID4}"                    # s9275

HERE = Path(__file__).resolve().parent
WEB_DIR = HERE / "web_application"
DATA_DIR = HERE / "data"
SEED_FILE = DATA_DIR / "recall_notices.seed.json"
STORE_FILE = Path(os.getenv("NOTICE_STORE", DATA_DIR / "recall_notices.json"))

CATEGORIES = (
    "Undeclared Allergen",
    "Bacterial Contamination",
    "Foreign Material",
    "Mislabeling",
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# --- models ------------------------------------------------------------------
# The field names are the ones in DOMAIN_SCHEMA.md. The same names are used by
# the HTML ids, by app.js, and by the Part 3 agent graph.


class NoticeIn(BaseModel):
    """What the client sends on POST and PUT."""

    productName: str = Field(min_length=1)
    recallingFirm: str = Field(min_length=1)
    submitterEmail: str
    description: str
    category: Literal[CATEGORIES]  # type: ignore[valid-type]
    agreedToTerms: bool
    submissionDate: Optional[str] = None

    @field_validator("submitterEmail")
    @classmethod
    def _email(cls, value: str) -> str:
        if not EMAIL_RE.match(value.strip()):
            raise ValueError("submitterEmail is not a valid email address")
        return value.strip()

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        # The same rule the browser enforces in app.js, enforced again here.
        # A client-side check is a convenience; it is not a guarantee, because
        # anyone can POST to this endpoint without going through the page.
        if len(value.strip()) <= 25:
            raise ValueError("description must be longer than 25 characters")
        return value

    @field_validator("agreedToTerms")
    @classmethod
    def _terms(cls, value: bool) -> bool:
        if not value:
            raise ValueError("agreedToTerms must be true")
        return value


class Notice(NoticeIn):
    """What the server stores and returns."""

    id: int
    submissionDate: str


# --- storage -----------------------------------------------------------------


def load_notices() -> List[dict]:
    """Read the store, creating it from the seed file on first use."""
    if not STORE_FILE.exists():
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SEED_FILE, STORE_FILE)
    return json.loads(STORE_FILE.read_text(encoding="utf-8"))


def save_notices(notices: List[dict]) -> None:
    """Write the whole store back.

    Written to a temporary file and moved into place, so an interrupted write
    cannot leave a half-written JSON file behind.
    """
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(notices, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STORE_FILE)


def next_id(notices: List[dict]) -> int:
    return max((int(n["id"]) for n in notices), default=0) + 1


def find_index(notices: List[dict], notice_id: int) -> int:
    for index, notice in enumerate(notices):
        if int(notice["id"]) == notice_id:
            return index
    raise HTTPException(status_code=404, detail=f"Recall notice {notice_id} not found")


# --- app ---------------------------------------------------------------------

app = FastAPI(
    title="Recall Notice API",
    version="2.0.0",
    description=f"DATA 260 HW2 - domain 3, grocery supply and recall notices ({PREFIX})",
)


@app.get("/api/config")
async def get_config() -> dict:
    """Section 0 values, so the running server can be checked against them."""
    return {"sid4": SID4, "port_base": PORT_BASE, "prefix": PREFIX, "domain_id": SID4 % 8}


@app.get("/api/notices", response_model=List[Notice])
async def list_notices(
    response: Response,
    q: Optional[str] = Query(default=None, description="match product name or recalling firm"),
) -> List[dict]:
    """Part 2.4 - list, optionally filtered by a search term.

    The term is matched case-insensitively against the primary field
    (productName) and the secondary field (recallingFirm).
    """
    delay_ms = int(os.getenv("DEMO_DELAY_MS", "0"))
    if delay_ms:
        await asyncio.sleep(delay_ms / 1000.0)

    if os.getenv("DEMO_FAIL_LIST") == "1":
        raise HTTPException(status_code=500, detail="Recall notice store is unavailable")

    response.headers["Cache-Control"] = "no-store"
    notices = load_notices()

    if q:
        needle = q.strip().lower()
        notices = [
            n
            for n in notices
            if needle in n["productName"].lower() or needle in n["recallingFirm"].lower()
        ]
    return notices


@app.get("/api/notices/{notice_id}", response_model=Notice)
async def get_notice(notice_id: int) -> dict:
    notices = load_notices()
    return notices[find_index(notices, notice_id)]


@app.post("/api/notices", response_model=Notice, status_code=201)
async def create_notice(payload: NoticeIn) -> dict:
    """Part 2.1 - add a new record and return it with its assigned id."""
    notices = load_notices()
    record = payload.model_dump()
    record["id"] = next_id(notices)
    record["submissionDate"] = payload.submissionDate or datetime.now(timezone.utc).isoformat()
    notices.append(record)
    save_notices(notices)
    print(f"[POST]   created notice {record['id']}: {record['productName']}")
    return record


@app.put("/api/notices/{notice_id}", response_model=Notice)
async def update_notice(notice_id: int, payload: NoticeIn) -> dict:
    """Part 2.2 - replace the primary, secondary and remaining fields of a record.

    The id is not editable: it identifies the record being changed.
    """
    notices = load_notices()
    index = find_index(notices, notice_id)
    record = payload.model_dump()
    record["id"] = notice_id
    record["submissionDate"] = payload.submissionDate or notices[index]["submissionDate"]
    notices[index] = record
    save_notices(notices)
    print(f"[PUT]    updated notice {notice_id}: {record['productName']}")
    return record


@app.delete("/api/notices/{notice_id}", status_code=204)
async def delete_notice(notice_id: int) -> Response:
    """Part 2.3 - remove a record."""
    notices = load_notices()
    index = find_index(notices, notice_id)
    removed = notices.pop(index)
    save_notices(notices)
    print(f"[DELETE] removed notice {notice_id}: {removed['productName']}")
    return Response(status_code=204)


# The front end is mounted last so every /api route above is matched first.
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    print(f"Recall Notice API on http://127.0.0.1:{PORT_BASE}  (PORT_BASE for SID4 {SID4})")
    print(f"store: {STORE_FILE}")
    uvicorn.run(app, host="127.0.0.1", port=PORT_BASE)
