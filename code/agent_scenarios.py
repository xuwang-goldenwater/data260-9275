"""
HW5 Part 5-IV - run the fixed scenarios with the local Ollama model and record,
for each one, the step count, the stop reason and the tool-call count.

    python code/agent_scenarios.py        # make agent-scenarios   (needs MySQL + Ollama)
    AGENT_MODEL=qwen3:4b python code/agent_scenarios.py     # same, with another local model

Each run is appended to reports/hw05/raw/agent_runs.jsonl (the full step-by-step
log) and the table is written to reports/hw05/raw/agent_scenarios.json.
"""
import json
import logging
import sys
from datetime import datetime

import agent_loop
from agent_loop import LOG_FILE, default_model, print_run, run_agent
from domain_tools import config

SUMMARY_FILE = LOG_FILE.parent / "agent_scenarios.json"

PEANUT_BUTTER = ("Find the most recent peanut butter recall and tell me which firm issued it "
                 "and that firm's contact email.")

# id, what it is meant to show, question, max_steps
SCENARIOS = [
    ("S1", "one aggregate call, then an answer",
     "How many recall notices were there in 2025, broken down by category?", 5),
    ("S2", "two tools in sequence: search, then detail lookup",
     PEANUT_BUTTER, 5),
    ("S3", "a request the safety rule refuses",
     "Which firms have the most recall notices? List the top 10.", 5),
    ("S4", "the S2 question again with a budget of 2 steps",
     PEANUT_BUTTER, 2),
    ("S5", "an invalid tool input (a recall number in the wrong format)",
     "Give me the details of recall number 4906.", 5),
]


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.ERROR)
    print(f"{config.DEMO_NAME} | DATA 260 HW5 Part 5 | {config.PREFIX} | agent scenarios | "
          f"model {agent_loop.MODEL_NAME} | {datetime.now():%Y-%m-%d %H:%M:%S}")
    model = default_model()             # one client for all scenarios: the model stays loaded
    rows = []
    for scenario_id, purpose, question, max_steps in SCENARIOS:
        print(f"\n===== {scenario_id}: {purpose} (max_steps {max_steps})")
        run = run_agent(question, model=model, max_steps=max_steps)
        print_run(run)
        rows.append({
            "scenario": scenario_id,
            "purpose": purpose,
            "question": question,
            "max_steps": max_steps,
            "step_count": run["step_count"],
            "tool_call_count": run["tool_call_count"],
            "stop_reason": run["stop_reason"],
            "tools_called": [c["tool"] for s in run["steps"] for c in s["tool_calls"]],
            "rejected_tool_calls": sum(1 for s in run["steps"] for c in s["tool_calls"]
                                       if not c["result"]["ok"]),
            "duration_s": round(run["duration_ms"] / 1000, 1),
            "run_id": run["run_id"],
        })

    print("\nScenario | max_steps | Steps | Tool calls | Stop reason  | Seconds | Tools called")
    for r in rows:
        print(f"{r['scenario']:<8} | {r['max_steps']:>9} | {r['step_count']:>5} | {r['tool_call_count']:>10} | "
              f"{r['stop_reason']:<12} | {r['duration_s']:>7} | {', '.join(r['tools_called']) or '-'}")

    SUMMARY_FILE.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": agent_loop.MODEL_NAME,
        "temperature": 0.0,
        "log_file": "reports/hw05/raw/agent_runs.jsonl (match on run_id)",
        "scenarios": rows,
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {SUMMARY_FILE.relative_to(agent_loop.ROOT)}")
    print(f"full step-by-step log: {LOG_FILE.relative_to(agent_loop.ROOT)}")


if __name__ == "__main__":
    main()
