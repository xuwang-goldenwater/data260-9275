"""
HW5 Part 5-II - the agent loop: a local Ollama model that answers questions
about recall notices by calling the three domain tools.

    python code/agent_loop.py "How many recalls were there in 2025, by category?"

The loop (the "harness") does not think. Each step it
  1. sends the conversation and the tool definitions to the model,
  2. if the model answered in text: stops                       -> completed
  3. otherwise runs every tool the model asked for through execute_tool()
     and adds the results to the conversation,
  4. if a result is a safety-rule refusal: stops                -> safety_block
and it never takes more than max_steps steps                    -> max_steps

Every run is appended as one JSON line to reports/hw05/raw/agent_runs.jsonl:
each step, each tool call with its inputs and result, and the stop reason.
"""
import json
import logging
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from domain_tools import INPUT_MODELS, config, input_schema
from tool_entry import execute_tool, is_safety_block

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "reports" / "hw05" / "raw" / "agent_runs.jsonl"

MODEL_NAME = os.getenv("AGENT_MODEL", "qwen3:8b")     # e.g. AGENT_MODEL=qwen3:4b to try another local model
MAX_STEPS = 5

log = logging.getLogger("agent_loop")

SYSTEM_PROMPT = """You are the recall-notice assistant for a grocery supply database.
Answer only from what the tools return. Never invent recall numbers, firms or figures.

Every tool returns JSON of the form {"ok": ..., "data": ..., "error": ...}.
- ok true: use data.
- ok false: read error. If your arguments were wrong, correct them and call again.
  If the request cannot be done, tell the user what the error says.

Which tool for what:
- search_notices: find notices by product name.
- get_notice: everything about one notice, including the issuing firm and the
  firm's contact email. Recall numbers look like F-0001-2025. For details of a
  notice you found by searching, call get_notice with its recall_number.
- recall_summary: counts and totals only. It does not look up a notice or a firm.

When you have what you need, answer the user in plain text and do not call a tool."""


# ---- tool definitions for the model -------------------------------------------------

def tool_specs() -> list[dict]:
    """The three tools in the format Ollama expects, built from the Pydantic models.

    Ollama keeps only type, description and enum for each parameter, so the
    schema is reduced to those. The limits (1-20, the F-NNNN-YYYY pattern) are
    in the descriptions, and execute_tool enforces them whatever the model sends.
    """
    specs = []
    for name, model in INPUT_MODELS.items():
        schema = input_schema(name)
        properties = {}
        for field_name, prop in schema["properties"].items():
            core = next(o for o in prop.get("anyOf", [prop]) if o.get("type") != "null")
            properties[field_name] = {"type": core.get("type", "string"),
                                      "description": prop.get("description", "")}
            if "enum" in core:
                properties[field_name]["enum"] = list(core["enum"])
        specs.append({"type": "function", "function": {
            "name": name,
            "description": (model.__doc__ or "").strip(),
            "parameters": {"type": "object", "properties": properties,
                           "required": schema.get("required", [])},
        }})
    return specs


# ---- models -----------------------------------------------------------------------
# The loop needs one thing from a model: complete(messages, tools) returning an
# object with .text and .tool_calls ([{"name", "arguments"}, ...]).

@dataclass
class ModelReply:
    text: str = ""
    tool_calls: list = field(default_factory=list)


class MockModel:
    """A scripted stand-in for the LLM, for offline tests.

    script is a list of ModelReply; each complete() returns the next one and
    the last one repeats forever. No network, no Ollama.
    """

    model = "mock"

    def __init__(self, script: list):
        self.script, self.calls = list(script), 0

    def complete(self, messages, tools=None):
        reply = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return reply


def default_model():
    """The real model: src/model_client.py (Ollama, qwen3:8b, temperature 0)."""
    sys.path.insert(0, str(ROOT / "src"))
    from model_client import ModelClient          # imported here so tests never load ollama
    return ModelClient(model=MODEL_NAME, temperature=0.0)


def strip_thinking(text: str) -> str:
    """Remove a reasoning block that a model leaked into its answer.

    qwen3:4b ignores "thinking off" and writes its reasoning into the reply,
    ending with </think> (seen on 2026-10-05; qwen3:8b does not do this). The
    part after the last </think> is the answer. The log keeps the raw text.
    """
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return text.rsplit("</think>", 1)[-1].strip()


# ---- the loop ---------------------------------------------------------------------

