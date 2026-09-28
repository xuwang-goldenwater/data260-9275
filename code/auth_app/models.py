"""ORM classes. They mirror code/sql/hw04_schema.sql; the SQL file is the source of truth."""
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(60), nullable=False)   # bcrypt output is 60 chars


class SessionToken(Base):
    """One row per logged-in browser. The cookie holds only `id`."""

    __tablename__ = "sessions"

    id = Column(String(64), primary_key=True)             # opaque random token
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False)         # naive UTC
    expires_at = Column(DateTime, nullable=False)         # naive UTC, pushed forward on use

    user = relationship("User", lazy="joined")


class Firm(Base):
    """Related table for Part 3: the company that issued the recall (200 seeded rows)."""

    __tablename__ = "firms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False)
    state = Column(String(2), nullable=False)


class RecallNotice(Base):
    """Primary domain entity (DOMAIN_ID 3)."""

    __tablename__ = "recall_notices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_name = Column(String(255), nullable=False)    # primary field
    category = Column(String(40), nullable=False)          # secondary field
    firm_id = Column(Integer, ForeignKey("firms.id", ondelete="SET NULL"), nullable=True)
    recall_date = Column(Date, nullable=False)

    # lazy="raise": touching notice.firm without saying how to load it is an
    # error. The naive endpoint therefore has to issue its per-row query on
    # purpose, and the fixed endpoint has to ask for joinedload. No accidental
    # N+1 anywhere else in the app.
    firm = relationship("Firm", lazy="raise")
