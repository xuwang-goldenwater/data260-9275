"""
HW4 self-check (smoke test) -> reports/hw04/verification.json

    make verify-hw04

Needs MySQL running and `make db-init seed` done. Starts the API on PORT_BASE
itself (or reuses one that is already running there), then checks behaviour,
not wording:

  Part 1  React files and routes exist (Login, Home, Create/Update/DeleteRecord)
  Part 2  MySQL schema, db_session_basede26, login sets an HttpOnly cookie that
          holds only an opaque token stored in `sessions`, CRUD round trip
          persisted in MySQL, 401 without a session, logout kills the token
  Part 3  seed counts, naive vs fixed return identical data with 1+N vs 1
          list queries at 10/50/200, 180 raw rows, index present, EXPLAIN saved
  Part 4  RAG outputs exist, C refused Q5 and Q6, k-sweep has k = 1, 3, 5

Temporary data: one recall notice is created and deleted, and one extra login
session is created and logged out. No application file is modified.
"""
import ast
import csv
import json
import random
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import pymysql

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code" / "auth_app"))
import config  # noqa: E402

HW4 = ROOT / "reports" / "hw04"
RAW = HW4 / "raw"
BASE = f"http://localhost:{config.PORT_BASE}"
MODEL = "qwen3:8b (Ollama, via src/model_client.py); embeddings sentence-transformers/all-MiniLM-L6-v2"

checks = []


