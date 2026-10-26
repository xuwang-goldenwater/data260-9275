"""POST /auth/login and GET /auth/me  (HW7: JWT bearer tokens).

HW4 kept a random token in a cookie and a matching row in the sessions table.
HW7 signs a JWT instead: the server stores nothing per login, and the client
sends the token back in the Authorization header. The old version is at tag hw4.
"""
import bcrypt
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from deps import create_access_token, get_current_user, unauthorized
from models import User
from schemas import LoginIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

# Compared against when the username is unknown, so a wrong username and a
# wrong password take the same time and return the same message.
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt())


def check_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    if user is None:
        check_password(payload.password, _DUMMY_HASH.decode("ascii"))
        raise unauthorized("Invalid username or password")
    if not check_password(payload.password, user.password_hash):
        raise unauthorized("Invalid username or password")

    token, expires_in = create_access_token(user)   # only after the hash matched
    return TokenOut(access_token=token, expires_in=expires_in, role=user.role)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
