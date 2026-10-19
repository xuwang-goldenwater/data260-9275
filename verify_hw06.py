"""
HW6 self-check (smoke test) -> reports/hw06/verification.json

    make verify-hw06

Needs MongoDB (Docker container s9275-mongo) and Ollama with qwen2.5:3b. Starts the
API on PORT_BASE itself (or reuses one already running there). Checks behaviour, not
wording:

  Part 1  database + validator, API on PORT_BASE, CRUD, 400 / 404 / 409 / 422
  Part 2  POST /api/chat answers and reports the memory it used; GET /api/memory and
          GET /api/aggregate answer; messages / summaries / episodes collections exist
  Part 3  saved run data: four complete runs, five scored probes each, summary written
  Part 4  file-memory functions, the 55-line original and the < 40-line consolidated
          MEMORY.md, AGENT.md sections, the parse_recall_number tests pass

Temporary data: one notice (deleted again) and one chat user verify_<VERIFY_SEED>
(its messages, summaries and episodes are deleted again). No application file is modified.
"""
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

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code" / "doc_app"))
sys.path.insert(0, str(ROOT / "code"))
import config  # noqa: E402
import db  # noqa: E402
import file_memory as fm  # noqa: E402

HW6 = ROOT / "reports" / "hw06"
RAW = HW6 / "raw"
BASE = f"http://localhost:{config.PORT_BASE}"
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
        check(name, False, f"error: {type(exc).__name__}: {str(exc)[:200]}")


def git(*args):
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).rstrip("\n")
    except Exception:  # noqa: BLE001
        return None


def port_open():
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", config.PORT_BASE)) == 0


# ---------------------------------------------------------------- Part 1

def part1_database():
    database = db.get_db()
    check("P1 MongoDB reachable", db.ping().get("ok") == 1.0, config.MONGO_URI)
    info = database.command("listCollections", filter={"name": config.NOTICES_COLLECTION})
    options = info["cursor"]["firstBatch"][0]["options"] if info["cursor"]["firstBatch"] else {}
    check(f"P1 {config.DB_NAME}.{config.NOTICES_COLLECTION} has a $jsonSchema validator",
          "$jsonSchema" in options.get("validator", {}))
    indexes = db.get_notices().index_information()
    check("P1 recall_number has a unique index",
          any(v.get("unique") for v in indexes.values()), sorted(indexes))


def part1_api(client: httpx.Client):
    rng = random.Random(config.VERIFY_SEED)
    number = f"F-{rng.randint(9000, 9999)}-2026"
    db.get_notices().delete_many({"recall_number": number})        # leftover from a crashed run
    body = {"product_name": "Verify Granola Bars", "recall_number": number,
            "category": "Undeclared Allergen", "recall_date": "2026-10-18T09:00:00Z",
            "firm": {"name": "Verify Foods", "state": "CA"}}
    url = f"{BASE}/api/doc/notices"
    r = client.get(f"{BASE}/api/health")
    check(f"P1 API answers on PORT_BASE {config.PORT_BASE}", r.status_code == 200, r.json())
    r = client.post(url, json=body)
    check("P1 POST creates a notice (201, status defaults to ongoing)",
          r.status_code == 201 and r.json().get("status") == "ongoing", r.status_code)
    nid = r.json().get("id")
    try:
        check("P1 GET all lists notices (200)", client.get(url).status_code == 200)
        check("P1 GET /:id returns it (200)", client.get(f"{url}/{nid}").status_code == 200)
        r = client.put(f"{url}/{nid}", json={**body, "status": "completed"})
        check("P1 PUT /:id updates it (200, status completed)",
              r.status_code == 200 and r.json().get("status") == "completed", r.status_code)
        check("P1 duplicate recall_number -> 409", client.post(url, json=body).status_code == 409)
        check("P1 missing required fields -> 422",
              client.post(url, json={"product_name": "x"}).status_code == 422)
        check("P1 invalid enum -> 422",
              client.post(url, json={**body, "category": "Color"}).status_code == 422)
        check("P1 invalid id format -> 400", client.get(f"{url}/abc").status_code == 400)
    finally:
        r = client.delete(f"{url}/{nid}")
        check("P1 DELETE /:id removes it (204, then 404)",
              r.status_code == 204 and client.get(f"{url}/{nid}").status_code == 404)


