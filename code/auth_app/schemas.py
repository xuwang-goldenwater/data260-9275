"""Request and response bodies.

Naming: *In is what the client sends (POST and PUT), *Out is what the API
returns. Pydantic checks every *In before the route function runs; a body that
fails becomes a 422 response and never reaches MySQL.
"""
from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

import config

Category = Literal[config.CATEGORIES]  # type: ignore[valid-type]

RECALL_NUMBER_PATTERN = r"^F-\d{4}-\d{4}$"      # FDA style, e.g. F-0123-2026
INT_UNSIGNED_MAX = 4_294_967_295                # MySQL INT UNSIGNED


# ---- auth ---------------------------------------------------------------------

class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str


# ---- firms (related entity) ---------------------------------------------------

class FirmIn(BaseModel):
    """What the client sends on POST /api/firms and PUT /api/firms/{id}."""

    name: str = Field(min_length=1, max_length=150)
    state: str = Field(pattern=r"^[A-Z]{2}$")          # two capital letters, e.g. CA
    contact_email: EmailStr                            # unique field, format checked here


class FirmOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    state: str
    contact_email: str
    created_at: datetime
    updated_at: datetime


class FirmBrief(BaseModel):
    """The short form of a firm that is nested inside each notice."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    state: str


class FirmPage(BaseModel):
    page: int
    page_size: int
    total: int                    # rows in the whole table, not just this page
    items: List[FirmOut]


# ---- recall notices (primary entity) ------------------------------------------

class NoticeIn(BaseModel):
    """What the client sends on POST /api/notices and PUT /api/notices/{id}."""

    product_name: str = Field(min_length=1, max_length=255)
    category: Category
    recall_number: str = Field(pattern=RECALL_NUMBER_PATTERN)     # unique field
    units_affected: int = Field(default=0, ge=0, le=INT_UNSIGNED_MAX)
    firm_id: int = Field(ge=1)                # required: every notice belongs to a firm
    recall_date: Optional[date] = None        # defaults to today on create


class NoticeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_name: str
    category: str
    recall_number: str
    units_affected: int
    recall_date: date
    firm_id: int
    firm: FirmBrief                           # the related row
    created_at: datetime
    updated_at: datetime


class NoticePage(BaseModel):
    version: Literal["naive", "fixed"]
    page: int
    page_size: int
    items: List[NoticeOut]


class FirmNoticesPage(BaseModel):
    """GET /api/firms/{id}/notices - the relationship query."""

    firm: FirmBrief
    page: int
    page_size: int
    total: int                    # how many notices this firm has in all
    items: List[NoticeOut]
