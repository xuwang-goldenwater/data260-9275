"""
HW5 self-check (smoke test) -> reports/hw05/verification.json

    make verify-hw05

Needs MySQL running with the HW5 schema (`make db-init seed migrate-hw05`),
internet access for TheMealDB, and Ollama running with the local model.
Starts the API on PORT_BASE itself (or reuses one already running there) and
starts both MCP servers over STDIO. It checks behaviour, not wording:

  Part 1   schema of both tables, API on PORT_BASE, CRUD on both entities,
           the relationship query, 401 / 404 / 409 / 422, Redux + Axios client
  Part 2A  meals MCP server starts, lists 4 tools, answers a tool call
  Part 2B  domain MCP server starts, lists exactly 3 tools, a valid and an
           invalid call both come back as {ok, data, error}
  Part 3   retry policy (recover, give up, do not retry bad input, timeout);
           the 150 fault-injection calls replayed against the saved CSV
  Part 4   execute_tool returns JSON text; the offline test runner passes
  Part 5   safety rule blocks / allows; agent stops at max_steps with a mock
           model; one live run with the local model; the saved run log

Temporary data: one firm and one recall notice are created through the API
and deleted again, and one login session is created and logged out. The live
agent run is not written to the run log. No application file is modified.
"""
import asyncio
import csv
import hashlib
import json
import logging
import os
import random
import re
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import httpx
import pymysql

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code" / "auth_app"))
sys.path.insert(0, str(ROOT / "code"))
import agent_loop  # noqa: E402
import config  # noqa: E402
import retry_policy  # noqa: E402

HW5 = ROOT / "reports" / "hw05"
RAW = HW5 / "raw"
BASE = f"http://localhost:{config.PORT_BASE}"
MODEL_NAME = os.getenv("AGENT_MODEL", "qwen3:8b")
ENVELOPE_KEYS = {"ok", "data", "error"}

checks = []


def check(name, ok, detail=""):
    checks.append({"name": name, "passed": bool(ok), "detail": str(detail)})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")
    return bool(ok)