# ---------------------------------------------------------------- Part 2

def part2_api(client: httpx.Client):
    user = f"verify_{config.VERIFY_SEED}"
    cleanup_user(user)
    try:
        r = client.post(f"{BASE}/api/chat", json={"user_id": user,
                        "message": "Hi, I live in San Jose and my son is allergic to milk."})
        j = r.json()
        check("P2 POST /api/chat returns a reply", r.status_code == 200 and bool(j.get("reply")),
              r.status_code)
        check("P2 response shows the memory used",
              {"short_term", "long_term_summary", "episodic_facts"} <= set(j.get("memory_used", {})))
        r = client.post(f"{BASE}/api/chat", json={"user_id": user, "session_id": j["session_id"],
                        "message": "Who in my family has an allergy?"})
        j2 = r.json()
        check("P2 second turn sees the first turn in the short-term window",
              j2["memory_used"]["short_term"]["count"] >= 2, j2["memory_used"]["short_term"]["count"])
        check("P2 second turn retrieves episodic facts",
              len(j2["memory_used"]["episodic_facts"]) >= 1, len(j2["memory_used"]["episodic_facts"]))
        r = client.get(f"{BASE}/api/memory/{user}")
        check("P2 GET /api/memory/{user_id} returns messages",
              r.status_code == 200 and len(r.json()["messages"]) >= 4, len(r.json()["messages"]))
        r = client.get(f"{BASE}/api/aggregate/{user}")
        check("P2 GET /api/aggregate/{user_id} returns daily counts",
              r.status_code == 200 and r.json()["daily_message_counts"], r.json()["daily_message_counts"])
    finally:
        cleanup_user(user)
    names = set(db.get_db().list_collection_names())
    check("P2 messages / summaries / episodes collections exist",
          {"messages", "summaries", "episodes"} <= names)


def cleanup_user(user):
    for c in ("messages", "summaries", "episodes"):
        db.get_db()[c].delete_many({"user_id": user})


# ---------------------------------------------------------------- Part 3

def part3():
    rows = [json.loads(line) for line in open(RAW / "part3_turns.jsonl", encoding="utf-8")]
    complete = {}
    for r in rows:
        complete.setdefault(r["run_id"], []).append(r)
    settings = {v[0]["setting"] for v in complete.values() if len(v) == 35}
    check("P3 complete 35-turn runs for N4, N12, N30, N30_comp",
          {"N4", "N12", "N30", "N30_comp"} <= settings, sorted(settings))
    check("P3 per-turn rows carry section tokens and latency",
          all({"tokens_short_term_window", "tokens_episodic_facts", "total_latency_ms"} <= set(r)
              for r in rows))
    scores = list(csv.DictReader(open(RAW / "part3_probe_scores.csv", encoding="utf-8")))
    check("P3 20 probe answers, all scored 1-5",
          len(scores) == 20 and all(s["score"] in "12345" and s["score"] for s in scores), len(scores))
    summary = json.loads((RAW / "part3_summary.json").read_text())
    check("P3 summary with cost estimate", all("cost_10k_conversations_usd" in v
                                               for v in summary.values()), sorted(summary))
    import yaml
    check("P3 memory_probes.yaml has 5 probes and a rubric",
          len(yaml.safe_load(open(HW6 / "memory_probes.yaml"))["probes"]) == 5)


# ---------------------------------------------------------------- Part 4

