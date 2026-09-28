"""
Recall Notice API - HW4 (extends the HW3 auth app).

HW3 -> HW4 changes:
  - users and sessions move from in-memory dicts into MySQL (database s9275_rel)
  - login is email + password, JSON in / JSON out, for the React client
  - the cookie holds only an opaque token that points at a sessions row
  - recall-notice CRUD is served here (moved from HW2's JSON file into MySQL)
  - every request is timed and its SQL statements counted (Part 3)

Run:  make run-hw04      (API on http://localhost:8275, docs at /docs)
"""
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

import config
import query_counter
from database import engine
from routers.auth import router as auth_router
from routers.notices import router as notices_router

app = FastAPI(title="Recall Notice API", version="4.0.0",
              description=f"DATA 260 HW4 - domain {config.DOMAIN_ID} ({config.PREFIX})")


@app.middleware("http")
async def time_and_count(request: Request, call_next):
    """Adds X-Server-Time-Ms and X-SQL-Total to every response."""
    counter = query_counter.start_request()
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Server-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.3f}"
    response.headers["X-SQL-Total"] = str(counter.total)
    return response


# Added after the middleware above, so CORS is the outermost layer and also
# decorates 401 responses (otherwise the browser hides them from React).
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.FRONTEND_ORIGINS,
    allow_credentials=True,               # let the browser send the session cookie
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-SQL-Total", "X-SQL-List", "X-Server-Time-Ms"],
)

app.include_router(auth_router)
app.include_router(notices_router)


@app.get("/", include_in_schema=False)
def root():
    """This process is only the API; the pages live in the React app on :5173."""
    return {"service": "Recall Notice API", "docs": f"http://localhost:{config.PORT_BASE}/docs",
            "health": "/api/health", "frontend": "http://localhost:5173"}


@app.get("/api/health")
def health():
    """Unauthenticated: is the API up and can it reach MySQL?"""
    with engine.connect() as conn:
        db_name = conn.execute(text("SELECT DATABASE()")).scalar()
        version = conn.execute(text("SELECT VERSION()")).scalar()
    return {"status": "ok", "database": db_name, "mysql_version": version}


@app.get("/api/config")
def get_config():
    return {"sid4": config.SID4, "port_base": config.PORT_BASE, "prefix": config.PREFIX,
            "seed": config.SEED, "verify_seed": config.VERIFY_SEED,
            "domain_id": config.DOMAIN_ID, "database": config.DB_NAME}


if __name__ == "__main__":
    print(f"Recall Notice API on http://localhost:{config.PORT_BASE}  (database {config.DB_NAME})")
    uvicorn.run(app, host="127.0.0.1", port=config.PORT_BASE)
