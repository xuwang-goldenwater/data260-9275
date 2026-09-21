"""
Routes for HW3 Part 1: /, /login, /dashboard, /logout.

Why there is a server-side session table (ACTIVE_SESSIONS):
Starlette's SessionMiddleware keeps the session *inside* the signed cookie.
If we only did request.session.clear() on logout, someone who saved the old
cookie could send it again and still reach /dashboard until max_age runs out.
So the cookie only carries a random session id ("sid"), and the server keeps
the list of sids that are still valid. Logout and idle timeout delete the sid
from that list, which makes the old cookie useless.
"""
import os
import secrets
import time
from pathlib import Path

import bcrypt
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_302_FOUND

router = APIRouter()

# Absolute path, so the app works no matter which folder it is started from
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# Log out a user who has not made a request for this many seconds
IDLE_TIMEOUT_SECONDS = int(os.getenv("IDLE_TIMEOUT_SECONDS", "900"))  # 15 minutes

# Demo user. Only the bcrypt hash of the password is kept in memory.
# A real application would load users from a database.
USERS = {
    "admin": bcrypt.hashpw(b"password", bcrypt.gensalt()),
}

# sid -> {"user": username, "last_seen": unix time}
ACTIVE_SESSIONS = {}


def get_current_user(request: Request):
    """Return the logged-in username, or None.

    Also enforces the idle timeout and refreshes last_seen on every request.
    """
    sid = request.session.get("sid")
    if not sid:
        return None

    record = ACTIVE_SESSIONS.get(sid)
    if record is None:
        # sid was logged out (or the server restarted) -> cookie is dead
        request.session.clear()
        return None

    idle_for = time.time() - record["last_seen"]
    if idle_for > IDLE_TIMEOUT_SECONDS:
        # idle too long -> end the session on the server side
        del ACTIVE_SESSIONS[sid]
        request.session.clear()
        return None

    record["last_seen"] = time.time()
    return record["user"]


def check_password(username: str, password: str) -> bool:
    hashed = USERS.get(username)
    if hashed is None:
        return False
    return bcrypt.checkpw(password.encode("utf-8"), hashed)


@router.get("/")
def home(request: Request):
    user = get_current_user(request)
    return templates.TemplateResponse(
        request, "index.html", {"user": user}
    )


@router.get("/login")
def login_page(request: Request, reason: str = ""):
    user = get_current_user(request)

    info = None
    if reason == "ended":
        info = "Your session has ended (idle timeout or logout). Please log in again."

    return templates.TemplateResponse(
        request, "login.html", {"user": user, "error": None, "info": info}
    )


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if check_password(username, password):
        # Start a fresh session with a new random id
        request.session.clear()
        sid = secrets.token_urlsafe(32)
        ACTIVE_SESSIONS[sid] = {"user": username, "last_seen": time.time()}
        request.session["sid"] = sid
        return RedirectResponse(url="/dashboard", status_code=HTTP_302_FOUND)

    # Wrong username or password: show the login page again with an alert
    return templates.TemplateResponse(
        request,
        "login.html",
        {"user": None, "error": "Invalid username or password.", "info": None},
        status_code=401,
    )


@router.get("/dashboard")
def dashboard(request: Request):
    had_sid = "sid" in request.session
    user = get_current_user(request)

    if not user:
        url = "/login?reason=ended" if had_sid else "/login"
        return RedirectResponse(url=url, status_code=HTTP_302_FOUND)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"user": user, "idle_minutes": IDLE_TIMEOUT_SECONDS // 60},
    )


@router.get("/logout")
def logout(request: Request):
    sid = request.session.get("sid")
    if sid:
        ACTIVE_SESSIONS.pop(sid, None)  # old cookie can no longer be used
    request.session.clear()
    return RedirectResponse(url="/", status_code=HTTP_302_FOUND)