def safe(name, fn):
    """Run one group of checks; an unexpected error fails that group, not the script."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        check(name, False, f"error: {type(exc).__name__}: {str(exc).splitlines()[0][:200] if str(exc) else ''}")


def git(*args):
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).rstrip("\n")
    except Exception:  # noqa: BLE001
        return None


def query(sql, args=None):
    conn = pymysql.connect(host=config.MYSQL_HOST, port=config.MYSQL_PORT, user=config.MYSQL_USER,
                           password=config.MYSQL_PASSWORD, database=config.DB_NAME, autocommit=True)
    with conn.cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    conn.close()
    return rows


def port_open():
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", config.PORT_BASE)) == 0


def is_envelope(value):
    """The Part 2B contract: exactly ok/data/error, and they agree with each other."""
    if not isinstance(value, dict) or set(value) != ENVELOPE_KEYS:
        return False
    if value["ok"] is True:
        return value["data"] is not None and value["error"] is None
    return value["ok"] is False and value["data"] is None and isinstance(value["error"], str) and value["error"] != ""


# ---- Part 1: two entities, CRUD, relationship, Redux client ---------------------------

def part1_schema():
    def unique(table, column):
        return query("SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=%s AND "
                     "table_name=%s AND column_name=%s AND non_unique=0", (config.DB_NAME, table, column))[0][0] > 0

    firm_cols = {r[0] for r in query("SHOW COLUMNS FROM firms")}
    notice_cols = {r[0]: r for r in query("SHOW COLUMNS FROM recall_notices")}
    check("P1 firms has contact_email, created_at, updated_at",
          {"contact_email", "created_at", "updated_at"} <= firm_cols)
    check("P1 recall_notices has recall_number, units_affected, firm_id, timestamps",
          {"recall_number", "units_affected", "firm_id", "created_at", "updated_at"} <= set(notice_cols))
    check("P1 unique fields: firms.contact_email and recall_notices.recall_number",
          unique("firms", "contact_email") and unique("recall_notices", "recall_number"))
    check("P1 recall_notices.firm_id is NOT NULL", notice_cols["firm_id"][2] == "NO")
    rule = query("SELECT delete_rule FROM information_schema.referential_constraints WHERE "
                 "constraint_schema=%s AND table_name='recall_notices' AND referenced_table_name='firms'",
                 (config.DB_NAME,))
    check("P1 foreign key recall_notices -> firms with ON DELETE RESTRICT",
          rule and rule[0][0] in ("RESTRICT", "NO ACTION"), rule[0][0] if rule else "no foreign key")


def remove_temp_rows(email, number):
    """Delete what this script created, straight in MySQL (also cleans up after a crashed run)."""
    query("DELETE FROM recall_notices WHERE recall_number = %s", (number,))
    query("DELETE FROM firms WHERE contact_email = %s", (email,))


def part1_api():
    client = httpx.Client(base_url=BASE, timeout=20)
    health = client.get("/api/health").json()
    check(f"P1 API responds on PORT_BASE {config.PORT_BASE}",
          health.get("status") == "ok" and health.get("database") == config.DB_NAME, health)
    cfg = client.get("/api/config").json()
    check("P1 /api/config matches Section 0",
          (cfg["sid4"], cfg["port_base"], cfg["prefix"], cfg["seed"], cfg["verify_seed"], cfg["domain_id"])
          == (9275, 8275, "s9275", 9275, 269275, 3), cfg)
    check("P1 GET /api/firms without a session -> 401", client.get("/api/firms").status_code == 401)

    login = client.post("/api/auth/login", json={"email": config.DEMO_EMAIL, "password": config.DEMO_PASSWORD})
    check("P1 login -> 200", login.status_code == 200)

    rng = random.Random(config.VERIFY_SEED)                     # same temporary values on every run
    tag = rng.randint(1000, 9999)
    email = f"verify-hw05-{tag}@{config.PREFIX}.example.com"
    number = f"F-{tag}-2099"
    remove_temp_rows(email, number)
    try:
        firm_body = {"name": f"verify-hw05 firm {tag}", "state": "CA", "contact_email": email}
        made = client.post("/api/firms", json=firm_body)
        firm_id = made.json().get("id")
        check("P1 POST /api/firms -> 201", made.status_code == 201 and firm_id, f"id {firm_id}")
        check("P1 POST /api/firms with the same contact_email -> 409",
              client.post("/api/firms", json=firm_body).status_code == 409)
        check("P1 POST /api/firms with a bad state -> 422",
              client.post("/api/firms", json={**firm_body, "state": "California"}).status_code == 422)
        changed = client.put(f"/api/firms/{firm_id}", json={**firm_body, "state": "NV"})
        in_db = query("SELECT state FROM firms WHERE id = %s", (firm_id,))
        check("P1 PUT /api/firms/{id} -> 200 and the MySQL row changed",
              changed.status_code == 200 and in_db and in_db[0][0] == "NV")
        listed = client.get("/api/firms", params={"page_size": 5})
        check("P1 GET /api/firms (paged) -> 200", listed.status_code == 200 and len(listed.json()["items"]) == 5)

        notice_body = {"product_name": f"verify-hw05 product {tag}", "category": "Mislabeling",
                       "recall_number": number, "units_affected": 42, "firm_id": firm_id}
        made = client.post("/api/notices", json=notice_body)
        notice_id = made.json().get("id")
        check("P1 POST /api/notices -> 201", made.status_code == 201 and notice_id, f"id {notice_id}")
        check("P1 POST /api/notices with the same recall_number -> 409",
              client.post("/api/notices", json=notice_body).status_code == 409)
        check("P1 POST /api/notices with a malformed recall_number -> 422",
              client.post("/api/notices", json={**notice_body, "recall_number": "ABC-12"}).status_code == 422)
        changed = client.put(f"/api/notices/{notice_id}", json={**notice_body, "units_affected": 43})
        in_db = query("SELECT units_affected FROM recall_notices WHERE id = %s", (notice_id,))
        check("P1 PUT /api/notices/{id} -> 200 and the MySQL row changed",
              changed.status_code == 200 and in_db and in_db[0][0] == 43)

        related = client.get(f"/api/firms/{firm_id}/notices")
        numbers = [n["recall_number"] for n in related.json().get("items", [])]
        check("P1 relationship query GET /api/firms/{id}/notices returns the firm's notice",
              related.status_code == 200 and numbers == [number], numbers)
        check("P1 DELETE a firm that still has a notice -> 409",
              client.delete(f"/api/firms/{firm_id}").status_code == 409)
        gone_notice = client.delete(f"/api/notices/{notice_id}").status_code
        gone_firm = client.delete(f"/api/firms/{firm_id}").status_code
        check("P1 DELETE notice, then firm -> 204 and 204", (gone_notice, gone_firm) == (204, 204),
              (gone_notice, gone_firm))
        check("P1 GET the deleted firm and notice -> 404",
              client.get(f"/api/firms/{firm_id}").status_code == 404
              and client.get(f"/api/notices/{notice_id}").status_code == 404)
    finally:
        remove_temp_rows(email, number)
        client.post("/api/auth/logout")


def part1_frontend():
    src = ROOT / "frontend" / "src"
    deps = json.loads((ROOT / "frontend" / "package.json").read_text())["dependencies"]
    need = ["@reduxjs/toolkit", "react-redux", "axios"]
    check("P1 frontend depends on Redux Toolkit, react-redux and axios", all(d in deps for d in need))
    slice_code = (src / "features" / "notices" / "noticesSlice.js").read_text()
    thunks = re.findall(r"export const (\w+) = createAsyncThunk", slice_code)
    check("P1 notices slice has 4 async thunks (fetch, create, update, delete)", len(thunks) == 4, thunks)
    check("P1 store is created and given to the app",
          "configureStore" in (src / "store" / "store.js").read_text()
          and "<Provider" in (src / "main.jsx").read_text())


# ---- Part 2: the two MCP servers over STDIO ---------------------------------------------

async def mcp_calls(script, calls):
    """Start one MCP server as a child process, list its tools, make the calls."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = StdioServerParameters(command=sys.executable, args=[str(script)], cwd=str(ROOT),
                                   env=dict(os.environ))
    with open(os.devnull, "w") as quiet:                      # the server logs to stderr; keep it off the report
        async with stdio_client(server, errlog=quiet) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                names = sorted(tool.name for tool in (await session.list_tools()).tools)
                results = [await session.call_tool(name, arguments) for name, arguments in calls]
    return names, results


