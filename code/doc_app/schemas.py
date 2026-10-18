"""Pydantic schemas for the recall-notice document API (HW6 Part 1-III).

This is the API-layer check. init_db.py's $jsonSchema is the database-layer
check. Both read their limits and allowed values from config.py.

Differences from auth_app/schemas.py (HW5):
  - id is a str (the 24-hex ObjectId), not an int
  - firm is an embedded object, not a firm_id foreign key
  - recall_date is a datetime (the assignment asks for a date/time field)
  - extra="forbid": unknown fields -> 422, mirroring additionalProperties: False
"""
from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

import config

Status = Literal[config.STATUSES]          # "ongoing" | "completed" | "terminated"
Category = Literal[config.CATEGORIES]      # the four HW4/HW5 categories


class FirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    state: Optional[str] = Field(default=None, pattern=r"^[A-Z]{2}$")


class NoticeIn(BaseModel):
    """Body of POST /api/doc/notices and PUT /api/doc/notices/{id}.

    PUT replaces the whole document (same as HW5), so it uses this model too.
    created_at / updated_at are not here: the server sets them.
    """
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_name: str = Field(min_length=1, max_length=config.PRODUCT_NAME_MAX)
    reason: Optional[str] = Field(default=None, max_length=config.REASON_MAX)
    recall_number: str = Field(pattern=config.RECALL_NUMBER_PATTERN)
    status: Status = config.DEFAULT_STATUS
    category: Category
    recall_date: datetime
    firm: Optional[FirmIn] = None

    @field_validator("recall_date")
    @classmethod
    def assume_utc(cls, value: datetime) -> datetime:
        """A time sent without a zone is taken as UTC, so storage is consistent."""
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class FirmOut(BaseModel):
    name: str
    state: Optional[str] = None


class NoticeOut(BaseModel):
    id: str
    product_name: str
    reason: Optional[str] = None
    recall_number: str
    status: Status
    category: Category
    recall_date: datetime
    firm: Optional[FirmOut] = None
    created_at: datetime
    updated_at: datetime


class NoticeList(BaseModel):
    count: int
    items: List[NoticeOut]
