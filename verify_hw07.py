"""
HW7 self-check (smoke test) -> reports/hw07/verification.json

    make verify-hw07

Needs MySQL (s9275_rel) and Ollama with qwen2.5:3b. No server is started: the
JWT API is called in-process with FastAPI's TestClient. Checks behaviour and the
saved evidence, not wording:

  Part 1  three roles in MySQL, login 200/401, /auth/me 401 without / with a bad
          token, reader 403 / writer 201 on create, writer 403 / moderator 204 on
          delete, Ruff clean on the HW7 files, pre-commit hook installed
  Part 2  one live run of the error case (nonexistent ID); reliability summary
  Part 3  Reflexion summary, stored reflections carry their evidence
  Part 4  scenario CSVs >= 500 rows, UI runs decided correctly, snapshot SHA-256
          matches the saved text, csv_sql refuses writes, calculator refuses names
  Part 5  fixtures exist; with prompt+tool defenses no attack succeeded; the
          tool replay shows the attack works without the tool defense
  Part 6  safety gate: 10/10 commands decided correctly

Temporary data: one recall notice (created as writer, deleted as moderator).
"""
import csv
import hashlib
import json
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code" / "auth_app"))
sys.path.insert(0, str(ROOT / "code"))
import config  # noqa: E402

HW7 = ROOT / "reports" / "hw07"
RAW = HW7 / "raw"
BIKE = RAW / "bike"
checks = []


def check(name, ok, detail=""):
    checks.append({"name": name, "passed": bool(ok), "detail": str(detail)})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")
    return bool(ok)


def safe(name, fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        check(name, False, f"error: {type(exc).__name__}: {str(exc)[:200]}")


def git(*args):
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).rstrip("\n")
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- Part 1

def part1():
    import pymysql
    from fastapi.testclient import TestClient
    from main import app

    conn = pymysql.connect(host=config.MYSQL_HOST, port=config.MYSQL_PORT, user=config.MYSQL_USER,
                           password=config.MYSQL_PASSWORD, database=config.DB_NAME)
    with conn.cursor() as cur:
        cur.execute("SELECT username, role, LENGTH(password_hash) FROM users "
                    "WHERE username LIKE %s ORDER BY username", (f"{config.PREFIX}_%",))
        users = cur.fetchall()
    conn.close()
    check("P1 users table has reader/writer/moderator with bcrypt hashes",
          {u[1] for u in users} >= {"reader", "writer", "moderator"} and all(u[2] == 60 for u in users),
          [u[:2] for u in users])

    c = TestClient(app)
    tokens = {}
    for role in ("reader", "writer", "moderator"):
        r = c.post("/auth/login", json={"username": f"{config.PREFIX}_{role}", "password": f"{role}-9275"})
        tokens[role] = r.json().get("access_token") if r.status_code == 200 else None
        check(f"P1 login {role} -> 200 + JWT", r.status_code == 200 and tokens[role], r.status_code)
    r = c.post("/auth/login", json={"username": f"{config.PREFIX}_reader", "password": "wrong"})
    check("P1 login wrong password -> 401", r.status_code == 401, r.status_code)
    check("P1 /auth/me without token -> 401", c.get("/auth/me").status_code == 401)
    r = c.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    check("P1 /auth/me with invalid token -> 401", r.status_code == 401, r.json().get("detail"))
    h = {role: {"Authorization": f"Bearer {t}"} for role, t in tokens.items()}
    r = c.get("/auth/me", headers=h["writer"])
    check("P1 /auth/me returns identity and role", r.status_code == 200 and r.json().get("role") == "writer",
          r.json())
    check("P1 reader can list notices -> 200",
          c.get("/api/notices?page=1&page_size=3", headers=h["reader"]).status_code == 200)
    n = random.Random(config.VERIFY_SEED).randint(1000, 9999)
    body = {"product_name": "HW7 verify notice", "category": "Undeclared Allergen",
            "recall_number": f"F-{n}-2026", "units_affected": 1, "firm_id": 1}
    check("P1 reader create -> 403", c.post("/api/notices", json=body, headers=h["reader"]).status_code == 403)
    r = c.post("/api/notices", json=body, headers=h["writer"])
    created = r.status_code == 201
    check("P1 writer create -> 201", created, r.status_code)
    if created:
        nid = r.json()["id"]
        check("P1 writer delete -> 403", c.delete(f"/api/notices/{nid}", headers=h["writer"]).status_code == 403)
        check("P1 moderator delete -> 204",
              c.delete(f"/api/notices/{nid}", headers=h["moderator"]).status_code == 204)

    files = ["code/auth_app", "code/bike_app", "code/hw07_users.py", "code/file_tools.py",
             "code/test_file_tools.py", "code/agent_hw07.py", "code/hw07_tasks.py",
             "code/hw07_reliability.py", "code/reflexion_hw07.py", "code/bike_fetch_data.py",
             "code/bike_attacks.py", "verify_hw07.py"]
    r = subprocess.run(["ruff", "check", *files], cwd=ROOT, capture_output=True, text=True)
    check("P1 ruff check passes on the HW7 files", r.returncode == 0, (r.stdout or r.stderr).strip()[-120:])
    check("P1 pre-commit config + installed hook",
          (ROOT / ".pre-commit-config.yaml").exists() and (ROOT / ".git" / "hooks" / "pre-commit").exists())


# ---------------------------------------------------------------- Parts 2-3

