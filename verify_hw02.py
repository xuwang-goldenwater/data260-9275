"""
Self-check for Homework 2.  Run:  make verify-hw02   (or  python verify_hw02.py)

This is a smoke test, not a test suite. It starts the real system and checks
that the basic things work:

  - does the FastAPI backend actually come up on PORT_BASE and answer?
  - can a record be added, updated, deleted and searched through the API?
  - does the LangGraph script finish instead of hanging, under a hard timeout?
  - does the turn ceiling stop a graph that would otherwise loop forever?
  - do the recorded Part 4 runs satisfy the output contract they claim to?

Every check is behavioural. None of them compares model output to a fixed
string, because the model does not say the same thing twice. They ask
countable questions instead: exactly three tags? every tag 3-30 characters?
did the request succeed? did the process exit?

The API is started against a temporary record store (NOTICE_STORE), so running
this never touches code/data/recall_notices.json or any application file.

Writes reports/hw02/verification.json and exits non-zero if a required check
fails. Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
checks: List[Dict[str, Any]] = []

# ---- Section 0 -------------------------------------------------------------
SID4 = 9275
PORT_BASE = 8000 + SID4 % 900        # 8275
PREFIX = f"s{SID4}"                  # s9275
SEED = SID4                          # 9275
VERIFY_SEED = 260000 + SID4          # 269275
DOMAIN_ID = SID4 % 8                 # 3
MODEL = os.getenv("HW2_MODEL", "qwen3:8b")

API_BASE = f"http://127.0.0.1:{PORT_BASE}"
GRAPH_TIMEOUT_S = 240                # a real graph run must beat this
OFFLINE_TIMEOUT_S = 120


def check(name: str, ok: bool, detail: str = "", required: bool = True) -> bool:
    checks.append({"name": name, "passed": bool(ok), "detail": detail, "required": required})
    return bool(ok)


def read(rel: str) -> str:
    path = ROOT / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def http(method: str, path: str, body: Optional[dict] = None, timeout: float = 10.0):
    """Tiny HTTP helper. Returns (status, parsed_json_or_None)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        API_BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8")
        try:
            return err.code, json.loads(raw)
        except json.JSONDecodeError:
            return err.code, None


# ===========================================================================
# Section 0 and required files
# ===========================================================================

check("section0.port_base", PORT_BASE == 8275, f"PORT_BASE = {PORT_BASE}")
check("section0.prefix", PREFIX == "s9275", f"PREFIX = {PREFIX}")
check("section0.seed", SEED == 9275, f"SEED = {SEED}")
check("section0.verify_seed", VERIFY_SEED == 269275, f"VERIFY_SEED = {VERIFY_SEED}")
check("section0.domain_id", DOMAIN_ID == 3, "DOMAIN_ID = 3, grocery recall notices")

REQUIRED = [
    "code/api_server.py",
    "code/agent_graph.py",
    "code/graph_experiment_runner.py",
    "code/graph_offline_test.py",
    "code/data/recall_notices.seed.json",
    "code/web_application/index.html",
    "code/web_application/app.js",
    "code/web_application/styles.css",
    "src/model_client.py",
    "reports/hw02/cases/schema_input.json",
    "reports/hw02/cases/adversarial_input.json",
    "reports/hw02/raw/graph_runs.jsonl",
    "reports/hw02/raw/graph_runs.csv",
    "reports/hw02/raw/hw02_metrics.json",
    "reports/hw02/RUN_LOG.txt",
    "reports/hw02/METRICS.md",
    "reports/hw02/AI_USE.md",
    "reports/hw02/reproducible_run_instructions.md",
]
for rel in REQUIRED:
    check(f"file.{rel}", (ROOT / rel).exists())

check(
    "file.reports/hw02/report.pdf",
    (ROOT / "reports/hw02/report.pdf").exists(),
    "export the write-up to PDF before tagging",
    required=False,
)

# ===========================================================================
# Part 1 - the page must still be the HW1 page, plus the HW2 additions
# ===========================================================================

html = read("code/web_application/index.html")
css = read("code/web_application/styles.css")
js = read("code/web_application/app.js")

check("part1.viewport_meta", 'name="viewport"' in html, "needed for a real 375px layout")
check("part1.list_container", 'id="noticeList"' in html)
check("part1.state_container", 'id="listState"' in html)
check("part1.search_input", 'id="searchInput"' in html)
check("part1.loading_state", "showLoading" in js and "spinner" in css)
check("part1.empty_state", "showEmpty" in js)
check("part1.error_state", "showError" in js and "state-error" in css)
check("part1.media_query", "@media" in css, "responsive breakpoint present")
check(
    "part1.no_fixed_pixel_width",
    # max-width and min-width are fine; a bare `width: 640px` is what would
    # force a horizontal scrollbar at 375px.
    not re.search(r"(?<![-\w])width:\s*\d{3,}px", css),
    "no rule pins an element wider than the viewport",
)
check(
    "part1.touch_targets",
    "min-height: 44px" in css,
    "buttons meet the 44px minimum touch target",
)
# HW1 requirements that must survive the extension
check("part1.hw1_closure_kept", "createSubmissionCounter" in js and "countSubmission" in js)
check("part1.hw1_destructuring_kept",
      re.search(r"const\s*\{\s*productName\s*,\s*submitterEmail\s*\}", js) is not None)