def mcp(script, calls):
    return asyncio.run(asyncio.wait_for(mcp_calls(ROOT / "code" / script, calls), timeout=90))


def result_json(result):
    """The JSON a tool returned (FastMCP sends it as text content)."""
    return json.loads(result.content[0].text)


def part2a():
    names, (found, too_many) = mcp("meals_server.py", [
        ("search_meals_by_name", {"query": "Arrabiata"}),
        ("search_meals_by_name", {"query": "Arrabiata", "limit": 99}),          # allowed: 1-25
    ])
    check("P2A meals server starts and lists its 4 tools",
          names == ["meal_details", "meals_by_ingredient", "random_meal", "search_meals_by_name"], names)
    ok = not found.isError and result_json(found).get("count", 0) >= 1
    check("P2A tool call search_meals_by_name returns at least one meal from TheMealDB", ok,
          f"count {result_json(found).get('count')}" if not found.isError else found.content[0].text[:120])
    check("P2A a call with limit outside 1-25 is rejected", too_many.isError is True)


def part2b():
    names, (good, bad) = mcp("domain_server.py", [
        ("get_notice", {"recall_number": "F-0001-2025"}),
        ("search_notices", {"query": "peanut butter", "limit": 500}),           # allowed: 1-20
    ])
    check("P2B domain server starts and lists exactly 3 tools",
          names == ["get_notice", "recall_summary", "search_notices"], names)
    good, bad = result_json(good), result_json(bad)
    check("P2B valid call -> envelope with ok true and the notice in data",
          is_envelope(good) and good["ok"] and good["data"]["recall_number"] == "F-0001-2025")
    check("P2B invalid call -> envelope with ok false, data null and an error message",
          is_envelope(bad) and bad["ok"] is False, bad)


# ---- Part 3: retry policy and fault injection ---------------------------------------------

