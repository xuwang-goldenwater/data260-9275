"""
HW7 Part 2 - the hand-written agent loop, with a repair path.

    python code/agent_hw07.py A            # fixed task A (also B, C, error)
    python code/agent_hw07.py "any question about recall notices"

Same idea as HW5's agent_loop.py (kept unchanged at tag hw5): the model asks for
tools, the loop runs them through execute_tool() and appends each result as a
role "tool" message, until the model answers in text or a hard ceiling is hit.

New in HW7 - every model tool call is checked BEFORE it runs:
    unknown tool name             -> failure "unknown_tool"
    arguments not a JSON object,
    or schema validation fails    -> failure "malformed_arguments"
    text answer before any tool   -> failure "text_when_tool_required"
A failed call is not executed. The loop reprompts once with the specific
problem; after MAX_REPAIRS failed repairs it stops cleanly ("repair_failed").

Every tool invocation is logged (name + inputs) and the run ends with the total
number of tool calls. Stop reasons:
    completed | repair_failed | max_iterations | budget_exhausted | model_error
(budget_exhausted is used by the Part 3 Reflexion loop, which passes a budget.)
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from agent_loop import tool_specs                 # HW5: the three tools in Ollama's format
from domain_tools import INPUT_MODELS, check_inputs, config
from tool_entry import execute_tool

ROOT = Path(__file__).resolve().parent.parent

MODEL_NAME = os.getenv("AGENT_MODEL", "qwen2.5:3b")
TEMPERATURE = float(os.getenv("AGENT_TEMPERATURE", "0"))
MAX_ITERATIONS = 6          # hard ceiling on model turns
MAX_REPAIRS = 2             # failed calls the loop will try to repair before giving up

SYSTEM_PROMPT = """You are the recall-notice assistant for a grocery supply database.
You must use the tools to answer; never answer from memory and never invent recall
numbers, firms, emails or figures. Call the tools one step at a time and use what
each tool returns to decide the next call.

Tools:
- search_notices(query, category?, limit?): find notices whose product name contains query.
- get_notice(recall_number): all details of one notice, including the firm and its
  contact email. Recall numbers look like F-0123-2025.
- recall_summary(group_by, year?): counts per category, state or year.

Multi-step rule: a search result is only a summary. When the user asks for details,
a firm's contact email, or a comparison of notices, call get_notice for EACH of those
notices (one call per recall number) before you answer. Do not answer from search
results alone, and do not stop after the first tool call if the question has more steps.

Every tool returns JSON {"ok": ..., "data": ..., "error": ...}. If ok is false, read
the error: fix your arguments, or tell the user what the error says.
When you have everything the user asked for, answer in plain text."""


def classify_call(name: str, arguments: Any) -> Optional[tuple[str, str]]:
    """(failure_type, problem) for a call that must not run, or None if it is well-formed."""
    if name not in INPUT_MODELS:
        return "unknown_tool", (f"there is no tool named {name!r}. "
                                f"Available tools: {', '.join(INPUT_MODELS)}.")
    _, error = check_inputs(name, arguments)        # HW5 Pydantic models (extra=forbid)
    if error:
        return "malformed_arguments", f"the arguments for {name} are invalid: {error}."
    return None


def add_failure(run: dict, pending: Optional[int], failure: dict) -> int:
    """Record a failed call. A failure during a repair turn belongs to the same
    "slot" as the failure it was trying to fix; returns the new failure's index."""
    failure["slot"] = run["failures"][pending]["slot"] if pending is not None else len(run["failures"])
    failure["repaired"] = False
    run["failures"].append(failure)
    return len(run["failures"]) - 1


def default_model(temperature: float = TEMPERATURE, seed: Optional[int] = None):
    sys.path.insert(0, str(ROOT / "src"))
    from model_client import ModelClient            # HW1 adapter, src/model_client.py
    options = {"num_ctx": 8192}
    if seed is not None:
        options["seed"] = seed
    return ModelClient(model=MODEL_NAME, temperature=temperature, options=options)


