"""
HW3 Part 1 - proof that the session cookie is secure and cannot be reused.

Runs the real auth app in-process (FastAPI TestClient, no server needed) and
prints each step, so the output can be screenshotted for the report:

  1. log in and show the Set-Cookie header (HttpOnly, Secure, SameSite)
  2. use the cookie to open /dashboard            -> 200
  3. log out, then send the OLD cookie again       -> 302 back to /login
  4. log in again, wait longer than the idle limit -> 302 back to /login

The idle limit is set to 3 seconds here only so the demo is fast; the app
itself uses 15 minutes (IDLE_TIMEOUT_SECONDS).

Run:  make demo-session
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "auth_app"))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from routers import auth  # noqa: E402

BASE = "https://testserver"  # https, because the cookie is Secure
LOGIN = {"username": "admin", "password": "password"}


def show(step, response):
    where = response.headers.get("location", "")
    print(f"{step:<48} -> {response.status_code} {where}")


print("== 1. Login ==")
browser = TestClient(main.app, base_url=BASE)
r = browser.post("/login", data=LOGIN, follow_redirects=False)
show("POST /login (correct password)", r)
print("Set-Cookie:", r.headers["set-cookie"])
old_cookie = r.cookies.get("session")

print("\n== 2. Use the session ==")
show("GET /dashboard with the cookie", browser.get("/dashboard", follow_redirects=False))

print("\n== 3. Logout, then replay the old cookie ==")
show("GET /logout", browser.get("/logout", follow_redirects=False))
attacker = TestClient(main.app, base_url=BASE)
attacker.cookies.set("session", old_cookie)
show("GET /dashboard with the saved OLD cookie", attacker.get("/dashboard", follow_redirects=False))

print("\n== 4. Idle timeout ==")
auth.IDLE_TIMEOUT_SECONDS = 3
browser = TestClient(main.app, base_url=BASE)
browser.post("/login", data=LOGIN)
show("GET /dashboard right after login", browser.get("/dashboard", follow_redirects=False))
print("... waiting 4 seconds without any request ...")
time.sleep(4)
show("GET /dashboard after 4 idle seconds", browser.get("/dashboard", follow_redirects=False))
