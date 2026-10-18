"""HW6 Part 2 endpoints. The memory logic itself lives in memory.py.

    POST /api/chat                   one chat turn with short-term, long-term and episodic memory
    GET  /api/memory/{user_id}       last ~16 messages, latest session + lifetime summary, last ~20 facts
    GET  /api/aggregate/{user_id}    messages per day + most recent summaries

Errors: 422 bad body (Pydantic), 503 Ollama or MongoDB unreachable, 500 other database error.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

import memory
from routers.notices import mongo_errors          # same PyMongo -> HTTP mapping as Part 1

router = APIRouter(tags=["memory chat"])

ID_PATTERN = r"^[A-Za-z0-9_.-]{1,64}$"            # safe as a Mongo filter value and in a URL


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    user_id: str = Field(pattern=ID_PATTERN)
    session_id: Optional[str] = Field(default=None, pattern=ID_PATTERN,
                                      description="omit to start a new session")
    message: str = Field(min_length=1, max_length=2000)
    # Part 3 runs the same conversation with N = 4 / 12 / 30 without restarting the API
    short_term_n: Optional[int] = Field(default=None, ge=0, le=60,
                                        description="override SHORT_TERM_N for this turn")


def model_unavailable(exc: Exception) -> bool:
    """Ollama not running shows up as a connection error from its HTTP client."""
    name = type(exc).__name__
    return isinstance(exc, ConnectionError) or name in {"ConnectError", "ResponseError",
                                                        "ConnectTimeout", "ReadTimeout"}


@router.post("/api/chat")
def chat(payload: ChatIn):
    with mongo_errors("running the chat turn"):
        try:
            result = memory.chat_turn(payload.user_id, payload.message,
                                      payload.session_id, payload.short_term_n)
        except Exception as exc:
            if model_unavailable(exc):
                raise HTTPException(status_code=503,
                                    detail="Model unavailable: is Ollama running (ollama serve)?")
            raise
    result.pop("_sections", None)
    return result


UserId = Path(..., pattern=ID_PATTERN)


@router.get("/api/memory/{user_id}")
def get_memory(user_id: str = UserId):
    with mongo_errors("reading memory"):
        return memory.memory_view(user_id)


@router.get("/api/aggregate/{user_id}")
def get_aggregate(user_id: str = UserId):
    with mongo_errors("aggregating messages"):
        return memory.aggregate_view(user_id)