def run_agent(user_input: str, model: Optional[Any] = None, repo: Optional[Any] = None,
              max_steps: int = MAX_STEPS, log_path: Optional[Path] = LOG_FILE) -> dict:
    """Answer one question. Returns the run record that is also written to the log.

    model      anything with complete(messages, tools); default: local Ollama
    repo       storage for execute_tool; default: MySQL with the retry policy
    max_steps  the most model turns allowed
    log_path   where to append the run (None = do not write)
    """
    model = model if model is not None else default_model()
    tools = tool_specs()
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_input}]
    run = {
        "run_id": uuid.uuid4().hex[:8],
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "user_input": user_input,
        "model": getattr(model, "model", type(model).__name__),
        "max_steps": max_steps,
        "steps": [],
    }
    started = time.perf_counter()
    stop_reason, final_answer = "max_steps", ""

    for step in range(1, max_steps + 1):                      # the turn counter
        turn_started = time.perf_counter()
        try:
            reply = model.complete(messages, tools=tools)
        except Exception as exc:                              # Ollama not running, model missing...
            log.error("model call failed: %r", exc)
            stop_reason = "model_error"
            final_answer = f"The model could not be reached: {type(exc).__name__}: {exc}"
            break
        record = {"step": step,
                  "model_ms": round((time.perf_counter() - turn_started) * 1000),
                  "input_tokens": getattr(reply, "input_tokens", None),     # None for MockModel
                  "output_tokens": getattr(reply, "output_tokens", None),
                  "assistant_text": reply.text,
                  "tool_calls": []}
        run["steps"].append(record)

        if not reply.tool_calls:                              # a plain answer ends the run
            stop_reason, final_answer = "completed", strip_thinking(reply.text)
            break

        messages.append({"role": "assistant", "content": reply.text,
                         "tool_calls": [{"function": {"name": c["name"], "arguments": c["arguments"]}}
                                        for c in reply.tool_calls]})
        blocked = None
        for call in reply.tool_calls:
            result_text = execute_tool(call["name"], call["arguments"], repo=repo)
            envelope = json.loads(result_text)
            record["tool_calls"].append({"tool": call["name"], "inputs": call["arguments"],
                                         "result": envelope})
            messages.append({"role": "tool", "tool_name": call["name"], "content": result_text})
            if is_safety_block(envelope):
                blocked = envelope["error"]
                break
        if blocked:                                           # policy refusal: stop at once
            stop_reason = "safety_block"
            final_answer = f"I can't help with that request. {blocked}"
            break
    else:
        final_answer = (f"Stopped after {max_steps} steps without a final answer "
                        f"(max_steps limit).")

    run.update({
        "stop_reason": stop_reason,
        "step_count": len(run["steps"]),
        "tool_call_count": sum(len(s["tool_calls"]) for s in run["steps"]),
        "final_answer": final_answer,
        "duration_ms": round((time.perf_counter() - started) * 1000),
    })
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(run, default=str) + "\n")
    return run


def print_run(run: dict) -> None:
    """Show one run step by step."""
    print(f"\nQ: {run['user_input']}")
    for step in run["steps"]:
        cost = f"{step['model_ms'] / 1000:.1f} s"
        if step.get("output_tokens") is not None:
            cost += f", {step['input_tokens']} tokens in / {step['output_tokens']} out"
        if not step["tool_calls"]:
            print(f"  step {step['step']} ({cost}): model answered in text")
        for call in step["tool_calls"]:
            result = call["result"]
            outcome = "ok" if result["ok"] else f"ok false - {result['error']}"
            print(f"  step {step['step']} ({cost}): {call['tool']}({json.dumps(call['inputs'])}) -> {outcome}")
    print(f"  stop reason: {run['stop_reason']} | steps: {run['step_count']}/{run['max_steps']} | "
          f"tool calls: {run['tool_call_count']} | {run['duration_ms'] / 1000:.1f} s")
    print(f"A: {run['final_answer']}")


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.ERROR)
    if len(sys.argv) < 2:
        sys.exit('usage: python code/agent_loop.py "your question" [max_steps]')
    steps_allowed = int(sys.argv[2]) if len(sys.argv) > 2 else MAX_STEPS
    print(f"{config.DEMO_NAME} | DATA 260 HW5 Part 5 | {config.PREFIX} | agent run | "
          f"model {MODEL_NAME} | {datetime.now():%Y-%m-%d %H:%M:%S}")
    print_run(run_agent(sys.argv[1], max_steps=steps_allowed))
