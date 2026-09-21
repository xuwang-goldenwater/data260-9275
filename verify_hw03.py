"""
Self-check for Homework 3.  Run:  make verify-hw03   (or  python verify_hw03.py)

A smoke test, not a test suite. It does not download anything and does not
load the embedding model. It checks:

Part 1 (auth app, run in-process with FastAPI TestClient)
  - app is configured for PORT_BASE 8275
  - home page renders; wrong password -> 401 + Bootstrap alert
  - login sets a cookie with HttpOnly, Secure and SameSite
  - /dashboard works while logged in
  - after logout, the OLD cookie no longer reaches /dashboard
  - after the idle timeout, the cookie no longer reaches /dashboard

Part 2 (retrieval comparison)
  - every corpus file matches its SHA-256 in CORPUS_MANIFEST.json; total >= 200 KB
  - questions.yaml has 5+ questions, every expected_source exists, 2+ single-source
  - raw/ has 3 techniques x every question x k rows, and chunk stats for all 3
  - VERIFY_SEED picks random raw rows; each preview must really be in its source file
  - git: questions.yaml was committed before the retrieval results
  - the summary table can be recomputed from raw/

Writes reports/hw03/verification.json and exits non-zero if a required check fails.
"""
import hashlib
import json
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HW3 = ROOT / "reports" / "hw03"
sys.path.insert(0, str(ROOT / "code"))
sys.path.insert(0, str(ROOT / "code" / "auth_app"))

# ---- Section 0 -------------------------------------------------------------
SID4 = 9275
PORT_BASE = 8000 + SID4 % 900        # 8275
PREFIX = f"s{SID4}"                  # s9275
SEED = SID4                          # 9275
VERIFY_SEED = 260000 + SID4          # 269275
DOMAIN_ID = SID4 % 8                 # 3

checks = []


def check(name, ok, detail="", required=True):
    checks.append({"name": name, "passed": bool(ok), "detail": detail, "required": required})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")
    return bool(ok)


def clean(text):
    return " ".join(text.split())


# ---- Part 1 ----------------------------------------------------------------
def check_part1():
    from fastapi.testclient import TestClient
    import main
    from routers import auth

    check("auth app uses PORT_BASE", main.PORT_BASE == PORT_BASE, f"PORT_BASE={main.PORT_BASE}")

    base = "https://testserver"
    login = {"username": "admin", "password": "password"}
    client = TestClient(main.app, base_url=base)

    r = client.get("/")
    check("home page renders", r.status_code == 200 and "Recall Notice Desk" in r.text)

    r = client.post("/login", data={"username": "admin", "password": "wrong"})
    check("wrong password shows a Bootstrap alert", r.status_code == 401 and "alert-danger" in r.text,
          f"status={r.status_code}")

    r = client.post("/login", data=login, follow_redirects=False)
    cookie_header = r.headers.get("set-cookie", "").lower()
    check("login redirects to /dashboard", r.status_code == 302 and r.headers.get("location") == "/dashboard")
    check("session cookie is HttpOnly, Secure, SameSite",
          all(flag in cookie_header for flag in ("httponly", "secure", "samesite=lax")),
          r.headers.get("set-cookie", "")[-60:])
    old_cookie = r.cookies.get("session")

    r = client.get("/dashboard", follow_redirects=False)
    check("dashboard works while logged in", r.status_code == 200 and "Welcome" in r.text)

    client.get("/logout")
    replay = TestClient(main.app, base_url=base)
    replay.cookies.set("session", old_cookie)
    r = replay.get("/dashboard", follow_redirects=False)
    check("old cookie is rejected after logout", r.status_code == 302 and "/login" in r.headers.get("location", ""),
          f"status={r.status_code} location={r.headers.get('location')}")

    saved = auth.IDLE_TIMEOUT_SECONDS
    auth.IDLE_TIMEOUT_SECONDS = 1
    client = TestClient(main.app, base_url=base)
    client.post("/login", data=login)
    time.sleep(1.5)
    r = client.get("/dashboard", follow_redirects=False)
    auth.IDLE_TIMEOUT_SECONDS = saved
    check("idle session is rejected", r.status_code == 302 and "/login" in r.headers.get("location", ""),
          f"status={r.status_code} location={r.headers.get('location')}")


# ---- Part 2 ----------------------------------------------------------------
def check_corpus():
    manifest = json.loads((HW3 / "CORPUS_MANIFEST.json").read_text(encoding="utf-8"))
    bad = []
    for f in manifest["files"]:
        path = HW3 / f["file"]
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != f["sha256"]:
            bad.append(f["file"])
    total = sum(f["bytes"] for f in manifest["files"])
    check("corpus files match CORPUS_MANIFEST.json hashes", not bad,
          f"{len(manifest['files'])} files" + (f", mismatched: {bad[:3]}" if bad else ""))
    check("corpus is at least 200 KB", total >= 200_000, f"{total:,} bytes")
    check("SOURCES.md exists", (HW3 / "SOURCES.md").exists())


