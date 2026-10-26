"""
HW7 Part 4-II - web UI for the Bay Wheels advisor, on PORT_BASE 8275.

    make run-bike        then open http://localhost:8275

One page: CSV upload, pricing URL, Run. POST /api/run returns the timeline
(tool calls + observations) and the results panel. Stop make run-hw07 first:
both use port 8275.
"""
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                       # code/ (for `bike_app`)
sys.path.insert(0, str(HERE.parent / "auth_app"))          # config
import config  # noqa: E402
from bike_app.agent import MODEL_NAME, run_advisor  # noqa: E402

app = FastAPI(title="Bay Wheels membership advisor", version="7.0.0")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(HERE / "index.html")


@app.get("/fixtures/{name}", include_in_schema=False)
def fixture(name: str):
    """Part 5: the local hostile pricing-page fixture is served from here."""
    path = HERE.parent.parent / "reports" / "hw07" / "fixtures" / Path(name).name
    return FileResponse(path) if path.exists() else JSONResponse({"error": "not found"}, 404)


@app.post("/api/run")
async def run(file: UploadFile = File(...), pricing_url: str = Form(...),
              prompt_defense: bool = Form(True), tool_defense: bool = Form(True)):
    text = (await file.read()).decode("utf-8", errors="replace")
    label = Path(file.filename or "upload").stem
    try:
        result = run_advisor(text, pricing_url, prompt_defense, tool_defense, label=label)
    except ValueError as exc:                               # bad CSV
        return JSONResponse({"error": str(exc)}, status_code=400)
    return result


@app.get("/api/info")
def info():
    return {"model": MODEL_NAME, "port": config.PORT_BASE, "prefix": config.PREFIX,
            "student": config.DEMO_NAME}


if __name__ == "__main__":
    print(f"{config.DEMO_NAME} | DATA 260 HW7 Part 4 | Bay Wheels advisor UI on "
          f"http://localhost:{config.PORT_BASE}")
    uvicorn.run(app, host="127.0.0.1", port=config.PORT_BASE)
