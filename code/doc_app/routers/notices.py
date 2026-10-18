"""CRUD for recall-notice documents in MongoDB (HW6 Part 1-II).

    POST   /api/doc/notices              create            201 / 409 / 422
    GET    /api/doc/notices              list (newest)     200
    GET    /api/doc/notices/{id}         one               200 / 400 / 404
    PUT    /api/doc/notices/{id}         replace           200 / 400 / 404 / 409 / 422
    DELETE /api/doc/notices/{id}         delete            204 / 400 / 404

Every route can also answer 503 (MongoDB unreachable) or 500 (other database error).

Same routes as HW5's routers/notices.py, with the MySQL pieces swapped:
    db.get(RecallNotice, id)           -> col.find_one({"_id": ObjectId(id)})
    IntegrityError 1062 (duplicate)    -> DuplicateKeyError (code 11000)
    int id in the path                 -> 24-hex ObjectId string, checked first (400)
No login is required here: Part 1 is about the document store, not sessions.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query, Response, status
from pymongo import DESCENDING, ReturnDocument
from pymongo.errors import (ConnectionFailure, DuplicateKeyError, PyMongoError,
                            ServerSelectionTimeoutError, WriteError)

from db import get_notices
from schemas import Category, NoticeIn, NoticeList, NoticeOut, Status

router = APIRouter(prefix="/api/doc/notices", tags=["notice documents"])

VALIDATION_FAILED = 121      # MongoDB: document failed the $jsonSchema validator


# --- helpers ------------------------------------------------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_id(notice_id: str) -> ObjectId:
    """'abc' is not a valid ObjectId -> 400 before touching the database."""
    try:
        return ObjectId(notice_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400,
                            detail=f"Invalid id '{notice_id}': expected a 24-character hex ObjectId.")


def to_out(doc: dict) -> dict:
    """Mongo document -> API shape: _id (ObjectId) becomes id (str)."""
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


@contextmanager
def mongo_errors(action: str):
    """Turn PyMongo exceptions into HTTP status codes in one place.

    HTTPException raised inside the block is not a PyMongoError, so it passes
    straight through (the demo needed `except HTTPException: raise` in every route).
    """
    try:
        yield
    except DuplicateKeyError as exc:
        key = (exc.details or {}).get("keyValue", {})
        raise HTTPException(status_code=409,
                            detail=f"Duplicate value {key}: recall_number must be unique.")
    except WriteError as exc:
        if exc.code == VALIDATION_FAILED:     # should not happen: Pydantic checks first
            raise HTTPException(status_code=422,
                                detail="Document rejected by the database $jsonSchema validator.")
        raise HTTPException(status_code=500, detail=f"Database error while {action}.")
    except (ServerSelectionTimeoutError, ConnectionFailure):
        raise HTTPException(status_code=503, detail="Database unavailable (MongoDB not reachable).")
    except PyMongoError:
        raise HTTPException(status_code=500, detail=f"Database error while {action}.")


# --- routes -------------------------------------------------------------------

@router.post("", response_model=NoticeOut, status_code=status.HTTP_201_CREATED)
def create_notice(payload: NoticeIn):
    doc = payload.model_dump()                 # validated dict, status default filled in
    doc["created_at"] = doc["updated_at"] = now_utc()
    col = get_notices()
    with mongo_errors("creating the notice"):
        result = col.insert_one(doc)
        return to_out(col.find_one({"_id": result.inserted_id}))


@router.get("", response_model=NoticeList)
def list_notices(status_: Optional[Status] = Query(None, alias="status"),
                 category: Optional[Category] = None,
                 limit: int = Query(50, ge=1, le=200)):
    """Newest recall_date first; optional ?status= and ?category= filters."""
    query = {}
    if status_:
        query["status"] = status_
    if category:
        query["category"] = category
    col = get_notices()
    with mongo_errors("listing notices"):
        docs = list(col.find(query).sort([("recall_date", DESCENDING), ("_id", DESCENDING)])
                    .limit(limit))
    return {"count": len(docs), "items": [to_out(d) for d in docs]}


@router.get("/{notice_id}", response_model=NoticeOut)
def get_notice(notice_id: str):
    oid = parse_id(notice_id)
    with mongo_errors("fetching the notice"):
        doc = get_notices().find_one({"_id": oid})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Notice {notice_id} not found.")
    return to_out(doc)


@router.put("/{notice_id}", response_model=NoticeOut)
def update_notice(notice_id: str, payload: NoticeIn):
    """Full replacement (same as HW5). created_at is kept, updated_at is refreshed."""
    oid = parse_id(notice_id)
    changes = payload.model_dump()
    changes["updated_at"] = now_utc()
    with mongo_errors("updating the notice"):
        doc = get_notices().find_one_and_update(
            {"_id": oid}, {"$set": changes}, return_document=ReturnDocument.AFTER)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Notice {notice_id} not found.")
    return to_out(doc)


@router.delete("/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notice(notice_id: str):
    oid = parse_id(notice_id)
    with mongo_errors("deleting the notice"):
        result = get_notices().delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Notice {notice_id} not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
