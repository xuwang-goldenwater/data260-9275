"""Login / logout / who-am-I, backed by the users and sessions tables.

HW3 kept users and session ids in two in-memory dicts. HW4 moves both into
MySQL, so sessions survive a server restart and logout is a DELETE of one row.

The cookie holds only a random token (secrets.token_urlsafe). It carries no
user data; the server maps token -> user_id through the sessions table.
"""
import secrets

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from database import get_db
from deps import new_expiry, require_session, utcnow
from models import SessionToken, User
from schemas import LoginIn, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Compared against when the email is unknown, so a wrong email and a wrong
# password take the same time and return the same message.
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def check_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))


@router.post("/login", response_model=UserOut)
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if user is None:
        bcrypt.checkpw(payload.password.encode("utf-8"), _DUMMY_HASH)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not check_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    now = utcnow()
    token = secrets.token_urlsafe(32)            # 43 random URL-safe characters
    db.add(SessionToken(id=token, user_id=user.id, created_at=now,
                        expires_at=new_expiry(now, now)))
    db.commit()

    response.set_cookie(
        key=config.COOKIE_NAME,
        value=token,
        httponly=True,        # JavaScript cannot read it
        samesite="lax",       # sent to localhost:8275 from localhost:5173 (same site)
        secure=False,         # plain http on localhost; set True behind HTTPS
        max_age=config.ABSOLUTE_TIMEOUT_SECONDS,
        path="/",
    )
    return user


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(config.COOKIE_NAME)
    if token:
        row = db.get(SessionToken, token)
        if row is not None:
            db.delete(row)                       # the old cookie is now useless
            db.commit()
    response.delete_cookie(config.COOKIE_NAME, path="/")
    return {"message": "logged out"}


@router.get("/me", response_model=UserOut)
def me(session: SessionToken = Depends(require_session)):
    return session.user