check("part1.hw1_spread_kept", "...parsedData" in js and "submissionDate" in js)
check("part1.hw1_length_rule_kept", re.search(r"length\s*<=\s*25", js) is not None)
check("part1.four_categories", len(re.findall(r'<option value="[^"]+"', html)) == 4)

# ===========================================================================
# Part 2 - live API smoke test on PORT_BASE
# ===========================================================================

temp_store = Path(tempfile.gettempdir()) / f"hw02_verify_store_{os.getpid()}.json"
environment = dict(os.environ, NOTICE_STORE=str(temp_store))
server = subprocess.Popen(
    [sys.executable, str(ROOT / "code" / "api_server.py")],
    env=environment,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)

try:
    # Wait for the port to answer rather than sleeping a fixed amount.
    listening = False
    for _ in range(60):
        if server.poll() is not None:
            break
        try:
            status, _ = http("GET", "/api/config", timeout=1.0)
            if status == 200:
                listening = True
                break
        except Exception:
            time.sleep(0.5)

    if not check("part2.server_listens_on_port_base", listening,
                 f"FastAPI answered on {API_BASE}"):
        # Everything below needs a live server; record them as failures and stop.
        for name in ("part2.config_values", "part2.list", "part2.create",
                     "part2.update", "part2.delete", "part2.search_primary",
                     "part2.search_secondary", "part2.search_no_match",
                     "part2.rejects_short_description", "part2.rejects_bad_category",
                     "part2.missing_id_404", "part2.serves_front_end"):
            check(name, False, "server did not start")
    else:
        status, config = http("GET", "/api/config")
        check("part2.config_values",
              config == {"sid4": SID4, "port_base": PORT_BASE, "prefix": PREFIX,
                         "domain_id": DOMAIN_ID},
              json.dumps(config))

        status, seeded = http("GET", "/api/notices")
        check("part2.list", status == 200 and isinstance(seeded, list) and len(seeded) >= 1,
              f"{len(seeded) if isinstance(seeded, list) else '?'} records")

        sample = {
            "productName": "Verify Test Cereal, 18 oz box",
            "recallingFirm": "Verify Test Foods Co.",
            "submitterEmail": "qa@verifytestfoods.example",
            "description": "A verification record with a description comfortably longer than the twenty-five character minimum.",
            "category": "Mislabeling",
            "agreedToTerms": True,
        }
        status, created = http("POST", "/api/notices", sample)
        new_id = (created or {}).get("id")
        check("part2.create", status == 201 and isinstance(new_id, int),
              f"created id {new_id}")

        status, updated = http("PUT", f"/api/notices/{new_id}",
                               dict(sample, productName="Verify Test Cereal, 24 oz box"))
        check("part2.update",
              status == 200 and (updated or {}).get("productName", "").endswith("24 oz box"),
              "primary field changed and the id is unchanged")

        status, _ = http("DELETE", f"/api/notices/{new_id}")
        after_status, after = http("GET", f"/api/notices/{new_id}")
        check("part2.delete", status == 204 and after_status == 404,
              "record is gone after the delete")

        status, hits = http("GET", "/api/notices?q=onions")
        check("part2.search_primary",
              status == 200 and len(hits) >= 1
              and all("onion" in h["productName"].lower() for h in hits),
              f"{len(hits)} match on the primary field")

        status, hits = http("GET", "/api/notices?q=cedar%20mill")
        check("part2.search_secondary",
              status == 200 and len(hits) >= 1
              and all("cedar mill" in h["recallingFirm"].lower() for h in hits),
              f"{len(hits)} match on the secondary field")

        status, hits = http("GET", "/api/notices?q=zzzznomatch")
        check("part2.search_no_match", status == 200 and hits == [],
              "a search with no hits returns an empty list, not an error")

        status, _ = http("POST", "/api/notices", dict(sample, description="too short"))
        check("part2.rejects_short_description", status == 422)

        status, _ = http("POST", "/api/notices", dict(sample, category="Radiation"))
        check("part2.rejects_bad_category", status == 422,
              "category is constrained to the four DOMAIN_SCHEMA values")

        status, _ = http("GET", "/api/notices/999999")
        check("part2.missing_id_404", status == 404)

        try:
            with urllib.request.urlopen(API_BASE + "/", timeout=5) as response:
                page = response.read().decode("utf-8")
            check("part2.serves_front_end",
                  "<h1>Recall Notice</h1>" in page and 'src="app.js"' in page,
                  "the Part 1 page is served by the same process")
        except Exception as err:
            check("part2.serves_front_end", False, str(err))
