"""
Recall Notice Document API - HW6 (MongoDB).

Part 1: CRUD on s9275_doc.recall_notices   (routers/notices.py)
Part 2 will add /api/chat and the memory endpoints to this same app.

Run:  make run-hw06      (API on http://localhost:8275, docs at /docs)
Stop run-hw04 / run-hw05 first: they use the same port.
"""
import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
import db
from routers.notices import router as notices_router

app = FastAPI(title="Recall Notice Document API", version="6.0.0",
              description=f"DATA 260 HW6 - domain {config.DOMAIN_ID} ({config.PREFIX}), MongoDB {config.DB_NAME}")

# --- middleware ---------------------------------------------------------------

JSON_METHODS = {"POST", "PUT", "PATCH"}


@app.middleware("http")
async def require_json_body(request: Request, call_next):
    """JSON request bodies only: a POST/PUT that is not application/json gets 415.

    FastAPI then parses the JSON itself; malformed JSON is turned into a 400 by
    the validation handler below.
    """
    if request.method in JSON_METHODS:
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith("application/json"):
            return JSONResponse(status_code=415, content={
                "error": "unsupported_media_type",
                "detail": "Send the request body as JSON (Content-Type: application/json)."})
    return await call_next(request)


# No cookies are used, so any origin may call (Postman, a local HTML test page).
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])


# --- error handlers -----------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """Shorter, readable validation errors: one {field, message} per problem.

    Malformed JSON -> 400 (the body could not be read at all).
    Readable JSON that breaks the schema -> 422.
    """
    errors = [{"field": ".".join(str(p) for p in e["loc"] if p != "body") or "body",
               "message": e["msg"], "type": e["type"]}
              for e in exc.errors()]
    if any(e["type"] == "json_invalid" for e in errors):
        return JSONResponse(status_code=400, content={"error": "malformed_json", "errors": errors})
    return JSONResponse(status_code=422, content={"error": "validation_failed", "errors": errors})


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": "server_error",
                                                  "detail": "Unexpected server error."})


app.include_router(notices_router)


@app.get("/api/health")
def health():
    """Is the API up and can it reach MongoDB?"""
    try:
        db.ping()
        count = db.get_notices().estimated_document_count()
        return {"status": "ok", "database": config.DB_NAME, "notices": count}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "degraded",
                                                      "detail": "MongoDB not reachable."})


@app.get("/api/config")
def get_config():
    return {"sid4": config.SID4, "port_base": config.PORT_BASE, "prefix": config.PREFIX,
            "seed": config.SEED, "verify_seed": config.VERIFY_SEED,
            "domain_id": config.DOMAIN_ID, "database": config.DB_NAME}


if __name__ == "__main__":
    print(f"Xu Wang | DATA 260 HW6 | API on http://localhost:{config.PORT_BASE}  (docs /docs)")
    uvicorn.run(app, host="127.0.0.1", port=config.PORT_BASE)