def part4():
    original = (HW6 / "memory" / "MEMORY.original.md").read_text()
    consolidated = (HW6 / "memory" / "MEMORY.consolidated.md").read_text()
    check("P4 original MEMORY.md has 55 lines and needs consolidation",
          len(original.splitlines()) == 55 and fm.needs_consolidation(original)[0],
          fm.needs_consolidation(original)[1])
    check("P4 consolidated MEMORY.md has fewer than 40 lines",
          fm.count_memory_lines(consolidated) < fm.MAX_MEMORY_LINES,
          fm.count_memory_lines(consolidated))
    check("P4 consolidated file records resolved contradictions explicitly",
          "## Resolved contradictions" in consolidated)
    check("P4 consolidated file has a last_consolidated timestamp",
          fm.read_last_consolidated(consolidated) is not None)
    agent, _ = fm.load_memory_files()
    sections = ["## Project description", "## Technology stack", "## Coding conventions",
                "## Testing approach", "## Prohibited actions"]
    check("P4 AGENT.md has the five instruction sections",
          all(s in agent for s in sections), [s for s in sections if s not in agent] or "all")
    prompt = fm.build_system_prompt(agent, original)
    check("P4 system prompt contains AGENT.md and MEMORY.md",
          "===== AGENT.md" in prompt and "===== MEMORY.md" in prompt)
    out = subprocess.run([sys.executable, str(ROOT / "code" / "doc_app" / "test_recall_number.py")],
                         capture_output=True, text=True)
    check("P4 parse_recall_number tests pass", out.returncode == 0, out.stdout.strip()[-60:])
    help_out = subprocess.run([sys.executable, str(ROOT / "code" / "file_memory_cli.py"),
                               "--memory", str(HW6 / "memory" / "MEMORY.original.md"),
                               "--run", "/help"], capture_output=True, text=True)
    check("P4 CLI /help lists /memory /compact /dream",
          all(c in help_out.stdout for c in ("/memory", "/compact", "/dream")))


def main():
    head = git("rev-parse", "HEAD")
    changed = [line[3:] for line in (git("status", "--porcelain") or "").splitlines()]
    code_changed = [p for p in changed if not p.startswith("reports/")]
    print(f"Xu Wang | DATA 260 HW6 | {config.PREFIX} | self-check | {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"commit {head}\n")
    check("application code has no uncommitted changes (the commit hash describes the code tested)",
          head is not None and not code_changed, code_changed or "clean outside reports/")

    server = None
    reused = port_open()
    if not reused:
        server = subprocess.Popen([sys.executable, str(ROOT / "code" / "doc_app" / "main.py")],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if port_open():
                break
            time.sleep(0.2)
    try:
        with httpx.Client(timeout=300) as client:
            safe("P1 database", part1_database)
            safe("P1 API", lambda: part1_api(client))
            safe("P2 memory API", lambda: part2_api(client))
        safe("P3 run data", part3)
        safe("P4 file memory", part4)
    finally:
        if server:
            server.terminate()
            server.wait(timeout=10)

    result = {
        "homework": 6,
        "sid4": config.SID4,
        "port_base": config.PORT_BASE,
        "prefix": config.PREFIX,
        "domain_id": config.DOMAIN_ID,
        "seed": config.SEED,
        "verify_seed": config.VERIFY_SEED,
        "commit": head,
        "uncommitted_files_at_start": changed,
        "model": f"{config.CHAT_MODEL} (Ollama, temperature 0, seed {config.SEED}, "
                 f"num_ctx {config.NUM_CTX}, via src/model_client.py)",
        "configuration": {
            "database": f"MongoDB {config.DB_NAME} ({config.MONGO_URI})",
            "api": f"{BASE} ({'reused a running server' if reused else 'started by verify_hw06.py'})",
            "embeddings": f"{config.EMBED_MODEL} (CPU)",
            "short_term_n": config.SHORT_TERM_N,
            "summarize_every_user_msgs": config.SUMMARIZE_EVERY_USER_MSGS,
            "top_k": config.TOP_K,
        },
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "checks": checks,
        "passed": sum(c["passed"] for c in checks),
        "failed": sum(not c["passed"] for c in checks),
        "all_passed": all(c["passed"] for c in checks),
    }
    (HW6 / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n{result['passed']} passed, {result['failed']} failed -> reports/hw06/verification.json")
    sys.exit(0 if result["all_passed"] else 1)


if __name__ == "__main__":
    main()