def part3_retry():
    from retry_policy import RetriesExhausted, RetryPolicy, TransientStorageError, run_with_retry

    policy = RetryPolicy(max_attempts=3, timeout_s=2.0, base_delay_s=0.1, multiplier=2.0, max_delay_s=1.0)

    def operation(failures, error=TransientStorageError):
        left = [failures]

        def run():
            if left[0] > 0:
                left[0] -= 1
                raise error("made to fail")
            return "done"
        return run

    waits, attempts = [], []
    value = run_with_retry(operation(2), policy, sleep=waits.append, attempts=attempts)
    check("P3 two transient failures, then success on attempt 3, waits 0.1 s and 0.2 s",
          value == "done" and len(attempts) == 3 and waits == [0.1, 0.2], f"waits {waits}")

    attempts = []
    try:
        run_with_retry(operation(99), policy, sleep=lambda s: None, attempts=attempts)
        gave_up = False
    except RetriesExhausted:
        gave_up = True
    check("P3 an operation that always fails stops after 3 attempts", gave_up and len(attempts) == 3,
          f"{len(attempts)} attempts")

    attempts = []
    try:
        run_with_retry(operation(99, ValueError), policy, sleep=lambda s: None, attempts=attempts)
        raised = False
    except ValueError:
        raised = True
    check("P3 a non-transient error is not retried", raised and len(attempts) == 1, f"{len(attempts)} attempt")

    attempts, started = [], time.perf_counter()
    quick = RetryPolicy(max_attempts=2, timeout_s=0.2, base_delay_s=0.01, multiplier=2.0, max_delay_s=1.0)
    try:
        run_with_retry(lambda: time.sleep(1.0), quick, attempts=attempts)
        timed_out = False
    except RetriesExhausted:
        timed_out = True
    check("P3 a call slower than the timeout is cut off and retried",
          timed_out and len(attempts) == 2 and time.perf_counter() - started < 1.0,
          f"{len(attempts)} attempts in {time.perf_counter() - started:.2f} s")


def part3_fault_injection():
    import fault_injection as fi
    from domain_tools import MySQLRepo

    with open(RAW / "fault_injection_calls.csv", encoding="utf-8") as fh:
        saved = list(csv.DictReader(fh))
    per_rate = {}
    for row in saved:
        per_rate[row["failure_rate"]] = per_rate.get(row["failure_rate"], 0) + 1
    check("P3 raw file has 150 call records: 50 at each of 0%, 20%, 50%",
          len(saved) == 150 and per_rate == {"0.0": 50, "0.2": 50, "0.5": 50}, per_rate)

    def outcome(rows):          # per call: the attempt that succeeded, or 0 when every attempt failed
        return [int(r["attempts"]) if str(r["ok"]) == "True" else 0 for r in rows]

    predicted = [a for rate in fi.RATES for a in fi.expected_attempts(rate, config.VERIFY_SEED)]
    check(f"P3 saved outcomes equal what VERIFY_SEED {config.VERIFY_SEED} predicts", outcome(saved) == predicted)

    mysql = MySQLRepo()
    replay = [row for rate in fi.RATES for row in fi.run_rate(rate, mysql)]          # 150 real calls, no file written
    check("P3 replaying the 150 calls now gives the same outcomes as the saved file",
          outcome(replay) == outcome(saved),
          "success " + ", ".join(f"{rate:.0%}: {sum(r['ok'] for r in replay if r['failure_rate'] == rate)}/50"
                                 for rate in fi.RATES))
    signature = hashlib.sha256(json.dumps(
        [[r["failure_rate"], r["call_no"], r["attempts"], r["ok"]] for r in replay]).encode()).hexdigest()
    summary = json.loads((RAW / "fault_injection_summary.json").read_text())
    check("P3 replay signature equals the one in fault_injection_summary.json",
          signature == summary["sequence_signature_sha256"], signature[:16])


# ---- Part 4: execute_tool and the offline tests -------------------------------------------

