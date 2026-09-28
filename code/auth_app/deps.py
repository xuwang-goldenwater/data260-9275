"""Session lookup shared by every protected route."""
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

import config
from database import get_db
from models import SessionToken


def utcnow() -> datetime:
    """Naive UTC. MySQL DATETIME has no time zone, so both sides stay naive."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_expiry(created_at: datetime, now: datetime) -> datetime:
    """Idle limit from now, but never past the absolute limit from login."""
    idle = now + timedelta(seconds=config.IDLE_TIMEOUT_SECONDS)
    absolute = created_at + timedelta(seconds=config.ABSOLUTE_TIMEOUT_SECONDS)
    return min(idle, absolute)


def require_session(request: Request, db: Session = Depends(get_db)) -> SessionToken:
    """401 unless the cookie names a live row in the sessions table.

    Costs two SQL statements per request (SELECT the session, UPDATE its
    expiry). Part 3 reports these separately from the list query itself.
    """
    token = request.cookies.get(config.COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Login required")

    row = db.get(SessionToken, token)
    now = utcnow()
    if row is None:
        raise HTTPException(status_code=401, detail="Login required")
    if row.expires_at <= now:
        db.delete(row)
        db.commit()
        raise HTTPException(status_code=401, detail="Session expired")

    row.expires_at = new_expiry(row.created_at, now)   # sliding idle timeout
    db.commit()
    return row