def check(name, ok, detail=""):
    checks.append({"name": name, "passed": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")
    return bool(ok)


def safe(name, fn):
    """Run one group of checks; an unexpected error fails that group, not the script."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        check(name, False, f"error: {type(exc).__name__}: {exc}")


def git(*args):
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return None


def db():
    return pymysql.connect(host=config.MYSQL_HOST, port=config.MYSQL_PORT, user=config.MYSQL_USER,
                           password=config.MYSQL_PASSWORD, database=config.DB_NAME, autocommit=True)


def query(sql, args=None):
    conn = db()
    with conn.cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    conn.close()
    return rows


def port_open():
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", config.PORT_BASE)) == 0


# ---- Part 1: React client ----------------------------------------------------

def part1():
    src = ROOT / "frontend" / "src"
    pages = ["Login.jsx", "Home.jsx", "CreateRecord.jsx", "UpdateRecord.jsx", "DeleteRecord.jsx"]
    missing = [p for p in pages if not (src / "pages" / p).exists()]
    check("P1 React components exist", not missing, f"missing: {missing}" if missing else ", ".join(pages))

    pkg = json.loads((ROOT / "frontend" / "package.json").read_text())
    check("P1 react-router-dom dependency", "react-router-dom" in pkg.get("dependencies", {}))

    app = (src / "App.jsx").read_text()
    routes = ['path="/"', 'path="/create"', 'path="/update"', 'path="/delete"', 'path="/login"']
    check("P1 routes / /create /update /delete /login", all(r in app for r in routes))
    check("P1 Create/Update/Delete receive handler props",
          all(p in app for p in ["onAdd={onAdd}", "onUpdate={onUpdate}", "onDelete={onDelete}"]))
    check("P1 client sends cookies (credentials: include)",
          'credentials: "include"' in (src / "api" / "client.js").read_text())


# ---- Part 2: MySQL + sessions + CRUD -------------------------------------------

def part2_schema():
    tree = ast.parse((ROOT / "code" / "auth_app" / "database.py").read_text())
    names = {t.id for node in ast.walk(tree) if isinstance(node, ast.Assign)
             for t in node.targets if isinstance(t, ast.Name)}
    check("P2 database.py defines db_session_basede26", "db_session_basede26" in names)

    tables = {r[0] for r in query("SHOW TABLES")}
    need = {"users", "sessions", "recall_notices", "firms"}
    check(f"P2 database {config.DB_NAME} has tables {sorted(need)}", need <= tables, str(sorted(tables)))

    cols = {t: {r[0] for r in query(f"SHOW COLUMNS FROM {t}")} for t in need}
    check("P2 users(id, name, email, password_hash)", {"id", "name", "email", "password_hash"} <= cols["users"])
    check("P2 sessions(id, user_id, created_at, expires_at)",
          {"id", "user_id", "created_at", "expires_at"} <= cols["sessions"])
    unique = query("SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=%s "
                   "AND table_name='users' AND column_name='email' AND non_unique=0", (config.DB_NAME,))
    check("P2 users.email is UNIQUE", unique[0][0] > 0)
    hashes = query("SELECT password_hash FROM users LIMIT 5")
    check("P2 passwords stored as bcrypt hashes", hashes and all(h[0].startswith("$2") for h in hashes))


def part2_api(state):
    client = httpx.Client(base_url=BASE, timeout=20)
    state["client"] = client

    health = client.get("/api/health").json()
    check(f"P2 API responds on PORT_BASE {config.PORT_BASE}",
          health.get("status") == "ok" and health.get("database") == config.DB_NAME, str(health))
    cfg = client.get("/api/config").json()
    check("P2 /api/config matches Section 0",
          (cfg["sid4"], cfg["port_base"], cfg["prefix"], cfg["seed"], cfg["verify_seed"], cfg["domain_id"])
          == (9275, 8275, "s9275", 9275, 269275, 3), str(cfg))

    check("P2 GET /api/notices without session -> 401", client.get("/api/notices").status_code == 401)
    bad = client.post("/api/auth/login", json={"email": config.DEMO_EMAIL, "password": "wrong-password"})
    check("P2 wrong password -> 401", bad.status_code == 401)

    r = client.post("/api/auth/login", json={"email": config.DEMO_EMAIL, "password": config.DEMO_PASSWORD})
    set_cookie = r.headers.get("set-cookie", "")
    token = client.cookies.get(config.COOKIE_NAME)
    check("P2 login -> 200 + HttpOnly cookie", r.status_code == 200 and "httponly" in set_cookie.lower(),
          set_cookie.split(";")[0][:30] + "…; " + "; ".join(set_cookie.split("; ")[1:]))
    user = r.json()
    rows = query("SELECT user_id FROM sessions WHERE id = %s", (token,))
    check("P2 cookie token is a row in sessions for this user", rows and rows[0][0] == user["id"])
    opaque = (token and len(token) >= 32 and config.DEMO_EMAIL not in token
              and user["name"] not in token and "{" not in token)
    check("P2 cookie holds only an opaque token (no user data)", opaque, f"length {len(token or '')}")
    check("P2 GET /api/auth/me with cookie -> 200", client.get("/api/auth/me").status_code == 200)
    state["token"] = token

    rng = random.Random(config.VERIFY_SEED)
    name = f"verify-hw04 product {rng.randint(100000, 999999)}"
    max_before = query("SELECT COALESCE(MAX(id), 0) FROM recall_notices")[0][0]
    created = client.post("/api/notices", json={"product_name": name, "category": "Mislabeling"})
    nid = created.json().get("id") if created.status_code == 201 else None
    check("P2 POST /api/notices -> 201 with auto-increment id",
          created.status_code == 201 and nid and nid > max_before, f"id {nid}")
    in_db = query("SELECT product_name, category FROM recall_notices WHERE id = %s", (nid,))
    check("P2 created row is in MySQL", in_db and in_db[0][0] == name)
    check("P2 GET /api/notices/{id} -> 200", client.get(f"/api/notices/{nid}").status_code == 200)
    upd = client.put(f"/api/notices/{nid}", json={"product_name": name + " (updated)",
                                                   "category": "Foreign Material"})
    in_db = query("SELECT product_name, category FROM recall_notices WHERE id = %s", (nid,))
    check("P2 PUT -> 200 and MySQL row updated", upd.status_code == 200 and in_db
          and in_db[0] == (name + " (updated)", "Foreign Material"))
    listed = client.get("/api/notices", params={"page_size": 5})
    check("P2 GET /api/notices (all, paged) -> 200", listed.status_code == 200 and listed.json()["items"])
    dele = client.delete(f"/api/notices/{nid}")
    gone = not query("SELECT 1 FROM recall_notices WHERE id = %s", (nid,))
    check("P2 DELETE -> 204, row removed from MySQL, GET -> 404",
          dele.status_code == 204 and gone and client.get(f"/api/notices/{nid}").status_code == 404)


def part2_logout(state):
    client, token = state["client"], state["token"]
    client.post("/api/auth/logout")
    replay = httpx.Client(base_url=BASE, timeout=20, cookies={config.COOKIE_NAME: token})
    check("P2 after logout the old cookie gets 401", replay.get("/api/notices").status_code == 401)
    check("P2 logout deleted the sessions row", not query("SELECT 1 FROM sessions WHERE id = %s", (token,)))


# ---- Part 3: N+1 -------------------------------------------------------------------

def part3(state):
    manifest_path = RAW / "seed_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    check("P3 seed manifest: seed 9275, 200 firms, 5000 notices",
          (manifest.get("seed"), manifest.get("firms"), manifest.get("recall_notices"))
          == (config.SEED, 200, 5000), str({k: manifest.get(k) for k in ["seed", "firms", "recall_notices"]}))
    firms = query("SELECT COUNT(*) FROM firms")[0][0]
    # A few seeded rows may have been edited or deleted through the UI for screenshots.
    linked = query("SELECT COUNT(*) FROM recall_notices WHERE id <= 5000 AND firm_id IS NOT NULL")[0][0]
    check("P3 MySQL still holds the 200 firms and the seeded notices linked to them",
          firms == 200 and linked >= 4990, f"firms {firms}, seeded notices with a firm {linked}")

    client = state["client"]
    client.post("/api/auth/login", json={"email": config.DEMO_EMAIL, "password": config.DEMO_PASSWORD})
    rng = random.Random(config.VERIFY_SEED)
    for size in [10, 50, 200]:
        page = rng.randint(1, 5000 // size)
        n = client.get("/api/notices/naive", params={"page": page, "page_size": size})
        f = client.get("/api/notices/fixed", params={"page": page, "page_size": size})
        ok = (n.status_code == 200 and f.status_code == 200
              and n.json()["items"] == f.json()["items"] and len(n.json()["items"]) == size
              and all(i["firm"] for i in n.json()["items"]))
        check(f"P3 page_size {size}: naive and fixed return identical items with firms", ok, f"page {page}")
        check(f"P3 page_size {size}: naive = 1+N list queries, fixed = 1",
              n.headers.get("X-SQL-List") == str(size + 1) and f.headers.get("X-SQL-List") == "1",
              f"naive {n.headers.get('X-SQL-List')}, fixed {f.headers.get('X-SQL-List')}")
    client.post("/api/auth/logout")

    path = RAW / "n1_requests.csv"
    if check("P3 raw N+1 file exists", path.exists(), str(path.relative_to(ROOT))):
        with open(path, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        groups = {}
        for r in rows:
            groups[(r["page_size"], r["version"])] = groups.get((r["page_size"], r["version"]), 0) + 1
        check("P3 180 measured requests = 3 sizes x 2 versions x 30",
              len(rows) == 180 and len(groups) == 6 and set(groups.values()) == {30}, str(groups))

    index = query("SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=%s AND "
                  "table_name='recall_notices' AND index_name='ix_recall_notices_recall_date'",
                  (config.DB_NAME,))[0][0]
    check("P3 index ix_recall_notices_recall_date exists", index > 0)
    ex = RAW / "explain_before_after.json"
    if check("P3 EXPLAIN before/after saved", ex.exists()):
        data = json.loads(ex.read_text())["results"]
        before = [v["explain"][0] for v in data["before"].values()]
        after = [v["explain"][0] for v in data["after"].values()]
        check("P3 EXPLAIN: no index before, index used after (at least one page size)",
              all(b["key"] is None for b in before)
              and any(a["key"] == "ix_recall_notices_recall_date" for a in after))


# ---- Part 4: RAG --------------------------------------------------------------------

def part4():
    corpus = list((ROOT / "reports" / "hw03" / "corpus").glob("*.txt"))
    check("P4 corpus has >= 5 documents", len(corpus) >= 5, f"{len(corpus)} documents")
    check("P4 rag.py exists", (ROOT / "code" / "rag.py").exists())
    answers = RAW / "rag_answers.jsonl"
    if not check("P4 rag_answers.jsonl exists", answers.exists()):
        return
    runs = [json.loads(line) for line in answers.read_text(encoding="utf-8").splitlines() if line.strip()]
    main = [r for r in runs if r["run_id"].startswith("main")]
    combos = {(r["question_id"], r["config"]) for r in main}
    check("P4 six questions x configs A/B/C", len(combos) == 18, f"{len(combos)} combinations")
    c_refused = {r["question_id"]: r["refused"] for r in main if r["config"] == "C"}
    check("P4 config C refused Q5 and Q6", c_refused.get("Q5") and c_refused.get("Q6"), str(c_refused))
    check("P4 retrieval printouts saved", (RAW / "rag_retrievals.txt").exists()
          and (RAW / "rag_retrievals.jsonl").exists())
    sweep = RAW / "rag_ksweep.json"
    ks = {r["k"] for r in json.loads(sweep.read_text())} if sweep.exists() else set()
    check("P4 top_k sweep has k = 1, 3, 5", {1, 3, 5} <= ks, str(sorted(ks)))
    check("P4 comparison and evaluation table saved",
          (RAW / "rag_comparison.md").exists() and (RAW / "rag_eval_table.md").exists())


# ---- deliverables ----------------------------------------------------------------------

def deliverables():
    for name in ["RUN_LOG.txt", "METRICS.md", "AI_USE.md"]:
        check(f"reports/hw04/{name} exists", (HW4 / name).exists())


def main():
    print(f"===== verify-hw04 {datetime.now().isoformat(timespec='seconds')} =====")
    # Record the repository state before this script (and `make`'s tee into
    # RUN_LOG.txt) touches any file, so "clean" describes the commit under test.
    head = git("rev-parse", "HEAD")
    tag_commit = git("rev-list", "-n", "1", "hw4")
    clean = git("status", "--porcelain") == ""
    server, state = None, {}
    reused = port_open()
    if not reused:
        server = subprocess.Popen([sys.executable, str(ROOT / "code" / "auth_app" / "main.py")],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if port_open():
                break
            time.sleep(0.2)
    try:
        safe("P1 React client", part1)
        safe("P2 schema", part2_schema)
        safe("P2 API", lambda: part2_api(state))
        if "token" in state:
            safe("P2 logout", lambda: part2_logout(state))
        if "client" in state:
            safe("P3 N+1", lambda: part3(state))
        safe("P4 RAG", part4)
        deliverables()
    finally:
        if server:
            server.terminate()
            server.wait(timeout=10)

    result = {
        "homework": 4,
        "sid4": config.SID4,
        "port_base": config.PORT_BASE,
        "prefix": config.PREFIX,
        "domain_id": config.DOMAIN_ID,
        "seed": config.SEED,
        "verify_seed": config.VERIFY_SEED,
        "commit": head,
        "tag_hw4_commit": tag_commit,
        "working_tree_clean_at_start": clean,
        "model": MODEL,
        "database": f"MySQL {config.DB_NAME}",
        "server": "reused already-running server" if reused else "started by verify_hw04.py",
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "checks": checks,
        "passed": sum(c["passed"] for c in checks),
        "failed": sum(not c["passed"] for c in checks),
        "all_passed": all(c["passed"] for c in checks),
    }
    (HW4 / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n{result['passed']} passed, {result['failed']} failed -> reports/hw04/verification.json")
    sys.exit(0 if result["all_passed"] else 1)


if __name__ == "__main__":
    main()
