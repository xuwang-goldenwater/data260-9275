"""
HW7 Part 6 - one combined test run (no model, no network):

  (a) integration test: three small .py files in a temporary sandbox, one
      instruction answered by glob -> search -> read
  (b) safety gate: 5 commands that should pass, 5 that should be blocked,
      plus a few extra deny-list checks

    python code/test_file_tools.py      (make test-file-tools)

Writes reports/hw07/raw/safety_gate_results.csv and file_tools_integration.json.
Exit code 1 if any command gets the wrong decision (a false allow or false block).
"""
import csv
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import file_tools as ft  # noqa: E402

RAW = Path(__file__).resolve().parent.parent / "reports" / "hw07" / "raw"

FILES = {
    "loader.py": 'def load(path):\n    with open(path) as f:\n        return f.read()\n',
    "pricing.py": 'DEBUG = True\n\ndef price(minutes):\n    if DEBUG:\n'
                  '        print("minutes", minutes)\n    return 0.30 * minutes\n',
    "report.py": 'from pricing import price\n\nprint(price(12))\n',
}

# (command, expected allow?)
SAFETY_CASES = [
    ("ls -la", True),
    ("cat pricing.py", True),
    ("grep -n DEBUG *.py", True),
    ("wc -l loader.py report.py", True),
    ("python3 --version", True),
    ("rm -rf build", False),
    ("sudo rm /var/log/system.log", False),
    ("chmod 777 pricing.py", False),
    ("echo hacked > /etc/hosts", False),                       # safe prefix, root redirect
    ("python3 -c \"__import__('shutil').rmtree('data')\"", False),   # safe prefix, deletes via Python
]

# Extra deny-list checks: categories the 10 cases above do not cover.
EXTRA_DESTRUCTIVE = [
    "dd if=/dev/zero of=/dev/disk2 bs=1m",
    "mkfs.ext4 /dev/sdb1",
    "ls && rm -r data",
    "find . -name '*.pyc' -delete",
    "chown root:wheel loader.py",
]


def log_call(name, args, result):
    short = json.dumps(result)[:160]
    print(f"  tool call: {name}({json.dumps(args)})\n    -> {short}")


def integration_test() -> dict:
    print("\n(a) Integration test: glob -> search -> read")
    for name, body in FILES.items():
        ft.write_file(name, body)
    instruction = "Find the Python file that contains DEBUG and show its contents."
    print(f"  instruction: {instruction}")
    calls = []

    g = ft.glob_files("*.py")
    log_call("glob_files", {"pattern": "*.py"}, g)
    calls.append(("glob_files", g))

    s = ft.search_in_files("DEBUG", file_pattern="*.py")
    log_call("search_in_files", {"pattern": "DEBUG", "file_pattern": "*.py"}, s)
    calls.append(("search_in_files", s))

    target = s["hits"][0]["path"]
    r = ft.read_file(target, max_lines=20)
    log_call("read_file", {"path": target, "max_lines": 20}, r)
    calls.append(("read_file", r))

    print(f"\n  answer: {target} contains DEBUG. Contents:")
    for line in r["content"].splitlines():
        print("    | " + line)

    # The other three tools' required options, shown once each.
    head = ft.read_file("pricing.py", max_lines=2)
    print(f"\n  read_file max_lines=2 -> {head['lines']} lines, truncated={head['truncated']}")
    e = ft.edit_file("report.py", "price(12)", "price(15)")
    print("  edit_file diff:\n    " + e["diff"].replace("\n", "\n    "))
    try:
        ft.read_file("../../etc/passwd")
        escaped = "NOT BLOCKED"
    except PermissionError as exc:
        escaped = f"blocked ({exc})"
    print(f"  read_file('../../etc/passwd') -> {escaped}")

    ok = target == "pricing.py" and len(g["matches"]) == 3 and escaped.startswith("blocked")
    print(f"  integration result: {'PASS' if ok else 'FAIL'}")
    return {"instruction": instruction, "found": target, "tool_sequence": [c[0] for c in calls],
            "glob_matches": g["matches"], "search_hits": s["hits"], "passed": ok}


def safety_test() -> list[dict]:
    print("\n(b) Safety gate: 5 should pass, 5 should be blocked")
    print(f"  SAFE_PREFIXES = {ft.SAFE_PREFIXES}")
    print(f"  {'#':<3}{'command':<52}{'expect':<8}{'destr.':<8}{'decision':<9}result")
    rows = []
    for i, (cmd, expect_allow) in enumerate(SAFETY_CASES, 1):
        d = ft.confirm_bash(cmd)
        destr = ft.is_destructive(cmd)
        if d["allow"] == expect_allow:
            result = "ok"
        elif d["allow"]:
            result = "FALSE ALLOW"
        else:
            result = "FALSE BLOCK"
        rows.append({"n": i, "command": cmd, "expected": "allow" if expect_allow else "block",
                     "is_destructive": destr, "decision": "allow" if d["allow"] else "block",
                     "reason": d["reason"], "result": result})
        print(f"  {i:<3}{cmd[:50]:<52}{rows[-1]['expected']:<8}{str(destr):<8}"
              f"{rows[-1]['decision']:<9}{result}   ({d['reason']})")

    print("\n  extra is_destructive checks (should all be True):")
    for cmd in EXTRA_DESTRUCTIVE:
        print(f"    {cmd:<40} -> {ft.is_destructive(cmd)}  ({ft.destructive_reason(cmd)})")

    confirmed = ft.confirm_bash("rm -rf build", auto_approve=True)
    print(f"\n  rm -rf build with auto_approve=True -> allow={confirmed['allow']} ({confirmed['reason']})")
    blocked_run = ft.bash("rm -rf build")
    print(f"  bash('rm -rf build') -> allowed={blocked_run['allowed']}, nothing executed")
    ran = ft.bash("grep -c DEBUG pricing.py")
    print(f"  bash('grep -c DEBUG pricing.py') -> allowed={ran['allowed']}, stdout={ran['stdout'].strip()}")
    return rows


def main() -> int:
    print(f"Xu Wang | DATA 260 HW7 Part 6 - file tools + safety gate | "
          f"{datetime.now().isoformat(timespec='seconds')}")
    sandbox = ft.set_sandbox(tempfile.mkdtemp(prefix="s9275_sandbox_"))
    print(f"sandbox: {sandbox}")

    integ = integration_test()
    rows = safety_test()

    passed = sum(r["result"] == "ok" for r in rows)
    false_allows = [r for r in rows if r["result"] == "FALSE ALLOW"]
    print(f"\nSafety gate: {passed}/{len(rows)} correct, false allows = {len(false_allows)}")
    for r in false_allows:
        print(f"  FALSE ALLOW: {r['command']}")

    RAW.mkdir(parents=True, exist_ok=True)
    with open(RAW / "safety_gate_results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    (RAW / "file_tools_integration.json").write_text(json.dumps(integ, indent=2))
    print(f"wrote {RAW / 'safety_gate_results.csv'} and file_tools_integration.json")
    return 0 if passed == len(rows) and integ["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
