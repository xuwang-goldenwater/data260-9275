"""Request and response bodies."""
from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

import config

Category = Literal[config.CATEGORIES]  # type: ignore[valid-type]


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str


class FirmOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    state: str


class NoticeIn(BaseModel):
    """What the client sends on POST and PUT."""

    product_name: str = Field(min_length=1, max_length=255)
    category: Category
    recall_date: Optional[date] = None      # defaults to today on create
    firm_id: Optional[int] = None


class NoticeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_name: str
    category: str
    recall_date: date
    firm: Optional[FirmOut] = None          # the related row (Part 3)


class NoticePage(BaseModel):
    version: Literal["naive", "fixed"]
    page: int
    page_size: int
    items: List[NoticeOut]
