"""
HW5 Part 2 - run a fixed list of tool calls through the MCP Inspector and save
the machine-readable results under reports/hw05/raw/.

    python code/mcp_capture.py meals        # make capture-meals
    python code/mcp_capture.py domain       # make capture-domain

This uses the Inspector's command-line mode (`--cli`). It is the same Inspector
as the web page: it starts the server over STDIO, sends one tools/call, and
prints the JSON the server answered. The web page is for looking; this is for
keeping a file a grader can re-check.
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "reports" / "hw05" / "raw"

# name -> (server file, [(tool, arguments), ...])
SUITES = {
    "meals": ("code/meals_server.py", [
        ("search_meals_by_name", {"query": "Arrabiata"}),
        ("meals_by_ingredient", {"ingredient": "chicken", "limit": 3}),
        ("meal_details", {"id": "52771"}),
        ("random_meal", {}),
        # the cases the assignment lists under error handling
        ("search_meals_by_name", {"query": "zzzzzz"}),              # no matches -> empty result
        ("meal_details", {"id": "99999999"}),                       # unknown id  -> no matches
        ("search_meals_by_name", {"query": "Arrabiata", "limit": 99}),   # outside 1-25 -> rejected
    ]),
    # Part 2B: for each tool one successful call, then one intentionally invalid call
    "domain": ("code/domain_server.py", [
        ("search_notices", {"query": "peanut butter", "limit": 2}),
        ("search_notices", {"query": "peanut butter", "limit": 500}),     # limit outside 1-20
        ("get_notice", {"recall_number": "F-0001-2025"}),
        ("get_notice", {"recall_number": "ABC-12"}),                      # not F-NNNN-YYYY
        ("recall_summary", {"group_by": "category", "year": 2025}),
        ("recall_summary", {"group_by": "color"}),                        # not an allowed group
    ]),
}


def call(server: str, tool: str, arguments: dict) -> dict:
    """One tools/call through the Inspector CLI. Returns what was sent and what came back."""
    command = ["npx", "-y", "@modelcontextprotocol/inspector", "--cli",
               sys.executable, server, "--method", "tools/call", "--tool-name", tool]
    for key, value in arguments.items():
        command += ["--tool-arg", f"{key}={json.dumps(value)}"]

    done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
    try:
        result = json.loads(done.stdout)          # stdout carries only the JSON answer
    except ValueError:
        result = {"unparsed_stdout": done.stdout, "stderr_tail": done.stderr[-500:]}
    return {
        "tool": tool,
        "arguments": arguments,
        "is_error": bool(result.get("isError")),
        "inspector_exit_code": done.returncode,
        "result": result,
    }


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "meals"
    if name not in SUITES:
        sys.exit(f"unknown suite {name!r}; choose one of {sorted(SUITES)}")
    server, calls = SUITES[name]

    records = []
    for tool, arguments in calls:
        record = call(server, tool, arguments)
        records.append(record)
        answer = record["result"].get("structuredContent")
        if answer is None:                         # an error has text only
            content = record["result"].get("content") or [{}]
            answer = content[0].get("text", record["result"])
        if record["is_error"]:                                # the MCP layer itself reported an error
            status = "ERROR "
        elif isinstance(answer, dict) and answer.get("ok") is False:   # our envelope said no
            status = "reject"
        else:
            status = "ok    "
        print(f"{status} {tool} {json.dumps(arguments)}")
        print(f"       -> {json.dumps(answer)[:150]}")

    out_file = RAW_DIR / f"mcp_inspector_{name}.json"
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "server": server,
        "transport": "stdio",
        "client": "npx @modelcontextprotocol/inspector --cli",
        "calls": records,
    }, indent=2), encoding="utf-8")
    print(f"wrote {out_file.relative_to(ROOT)} ({len(records)} calls)")


if __name__ == "__main__":
    main()