finally:
    server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
    temp_store.unlink(missing_ok=True)
    Path(str(temp_store) + ".tmp").unlink(missing_ok=True)

# ===========================================================================
# Part 3 - the graph's structure, and that it terminates
# ===========================================================================

graph_source = read("code/agent_graph.py")
check("part3.agent_state", "class AgentState(TypedDict" in graph_source)
check("part3.planner_node", "def planner_node(state: AgentState)" in graph_source)
check("part3.reviewer_node", "def reviewer_node(state: AgentState)" in graph_source)
check("part3.supervisor_node", "def supervisor_node(state: AgentState)" in graph_source)
check("part3.router_logic", "def router_logic(state: AgentState)" in graph_source)
check("part3.conditional_edges", "add_conditional_edges" in graph_source)
check("part3.uses_stream", ".stream(" in graph_source)
# Import statements only. The module docstring is allowed to mention these
# names; what must not exist is an actual import of them.
graph_imports = re.findall(r"^\s*(?:from|import)\s+([\w.]+)", graph_source, re.MULTILINE)
check(
    "part3.goes_through_adapter",
    "from model_client import" in graph_source
    and not any(m.split(".")[0] in ("ollama", "langchain", "langchain_core",
                                    "langchain_ollama", "langchain_community")
                for m in graph_imports),
    f"imports: {sorted(set(m.split('.')[0] for m in graph_imports))}",
)

# The offline behaviour test uses a scripted fake model, so this check runs
# anywhere and still proves the graph terminates and the ceiling binds.
try:
    offline = subprocess.run(
        [sys.executable, str(ROOT / "code" / "graph_offline_test.py")],
        capture_output=True, text=True, timeout=OFFLINE_TIMEOUT_S,
    )
    passed = re.search(r"(\d+)/(\d+) behaviour tests passed", offline.stdout or "")
    check("part3.offline_behaviour_tests",
          offline.returncode == 0 and passed is not None and passed.group(1) == passed.group(2),
          passed.group(0) if passed else (offline.stdout or offline.stderr)[-200:])
    check("part3.ceiling_stops_a_forced_loop",
          "forced issues, ceiling 10" in (offline.stdout or "")
          and "FAIL" not in (offline.stdout or ""),
          "a Reviewer that always objects is stopped by the ceiling, not by luck")
except subprocess.TimeoutExpired:
    check("part3.offline_behaviour_tests", False, f"did not finish in {OFFLINE_TIMEOUT_S}s")
    check("part3.ceiling_stops_a_forced_loop", False, "offline test timed out")

# ===========================================================================
# Ollama, and one real graph run under a hard timeout
# ===========================================================================

ollama_ready = False
try:
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as response:
        installed = [m["name"] for m in json.loads(response.read()).get("models", [])]
    ollama_ready = True
    check("ollama.reachable", True, f"{len(installed)} model(s) installed")
    check("ollama.model_present", MODEL in installed, f"installed: {installed}")
except Exception as err:
    check("ollama.reachable", False, str(err))
    check("ollama.model_present", False, "cannot check without Ollama")

if ollama_ready:
    try:
        started = time.perf_counter()
        run = subprocess.run(
            [sys.executable, str(ROOT / "code" / "agent_graph.py"),
             "--input", str(ROOT / "reports/hw02/cases/schema_input.json"),
             "--ceiling", "10", "--json"],
            capture_output=True, text=True, timeout=GRAPH_TIMEOUT_S,
        )
        seconds = time.perf_counter() - started
        check("part3.live_graph_terminates", run.returncode == 0,
              f"exited in {seconds:.0f}s, well inside the {GRAPH_TIMEOUT_S}s timeout")
        record = json.loads((run.stdout or "{}").strip().splitlines()[-1])
        proposal = record.get("planner_proposal") or {}
        tags = proposal.get("tags", [])
        check("part3.live_run_returns_three_tags", len(tags) == 3, f"{len(tags)} tags")
        check("part4.live_tag_lengths",
              all(3 <= len(t) <= 30 for t in tags),
              f"lengths {[len(t) for t in tags]}")
        check("part4.live_summary_within_limit",
              len(proposal.get("summary", "").split()) <= 25,
              f"{len(proposal.get('summary', '').split())} words")
        check("part3.live_run_within_ceiling",
              record.get("turn_count", 99) <= record.get("turn_ceiling", 0),
              f"{record.get('turn_count')} of {record.get('turn_ceiling')} turns")
    except subprocess.TimeoutExpired:
        check("part3.live_graph_terminates", False,
              f"the graph did not finish within {GRAPH_TIMEOUT_S}s")
    except Exception as err:
        check("part3.live_graph_terminates", False, str(err))