def run_agent(user_input: str, model: Any = None, repo: Any = None,
              max_iterations: int = MAX_ITERATIONS, max_repairs: int = MAX_REPAIRS,
              require_tool: bool = True, extra_context: Optional[str] = None,
              budget: Optional[dict] = None,
              on_event: Optional[Callable[[str], None]] = print) -> dict:
    """Answer one question with tool calls. Returns the full run record.

    extra_context  Part 3: a reflection, added as a separate, labelled user
                   message (never into the system prompt)
    budget         Part 3: {"max_tool_calls": int, "max_tokens": int}
    on_event       where tool-invocation log lines go (print, or None for silent)
    """
    model = model if model is not None else default_model()
    say = on_event or (lambda _line: None)
    tools = tool_specs()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if extra_context:
        messages.append({"role": "user", "content": extra_context})
    messages.append({"role": "user", "content": user_input})

    run = {"run_id": uuid.uuid4().hex[:8], "started_at": datetime.now().isoformat(timespec="seconds"),
           "user_input": user_input, "model": getattr(model, "model", type(model).__name__),
           "temperature": getattr(model, "temperature", None),
           "seed": getattr(model, "options", {}).get("seed") if hasattr(model, "options") else None,
           "turns": [], "calls": [], "failures": []}
    started = time.perf_counter()
    tokens = 0
    executed = 0                # well-formed calls that actually ran
    repairs_used = 0
    pending_repair = None       # failure index waiting to be fixed by the next turn
    stop_reason, final_answer = "max_iterations", ""

    for iteration in range(1, max_iterations + 1):
        t0 = time.perf_counter()
        try:
            reply = model.complete(messages, tools=tools)
        except Exception as exc:                                    # Ollama down, model missing
            stop_reason, final_answer = "model_error", f"model call failed: {type(exc).__name__}: {exc}"
            break
        used = (getattr(reply, "input_tokens", 0) or 0) + (getattr(reply, "output_tokens", 0) or 0)
        tokens += used
        is_repair_turn = pending_repair is not None
        run["turns"].append({"iteration": iteration, "model_ms": round((time.perf_counter() - t0) * 1000),
                             "tokens": used, "text": reply.text, "repair_turn": is_repair_turn,
                             "tool_calls": [c["name"] for c in reply.tool_calls]})

        # ---- text reply ---------------------------------------------------------------
        if not reply.tool_calls:
            if require_tool and executed == 0:
                problem = ("you answered in text, but this question needs the tools. "
                           "Call one of: " + ", ".join(INPUT_MODELS) + ".")
                failed_at = add_failure(run, pending_repair, {"iteration": iteration,
                                        "type": "text_when_tool_required", "problem": problem})
                say(f"  [{iteration}] FAILURE text_when_tool_required")
                if repairs_used >= max_repairs:
                    stop_reason, final_answer = "repair_failed", reply.text
                    break
                repairs_used += 1
                pending_repair = failed_at
                messages.append({"role": "assistant", "content": reply.text})
                messages.append({"role": "user", "content": f"Your reply was rejected: {problem} Try again."})
                say(f"  [{iteration}] repair prompt sent ({repairs_used}/{max_repairs})")
                continue
            stop_reason, final_answer = "completed", reply.text.strip()
            break

        # ---- tool calls ---------------------------------------------------------------
        messages.append({"role": "assistant", "content": reply.text,
                         "tool_calls": [{"function": {"name": c["name"], "arguments": c["arguments"]}}
                                        for c in reply.tool_calls]})
        turn_failed = False
        failed_at = None
        for call in reply.tool_calls:
            name, args = call["name"], call["arguments"]
            bad = classify_call(name, args)
            record = {"iteration": iteration, "tool": name, "inputs": args,
                      "well_formed": bad is None, "failure_type": bad[0] if bad else None,
                      "repair_turn": is_repair_turn}
            if bad:
                turn_failed = True
                failed_at = add_failure(run, pending_repair if failed_at is None else failed_at,
                                        {"iteration": iteration, "type": bad[0], "problem": bad[1],
                                         "tool": name, "inputs": args})
                say(f"  [{iteration}] tool call: {name}({json.dumps(args)}) -> FAILURE {bad[0]}")
                result_text = json.dumps({"ok": False, "data": None,
                                          "error": f"call rejected, not executed: {bad[1]} "
                                                   f"Fix the call and try again."})
            else:
                result_text = execute_tool(name, args, repo=repo)
                executed += 1
                envelope = json.loads(result_text)
                outcome = "ok" if envelope["ok"] else f"ok false - {envelope['error']}"
                say(f"  [{iteration}] tool call: {name}({json.dumps(args)}) -> {outcome}")
                record["result"] = envelope
            run["calls"].append(record)
            messages.append({"role": "tool", "tool_name": name, "content": result_text})

        if pending_repair is not None and not turn_failed:          # the retry worked
            slot = run["failures"][pending_repair]["slot"]
            for f in run["failures"]:
                if f["slot"] == slot:
                    f["repaired"] = True
            pending_repair = None
        if turn_failed:
            if repairs_used >= max_repairs:
                stop_reason = "repair_failed"
                final_answer = "Stopped: the model kept making invalid tool calls."
                break
            repairs_used += 1
            pending_repair = failed_at
            say(f"  [{iteration}] repair prompt sent ({repairs_used}/{max_repairs})")

        if budget and (executed >= budget.get("max_tool_calls", 10**9)
                       or tokens >= budget.get("max_tokens", 10**9)):
            stop_reason = "budget_exhausted"
            final_answer = "Stopped: tool-call or token budget used up."
            break
    else:
        final_answer = f"Stopped after {max_iterations} model turns without a final answer."

    run.update({"stop_reason": stop_reason, "final_answer": final_answer,
                "tool_calls_total": len(run["calls"]), "tool_calls_executed": executed,
                "repairs_used": repairs_used, "tokens": tokens,
                "latency_ms": round((time.perf_counter() - started) * 1000)})
    say(f"  stop reason: {stop_reason} | turns: {len(run['turns'])} | "
        f"total tool calls: {len(run['calls'])} (executed {executed}) | "
        f"repairs: {repairs_used} | tokens: {tokens} | {run['latency_ms'] / 1000:.1f} s")
    return run


if __name__ == "__main__":
    from hw07_tasks import ERROR_CASE, TASKS
    if len(sys.argv) < 2:
        sys.exit('usage: python code/agent_hw07.py A|B|C|error|"question"')
    key = sys.argv[1]
    question = TASKS[key]["question"] if key in TASKS else (
        ERROR_CASE["question"] if key == "error" else key)
    print(f"{config.DEMO_NAME} | DATA 260 HW7 Part 2 | agent run | model {MODEL_NAME} "
          f"(temperature {TEMPERATURE}) | {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Q: {question}")
    result = run_agent(question)
    print(f"A: {result['final_answer']}")
    if key in TASKS:
        v = TASKS[key]["verify"](result)
        print(f"check: {'PASS' if v['passed'] else 'FAIL'} - {'; '.join(v['reasons'])}")
    elif key == "error":
        from hw07_tasks import verify_error_case
        print(f"check: {verify_error_case(result)}")
