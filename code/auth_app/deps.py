"""Who is calling, and may they do this?  (HW7: JWT bearer + roles)

    get_current_user  ->  401 when the token is missing, malformed, badly signed
                          or expired, or names a user that no longer exists
    require_role(...) ->  403 when the token is fine but the role is not allowed

401 = "I don't know who you are".  403 = "I know who you are, and the answer is no".
"""
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

import config
from database import get_db
from models import User

# auto_error=False: with True, FastAPI answers a missing header itself (403 in
# older versions). We want every authentication failure to be our own 401.
bearer_scheme = HTTPBearer(auto_error=False)


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail,
                         headers={"WWW-Authenticate": "Bearer"})


def create_access_token(user: User) -> tuple[str, int]:
    """Signed JWT for this user. Returns (token, lifetime in seconds)."""
    now = datetime.now(timezone.utc)
    lifetime = timedelta(minutes=config.ACCESS_TOKEN_MINUTES)
    claims = {
        "sub": str(user.id),          # JWT spec: subject is a string
        "username": user.username,
        "role": user.role,
        "iat": now,
        "exp": now + lifetime,        # PyJWT rejects the token after this
    }
    token = jwt.encode(claims, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)
    return token, int(lifetime.total_seconds())


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
                     db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise unauthorized("Not authenticated: send Authorization: Bearer <token>")
    try:
        claims = jwt.decode(creds.credentials, config.JWT_SECRET,
                            algorithms=[config.JWT_ALGORITHM],   # never trust the header's alg
                            options={"require": ["sub", "exp"]})
    except jwt.ExpiredSignatureError:
        raise unauthorized("Token expired") from None
    except jwt.InvalidTokenError:
        raise unauthorized("Invalid token") from None

    # The role is read from MySQL, not from the token: a changed role takes
    # effect on the next request instead of when the old token expires.
    user = db.get(User, int(claims["sub"]))
    if user is None:
        raise unauthorized("Invalid token")
    return user


def require_role(*allowed: str):
    """Dependency factory: require_role("writer", "moderator")."""
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403,
                                detail=f"Role '{user.role}' may not do this; needs one of {list(allowed)}")
        return user
    return checker