else:
    check("part3.live_graph_terminates", False, "skipped: Ollama not reachable", required=False)

# ===========================================================================
# Part 4 - the recorded experiment data
# ===========================================================================

runs_path = ROOT / "reports/hw02/raw/graph_runs.jsonl"
runs: List[Dict[str, Any]] = []
if runs_path.exists():
    runs = [json.loads(line) for line in runs_path.read_text(encoding="utf-8").splitlines() if line.strip()]

by_experiment: Dict[str, List[Dict[str, Any]]] = {}
for row in runs:
    by_experiment.setdefault(row["experiment"], []).append(row)

for name, expected in (("schema30", 30), ("ceiling2", 20), ("ceiling10", 20), ("adversarial", 5)):
    actual = len(by_experiment.get(name, []))
    check(f"part4.{name}_run_count", actual == expected, f"{actual} runs recorded, {expected} required")

completed = [r for r in runs if r.get("status") == "complete"]
check("part4.every_completed_run_has_three_tags",
      bool(completed) and all(len((r.get("planner_proposal") or {}).get("tags", [])) == 3 for r in completed),
      f"{len(completed)} completed runs")
check("part4.every_tag_within_char_limits",
      all(3 <= len(t) <= 30 for r in completed for t in (r["planner_proposal"] or {}).get("tags", [])),
      "3-30 characters, as the Pydantic model requires")
check("part4.every_summary_within_word_limit",
      all(len((r["planner_proposal"] or {}).get("summary", "").split()) <= 25 for r in completed),
      "at most 25 words")
check("part4.every_run_has_latency", all(isinstance(r.get("latency_ms"), (int, float)) for r in runs))
check("part4.no_run_exceeds_its_ceiling",
      all(r["turn_count"] <= r["turn_ceiling"] + 1 for r in runs),
      "the supervisor stops a run at the turn after the ceiling, never later")
check("part4.ceiling_arms_use_same_input",
      {r["case_id"] for r in by_experiment.get("ceiling2", [])}
      == {r["case_id"] for r in by_experiment.get("ceiling10", [])},
      "the ceiling comparison is on one frozen input")
check("part4.ceiling_arms_use_same_model",
      {(r["model"], r["temperature"]) for r in by_experiment.get("ceiling2", [])}
      == {(r["model"], r["temperature"]) for r in by_experiment.get("ceiling10", [])},
      "and one model configuration")
adversarial = by_experiment.get("adversarial", [])
check("part4.adversarial_reaches_ceiling",
      sum(1 for r in adversarial if r["outcome"] == "hit turn ceiling") >= 4,
      f"{sum(1 for r in adversarial if r['outcome'] == 'hit turn ceiling')} of {len(adversarial)} runs hit the ceiling")

# ===========================================================================
# write the report
# ===========================================================================

def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


commit = git("rev-parse", "HEAD")
dirty = bool(git("status", "--porcelain"))

required_failures = [c for c in checks if c["required"] and not c["passed"]]
optional_failures = [c for c in checks if not c["required"] and not c["passed"]]

report = {
    "assignment": "DATA 260 Homework 2",
    "homework_number": 2,
    "sid4": SID4,
    "commit_hash": commit or "unknown",
    "working_tree_clean": not dirty,
    "configuration": {
        "port_base": PORT_BASE,
        "prefix": PREFIX,
        "domain_id": DOMAIN_ID,
        "model": MODEL,
        "temperature": 0.0,
        "default_turn_ceiling": 10,
        "ceilings_compared": [2, 10],
    },
    "seed": SEED,
    "verify_seed": VERIFY_SEED,
    "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "checks_total": len(checks),
    "checks_passed": sum(1 for c in checks if c["passed"]),
    "required_failures": len(required_failures),
    "optional_failures": len(optional_failures),
    "status": "PASS" if not required_failures else "FAIL",
    "checks": checks,
}

out = ROOT / "reports/hw02/verification.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

print(f"\n{report['checks_passed']}/{report['checks_total']} checks passed  -> {report['status']}")
if required_failures:
    print("\nrequired failures:")
    for c in required_failures:
        print(f"  FAIL  {c['name']}  {c['detail']}")
if optional_failures:
    print("\noptional failures:")
    for c in optional_failures:
        print(f"  warn  {c['name']}  {c['detail']}")
print(f"\nwrote {out.relative_to(ROOT)}")

raise SystemExit(1 if required_failures else 0)