def check_questions():
    import yaml
    questions = yaml.safe_load((HW3 / "questions.yaml").read_text(encoding="utf-8"))["questions"]
    missing = [q["id"] for q in questions if not (HW3 / "corpus" / q["expected_source"]).exists()]
    complete = all(q.get("question") and q.get("expected_answer") for q in questions)
    single = sum(1 for q in questions if q.get("single_source"))
    check("questions.yaml has 5+ complete questions", len(questions) >= 5 and complete, f"{len(questions)} questions")
    check("every expected_source is a corpus file", not missing, f"missing: {missing}" if missing else "")
    check("2+ questions depend on a single source document", single >= 2, f"{single} single-source")
    return questions


def check_raw(questions):
    rows = [json.loads(line) for line in open(HW3 / "raw" / "retrievals.jsonl", encoding="utf-8")]
    stats = json.loads((HW3 / "raw" / "chunk_stats.json").read_text(encoding="utf-8"))
    techniques = {"token", "semantic", "sentence_window"}
    k = rows[0]["k"]
    expected_rows = len(techniques) * len(questions) * k
    check("retrievals.jsonl covers 3 techniques x all questions x k", len(rows) == expected_rows
          and {r["technique"] for r in rows} == techniques, f"{len(rows)} rows, expected {expected_rows}")
    check("chunk_stats.json has all 3 techniques", {s["technique"] for s in stats} == techniques)

    gap = max(abs(r["store_score"] - r["cosine_sim"]) for r in rows)
    check("store_score agrees with recomputed cosine", gap < 1e-3, f"max gap {gap:.6f}", required=False)

    # VERIFY_SEED: spot-check random rows against the corpus text
    rng = random.Random(VERIFY_SEED)
    sample = rng.sample(rows, 5)
    not_found = []
    for r in sample:
        source = clean((HW3 / "corpus" / r["source_file"]).read_text(encoding="utf-8"))
        if clean(r["preview"])[:120] not in source:
            not_found.append(f"{r['technique']}/{r['question_id']}/rank{r['rank']}")
    check("random raw rows (VERIFY_SEED) really come from their source file", not not_found,
          f"checked {len(sample)}" + (f", not found: {not_found}" if not_found else ""))


def git_first_commit_time(rel_path):
    out = subprocess.run(["git", "log", "--format=%ct", "--", rel_path], cwd=ROOT,
                         capture_output=True, text=True).stdout.split()
    return int(out[-1]) if out else None


def git_last_commit_time(rel_path):
    out = subprocess.run(["git", "log", "-1", "--format=%ct", "--", rel_path], cwd=ROOT,
                         capture_output=True, text=True).stdout.split()
    return int(out[0]) if out else None


def check_commit_order():
    q_first = git_first_commit_time("reports/hw03/questions.yaml")
    q_last = git_last_commit_time("reports/hw03/questions.yaml")
    r_first = git_first_commit_time("reports/hw03/raw/retrievals.jsonl")
    if q_first is None:
        check("questions.yaml committed before the retrieval results", False, "questions.yaml is not committed yet")
    elif r_first is None:
        check("questions.yaml committed before the retrieval results", True,
              "questions.yaml committed; retrieval results not committed yet")
    else:
        ok = q_first < r_first and q_last <= r_first
        check("questions.yaml committed before the retrieval results", ok,
              f"questions first/last commit {q_first}/{q_last}, results first commit {r_first}")


def check_summary():
    import rag_summary
    rows, stats, _ = rag_summary.load_data()
    table, _ = rag_summary.summary_table(rows, stats)
    metrics = (HW3 / "METRICS.md").read_text(encoding="utf-8") if (HW3 / "METRICS.md").exists() else ""
    check("summary table recomputes from raw/", len(table) == 3, f"{len(table)} techniques")
    check("METRICS.md contains the generated table", rag_summary.BEGIN in metrics)


def run(name, fn, *args):
    try:
        return fn(*args)
    except Exception as err:
        check(name, False, f"{type(err).__name__}: {err}")


if __name__ == "__main__":
    print(f"HW3 verification  SID4={SID4} PORT_BASE={PORT_BASE} DOMAIN_ID={DOMAIN_ID} VERIFY_SEED={VERIFY_SEED}\n")
    run("Part 1 auth app", check_part1)
    run("corpus", check_corpus)
    questions = run("questions.yaml", check_questions)
    if questions:
        run("raw retrieval output", check_raw, questions)
    run("git commit order", check_commit_order)
    run("summary", check_summary)

    failed = [c for c in checks if c["required"] and not c["passed"]]
    result = {
        "homework": "hw03",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": {"SID4": SID4, "PORT_BASE": PORT_BASE, "PREFIX": PREFIX, "SEED": SEED,
                   "VERIFY_SEED": VERIFY_SEED, "DOMAIN_ID": DOMAIN_ID},
        "passed": not failed,
        "n_checks": len(checks),
        "n_failed_required": len(failed),
        "checks": checks,
    }
    (HW3 / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed -> reports/hw03/verification.json")
    sys.exit(1 if failed else 0)