def part2():
    from agent_hw07 import run_agent
    from hw07_tasks import ERROR_CASE, verify_error_case
    run = run_agent(ERROR_CASE["question"], on_event=None)
    v = verify_error_case(run)
    check("P2 live run: nonexistent ID -> tool says not found, agent answers", v["passed"],
          f"{run['stop_reason']}, {run['tool_calls_total']} tool call(s)")
    s = json.loads((RAW / "reliability_summary.json").read_text())
    check("P2 reliability: >= 20 attempts, rates before/after repair, failure classes",
          s["attempts"] >= 20 and s["rate_before_repair"] is not None and len(s["failures"]) == 4,
          f"{s['attempts']} attempts, {s['rate_before_repair']} -> {s['rate_after_repair']}, {s['failures']}")


def part3():
    s = json.loads((RAW / "reflexion_summary.json").read_text())
    check("P3 original vs Reflexion summary on the same tasks",
          "original" in s and "reflexion" in s and s["max_retries"] == 2,
          f"success {s['original']['task_success']} -> {s['reflexion']['task_success']}")
    refl = [json.loads(line) for line in (RAW / "reflections.jsonl").read_text().splitlines() if line]
    check("P3 stored reflections carry user, run and evidence",
          refl and all(r.get("user_id") and r.get("run_id") and r.get("evidence", {}).get("verifier")
                       for r in refl), f"{len(refl)} reflection(s)")
    stops = set(s["reflexion"]["stop_reasons"])
    check("P3 Reflexion stop reasons are from success/budget_exhausted/human_review",
          stops <= {"success", "budget_exhausted", "human_review"}, stops)


# ---------------------------------------------------------------- Part 4

def part4():
    from bike_app import tools as T
    for name in ("membership_wins", "payperuse_wins"):
        rows = sum(1 for _ in csv.DictReader((BIKE / f"{name}.csv").open()))
        check(f"P4 {name}.csv has >= 500 trip rows", rows >= 500, rows)
    expected = {"membership_wins": "Buy Monthly Membership", "payperuse_wins": "Pay Per Ride/Minute"}
    for name, want in expected.items():
        runs = sorted((BIKE / "runs").glob(f"{name}_*.json"))
        if not check(f"P4 UI run saved for {name}", runs, len(runs)):
            continue
        r = json.loads(runs[-1].read_text())
        x = r["results"]
        check(f"P4 {name}: decision {want}", x["decision"] == want,
              f"{x['decision']} ({x['decision_source']}); agent said {x.get('agent_decision')}")
        check(f"P4 {name}: weekly table + citation with capture time and SHA-256",
              x["weekly"] and x["citations"] and all(c["sha256"] and c["captured_at"] for c in x["citations"]),
              f"{len(x['weekly'])} weeks, {len(x['citations'])} citation(s), {r['steps']} steps, "
              f"{r['total_time_s']} s, {r['stop_reason']}")
        snap = x["citations"][0]
        text = (BIKE / "snapshots" / snap["snapshot"]).read_text(encoding="utf-8")
        check(f"P4 {name}: snapshot text matches its SHA-256",
              hashlib.sha256(text.encode()).hexdigest() == snap["sha256"], snap["snapshot"])
    store = T.TripStore((BIKE / "payperuse_wins.csv").read_text())
    check("P4 csv_sql refuses a write statement", not T.csv_sql("DROP TABLE trips", store)["success"])
    check("P4 calculator refuses names", not T.calculator("rides*0.19")["success"])


# ---------------------------------------------------------------- Part 5

def part5():
    check("P5 three hostile fixtures exist", len(list((HW7 / "fixtures").glob("attack*.html"))) == 3)
    s = json.loads((BIKE / "attack_summary.json").read_text())
    full = [r for r in s["rows"] if r["defenses"] == "prompt+tool"]
    check("P5 with prompt+tool defenses no attack succeeded",
          len(full) == 3 and not any(r["success"] for r in full),
          [f"{r['attack']}: {r['success']}" for r in full])
    none = [r for r in s["rows"] if r["defenses"] == "none"]
    check("P5 matrix has 3 attacks x 3 defense states", len(s["rows"]) == 9,
          f"undefended successes: {sum(r['success'] for r in none)}/3")
    rep = s.get("tool_replay", [])
    check("P5 tool replay: works without tool defense, blocked with it",
          rep and all(r["attack_worked"] == (r["defenses"] == "none") for r in rep),
          [f"{r['attack']} {r['defenses']}: {r['attack_worked']}" for r in rep])


# ---------------------------------------------------------------- Part 6

def part6():
    import file_tools as ft
    from test_file_tools import SAFETY_CASES
    right = sum(ft.confirm_bash(cmd)["allow"] == allow for cmd, allow in SAFETY_CASES)
    check("P6 safety gate decides 10/10 commands correctly", right == len(SAFETY_CASES) == 10,
          f"{right}/{len(SAFETY_CASES)}")
    check("P6 destructive command with a safe prefix is blocked",
          not ft.confirm_bash("echo x > /etc/hosts")["allow"] and not ft.confirm_bash("ls && rm -rf data")["allow"])


def main():
    print(f"{config.DEMO_NAME} | DATA 260 HW7 self-check | {datetime.now():%Y-%m-%d %H:%M:%S}")
    dirty = [line for line in (git("status", "--porcelain") or "").splitlines()
             if line[3:] and not line[3:].startswith("reports/")]
    check("Repo: no uncommitted changes outside reports/", not dirty, dirty[:5])
    for name, fn in [("P1", part1), ("P2", part2), ("P3", part3), ("P4", part4), ("P5", part5),
                     ("P6", part6)]:
        safe(name, fn)
    passed = sum(c["passed"] for c in checks)
    result = {"student": config.DEMO_NAME, "homework": "HW7", "run_at": datetime.now().isoformat(timespec="seconds"),
              "commit": git("rev-parse", "--short", "HEAD"), "passed": passed,
              "failed": len(checks) - passed, "checks": checks}
    (HW7 / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n{passed} passed, {len(checks) - passed} failed -> reports/hw07/verification.json")
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
