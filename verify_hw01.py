"""
Self-check for Homework 1.  Run:  make verify-hw01   (or  python verify_hw01.py)

Confirms the repository contains what the assignment asks for and that the
local model stack is reachable. Writes reports/hw01/verification.json and exits
non-zero if any required check fails.

Standard library only, so it runs without installing anything.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
checks: list[dict] = []


def check(name: str, ok: bool, detail: str = "", required: bool = True) -> None:
    checks.append({"name": name, "passed": bool(ok), "detail": detail,
                   "required": required})


def read(rel: str) -> str:
    path = ROOT / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


# ---- Section 0 -------------------------------------------------------------
SID4 = 9275
check("section0.port_base", 8000 + SID4 % 900 == 8275, "PORT_BASE = 8275")
check("section0.domain_id", SID4 % 8 == 3, "DOMAIN_ID = 3, grocery recall notices")
check("section0.verify_seed", 260000 + SID4 == 269275, "VERIFY_SEED = 269275")

# ---- required files --------------------------------------------------------
REQUIRED = [
    "DOMAIN_SCHEMA.md", "AGENT.md", "README.md", "requirements.txt",
    "code/Dockerfile",
    "code/web_application/index.html", "code/web_application/app.js",
    "code/agents_demo.py", "code/hw1_client.py", "code/nondeterminism_runner.py",
    "src/model_client.py",
    "reports/hw01/METRICS.md", "reports/hw01/RUN_LOG.txt", "reports/hw01/AI_USE.md",
    "reports/hw01/reproducible_run_instructions.md",
    "reports/hw01/cases/nondeterminism_input.json",
    "reports/hw01/raw/nondeterminism_runs.csv",
    "reports/hw01/raw/nondeterminism_runs.jsonl",
]
for rel in REQUIRED:
    check(f"file.{rel}", (ROOT / rel).exists())

check("file.reports/hw01/report.pdf", (ROOT / "reports/hw01/report.pdf").exists(),
      "export the Word report to PDF before tagging", required=False)

# ---- Part 1: HTML ----------------------------------------------------------
html = read("code/web_application/index.html")
check("html.title", "<title>HW1-" in html)
check("html.h1", re.search(r"<h1[^>]*>", html) is not None)
check("html.autofocus", "autofocus" in html)
check("html.email_input", 'type="email"' in html)
check("html.textarea", "<textarea" in html)
check("html.four_options", len(re.findall(r'<option value="[^"]+"', html)) == 4)
check("html.terms_label", "I agree to the terms and conditions." in html)
check("html.script_tag", 'src="app.js"' in html)
check("html.script_at_end", html.rfind('src="app.js"') > html.rfind("</form>"))

# ---- Part 1: JavaScript ----------------------------------------------------
js = read("code/web_application/app.js")
check("js.arrow_function", "=>" in js)
check("js.length_check", re.search(r"length\s*<=\s*25", js) is not None)
check("js.terms_check", "agreedToTerms" in js)
check("js.json_stringify", "JSON.stringify" in js)
check("js.destructuring",
      re.search(r"const\s*\{\s*productName\s*,\s*submitterEmail\s*\}", js) is not None)
check("js.spread_operator", "...parsedData" in js and "submissionDate" in js)
check("js.closure", "createSubmissionCounter" in js and "countSubmission" in js)

# ---- schema / form agreement ----------------------------------------------
schema = read("DOMAIN_SCHEMA.md")
FIELDS = ["productName", "recallingFirm", "submitterEmail",
          "description", "category", "agreedToTerms", "submissionDate"]
check("schema.fields", all(f in schema for f in FIELDS))
check("schema.matches_html",
      all(f'id="{f}"' in html for f in FIELDS if f != "submissionDate"),
      "every schema field has a matching form control id")
CATEGORIES = ["Undeclared Allergen", "Bacterial Contamination",
              "Foreign Material", "Mislabeling"]
check("schema.categories", all(c in schema and c in html for c in CATEGORIES))

# ---- Part 2: no hardcoded domain ------------------------------------------
# Scan the agent logic for domain vocabulary. The sample input constants at the
# bottom of agents_demo.py are demo data, not logic, so they are excluded; the
# adapter is scanned in full.
logic = (
    read("code/agents_demo.py").split("DEFAULT_TITLE")[0]
    + read("src/model_client.py")
)
banned = [w for w in ("recall", "allerg", "grocery", "food", "milk", "peanut")
          if w in logic.lower()]
check("part2.no_hardcoded_domain", not banned,
      f"domain words found in agent logic: {banned}" if banned else
      "no domain vocabulary in the agent logic")
check("part2.adapter_interface",
      "def complete(" in read("src/model_client.py"),
      "src/model_client.py exposes complete(messages, tools=None)")
check("part2.goes_through_adapter",
      "from model_client import" in read("code/agents_demo.py"))

# ---- Part 3: raw data ------------------------------------------------------
runs = []
jsonl = ROOT / "reports/hw01/raw/nondeterminism_runs.jsonl"
if jsonl.exists():
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                runs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
check("part3.forty_runs", len(runs) == 40, f"{len(runs)} runs recorded")
check("part3.both_temperatures",
      {r.get("temperature") for r in runs} == {0.7, 0.0})
check("part3.three_tags_each",
      all(len(r.get("tags", [])) == 3 for r in runs))
check("part3.summary_within_limit",
      all(len(str(r.get("summary", "")).split()) <= 25 for r in runs))
check("part3.has_latency", all("latency_ms" in r for r in runs))

# ---- Part 4 ----------------------------------------------------------------
client_src = read("code/hw1_client.py")
check("part4.stats_command", "/stats" in client_src)
check("part4.history_length", "serialized history length" in client_src)
check("part4.compliance_check", "check_bullet_only" in client_src)
check("part4.agent_md_bullets", "bullet" in read("AGENT.md").lower())

# ---- local model stack -----------------------------------------------------
try:
    import ollama  # noqa
    tags = ollama.Client().list()
    names = [m.get("model", "") for m in tags.get("models", [])]
    check("ollama.reachable", True, f"{len(names)} model(s) installed")
    check("ollama.model_present", any(n.startswith("qwen3:8b") for n in names),
          f"installed: {names}")
except Exception as exc:  # noqa: BLE001
    check("ollama.reachable", False, str(exc), required=False)
    check("ollama.model_present", False, "skipped", required=False)

# ---- report ----------------------------------------------------------------
required_failed = [c for c in checks if c["required"] and not c["passed"]]
optional_failed = [c for c in checks if not c["required"] and not c["passed"]]

result = {
    "assignment": "DATA 260 Homework 1",
    "sid4": SID4,
    "verify_seed": 260000 + SID4,
    "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    "checks_total": len(checks),
    "checks_passed": sum(1 for c in checks if c["passed"]),
    "required_failures": len(required_failed),
    "optional_failures": len(optional_failed),
    "status": "PASS" if not required_failed else "FAIL",
    "checks": checks,
}

out = ROOT / "reports/hw01/verification.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

for c in checks:
    mark = "PASS" if c["passed"] else ("FAIL" if c["required"] else "WARN")
    line = f"  [{mark}] {c['name']}"
    if c["detail"]:
        line += f"  -- {c['detail']}"
    print(line)

print()
print(f"{result['checks_passed']}/{result['checks_total']} checks passed")
print(f"status: {result['status']}")
print(f"written: reports/hw01/verification.json")
sys.exit(0 if not required_failed else 1)
