"""
HW3 Part 1 - Recall Notice Desk: login / logout with sessions.

Started from the instructor's HW3 starter (main.py + routers/auth.py +
templates/). Changes from the starter:
  - runs on PORT_BASE 8275 instead of 8000
  - can be started from the repo root:  python code/auth_app/main.py

Run:  make run-auth     then open http://localhost:8275
"""
import os

import uvicorn
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from routers.auth import router as auth_router

# Section 0 values
SID4 = 9275
PORT_BASE = 8000 + SID4 % 900  # 8275

app = FastAPI(title="Recall Notice Desk")

# Secret key used to sign the session cookie
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-secret-key")

# Session cookie settings:
#   https_only=True  -> cookie gets the Secure attribute
#   same_site="lax"  -> cookie gets SameSite=lax
#   HttpOnly         -> Starlette always adds it
#   max_age=3600     -> hard upper limit of 1 hour, even for an active user.
#                       The idle timeout lives in routers/auth.py.
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    https_only=True,
    same_site="lax",
    max_age=3600,
)

app.include_router(auth_router)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT_BASE)
