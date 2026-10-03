"""ORM classes. They mirror code/sql/hw04_schema.sql; the SQL file is the source of truth."""
from sqlalchemy import Column, Date, DateTime, FetchedValue, ForeignKey, Integer, String, func
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
    """Related entity: the company that issued the recall (HW5: full CRUD)."""

    __tablename__ = "firms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False)                         # primary text field
    state = Column(String(2), nullable=False)                          # secondary text field
    contact_email = Column(String(255), nullable=False, unique=True)   # unique field

    # MySQL fills both columns (DEFAULT CURRENT_TIMESTAMP / ON UPDATE ...).
    # server_default: leave the column out of INSERT and read the value back.
    # server_onupdate: the value changes on UPDATE, so the loaded copy is stale.
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(),
                        server_onupdate=FetchedValue())


class RecallNotice(Base):
    """Primary domain entity (DOMAIN_ID 3)."""

    __tablename__ = "recall_notices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_name = Column(String(255), nullable=False)                 # primary field
    category = Column(String(40), nullable=False)                      # secondary field
    recall_number = Column(String(11), nullable=False, unique=True)    # unique field, F-NNNN-YYYY
    units_affected = Column(Integer, nullable=False, server_default="0")   # numeric, default 0
    recall_date = Column(Date, nullable=False)

    # HW5: every notice belongs to a firm, and a firm that still has notices
    # cannot be deleted (MySQL error 1451, returned by the API as 409).
    firm_id = Column(Integer, ForeignKey("firms.id", ondelete="RESTRICT"), nullable=False)

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(),
                        server_onupdate=FetchedValue())

    # lazy="raise": touching notice.firm without saying how to load it is an
    # error. The naive endpoint therefore has to issue its per-row query on
    # purpose, and the fixed endpoint has to ask for joinedload. No accidental
    # N+1 anywhere else in the app.
    firm = relationship("Firm", lazy="raise")