def part4():
    from tool_entry import execute_tool

    text = execute_tool("get_notice", {"recall_number": "F-0001-2025"})
    check("P4 execute_tool returns JSON text holding an ok envelope",
          isinstance(text, str) and is_envelope(json.loads(text)) and json.loads(text)["ok"])
    for label, name, inputs in [("unknown tool", "no_such_tool", {}),
                                ("invalid input", "recall_summary", {"group_by": "color"}),
                                ("inputs that are not JSON", "get_notice", "{not json")]:
        try:
            envelope = json.loads(execute_tool(name, inputs))
            fine = is_envelope(envelope) and envelope["ok"] is False
        except Exception as exc:  # noqa: BLE001
            fine, envelope = False, repr(exc)
        check(f"P4 execute_tool with {label} -> ok false, no exception", fine)

    run = subprocess.run([sys.executable, str(ROOT / "code" / "test_tools.py")], cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    lines = run.stdout.strip().splitlines()
    total = re.match(r"(\d+)/(\d+) tests passed", lines[-1] if lines else "")
    results = [line[:4] for line in lines if line.startswith(("PASS", "FAIL"))]
    check("P4 offline test runner: every test passes, at least 6 tests, X/Y summary printed",
          run.returncode == 0 and total and total.group(1) == total.group(2) and int(total.group(2)) >= 6
          and len(results) == int(total.group(2)), lines[-1] if lines else run.stderr[-200:])


# ---- Part 5: safety rule, agent loop, run log ----------------------------------------------

def part5_offline():
    from agent_loop import MockModel, ModelReply, run_agent
    from test_tools import InMemoryRepo
    from tool_entry import execute_tool, is_safety_block

    blocked = json.loads(execute_tool("recall_summary", {"group_by": "firm"}))
    allowed = json.loads(execute_tool("recall_summary", {"group_by": "category", "year": 2025}))
    check("P5 safety rule: recall_summary grouped by firm -> ok false envelope, no exception",
          is_envelope(blocked) and blocked["ok"] is False and is_safety_block(blocked))
    check("P5 safety rule: the same tool grouped by category is allowed",
          is_envelope(allowed) and allowed["ok"] is True and not is_safety_block(allowed))

    asks_forever = MockModel([ModelReply(tool_calls=[{"name": "search_notices", "arguments": {"query": "hummus"}}])])
    with tempfile.TemporaryDirectory() as folder:                       # a throw-away log file
        log_file = Path(folder) / "agent_runs.jsonl"
        run = run_agent("verify question", model=asks_forever, repo=InMemoryRepo(), max_steps=2, log_path=log_file)
        logged = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    check("P5 agent with a mock model stops at max_steps (2 steps, 2 tool calls)",
          run["stop_reason"] == "max_steps" and run["step_count"] == 2 and run["tool_call_count"] == 2)
    call = logged[0]["steps"][0]["tool_calls"][0] if logged else {}
    check("P5 the run is logged with each step, tool, inputs, result and the stop reason",
          len(logged) == 1 and logged[0]["stop_reason"] == "max_steps" and len(logged[0]["steps"]) == 2
          and set(call) == {"tool", "inputs", "result"} and is_envelope(call["result"]))


def part5_live():
    from agent_loop import run_agent

    import ollama

    installed = [m.model for m in ollama.list().models]
    if not check(f"P5 Ollama is running and has the local model {MODEL_NAME}", MODEL_NAME in installed, installed):
        return
    print(f"       one live agent run with {MODEL_NAME}; this can take a minute ...")
    started = time.perf_counter()
    run = run_agent("Which firms have the most recall notices?", max_steps=2, log_path=None)
    check("P5 live run with the local model ends with a defined stop reason",
          run["stop_reason"] in ("completed", "safety_block", "max_steps") and 1 <= run["step_count"] <= 2,
          f"{run['stop_reason']}, {run['step_count']} step(s), {run['tool_call_count']} tool call(s), "
          f"{time.perf_counter() - started:.1f} s")


def part5_logs():
    runs = [json.loads(line) for line in (RAW / "agent_runs.jsonl").read_text(encoding="utf-8").splitlines() if line]
    by_id = {r["run_id"]: r for r in runs}
    reasons = {r["stop_reason"] for r in runs}
    check("P5 agent_runs.jsonl holds runs that ended as completed, safety_block and max_steps",
          {"completed", "safety_block", "max_steps"} <= reasons, f"{len(runs)} runs, {sorted(reasons)}")
    scenarios = json.loads((RAW / "agent_scenarios.json").read_text())["scenarios"]
    matches = [s["run_id"] in by_id
               and (by_id[s["run_id"]]["step_count"], by_id[s["run_id"]]["tool_call_count"],
                    by_id[s["run_id"]]["stop_reason"]) == (s["step_count"], s["tool_call_count"], s["stop_reason"])
               and by_id[s["run_id"]]["model"] != "mock"
               for s in scenarios]
    check("P5 at least 4 scenarios, each with step count, tool-call count and stop reason equal to its logged run",
          len(scenarios) >= 4 and all(matches), f"{len(scenarios)} scenarios")


# ---- deliverables --------------------------------------------------------------------------

def deliverables():
    for name in ["RUN_LOG.txt", "METRICS.md", "AI_USE.md", "REFLECTION.md", "TOOL_CONTRACTS.md"]:
        check(f"reports/hw05/{name} exists", (HW5 / name).exists())
    words = len((HW5 / "REFLECTION.md").read_text(encoding="utf-8").split())
    check("REFLECTION.md is 200-300 words", 200 <= words <= 300, f"{words} words")
    for name, tools in [("mcp_inspector_meals.json", 4), ("mcp_inspector_domain.json", 3)]:
        calls = json.loads((RAW / name).read_text())["calls"]
        covered = {c["tool"] for c in calls}
        check(f"raw/{name} has Inspector output for all {tools} tools", len(covered) == tools, sorted(covered))


def main():
    # Read the repository state first, before this run writes anything.
    head = git("rev-parse", "HEAD")
    tag_commit = git("rev-list", "-n", "1", "hw5")
    changed = [line[3:] for line in (git("status", "--porcelain") or "").splitlines()]
    code_changed = [path for path in changed if not path.startswith("reports/")]

    logging.disable(logging.CRITICAL)        # rejected and retried calls log to stderr; keep the report clean
    print(f"{config.DEMO_NAME} | DATA 260 HW5 | {config.PREFIX} | self-check | {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"commit {head}\n")
    check("application code has no uncommitted changes (the commit hash describes the code tested)",
          head is not None and not code_changed, code_changed or "clean outside reports/")

    server = None
    reused = port_open()
    if not reused:
        server = subprocess.Popen([sys.executable, str(ROOT / "code" / "auth_app" / "main.py")],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if port_open():
                break
            time.sleep(0.2)
    try:
        safe("P1 schema", part1_schema)
        safe("P1 API", part1_api)
        safe("P1 frontend", part1_frontend)
        safe("P2A meals MCP server", part2a)
        safe("P2B domain MCP server", part2b)
        safe("P3 retry policy", part3_retry)
        safe("P3 fault injection", part3_fault_injection)
        safe("P4 execute_tool and tests", part4)
        safe("P5 safety rule and mock agent", part5_offline)
        safe("P5 live model", part5_live)
        safe("P5 run log", part5_logs)
        safe("deliverables", deliverables)
    finally:
        if server:
            server.terminate()
            server.wait(timeout=10)

    result = {
        "homework": 5,
        "sid4": config.SID4,
        "port_base": config.PORT_BASE,
        "prefix": config.PREFIX,
        "domain_id": config.DOMAIN_ID,
        "seed": config.SEED,
        "verify_seed": config.VERIFY_SEED,
        "commit": head,
        "tag_hw5_commit": tag_commit,
        "uncommitted_files_at_start": changed,
        "model": f"{MODEL_NAME} (Ollama, temperature 0, via src/model_client.py)",
        "configuration": {
            "database": f"MySQL {config.DB_NAME}",
            "api": f"{BASE} ({'reused a running server' if reused else 'started by verify_hw05.py'})",
            "mcp_transport": "stdio",
            "retry_policy": retry_policy.DEFAULT_POLICY.describe(),
            "agent_max_steps_default": agent_loop.MAX_STEPS,
        },
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "checks": checks,
        "passed": sum(c["passed"] for c in checks),
        "failed": sum(not c["passed"] for c in checks),
        "all_passed": all(c["passed"] for c in checks),
    }
    (HW5 / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n{result['passed']} passed, {result['failed']} failed -> reports/hw05/verification.json")
    sys.exit(0 if result["all_passed"] else 1)


if __name__ == "__main__":
    main()
