"""
DATA 260 - Homework 2, Parts 3 and 4: stateful agent graph with a supervisor.

Homework 1 ran Planner -> Reviewer -> Finalizer as a straight line. That shape
cannot go back. Here the same two agents become nodes in a LangGraph
StateGraph, and a supervisor decides after every step where control goes next,
which makes the correction loop possible:

        +---------------------+
        |     supervisor      |  <-- counts agent dispatches, enforces ceiling
        |   (router_logic)    |
        +----------+----------+
                   |
      +------------+-------------+
      |                          |
 (no valid proposal)      (proposal needs review)
      v                          v
 +----------+              +-----------+
 | planner  |              | reviewer  |
 +----+-----+              +-----+-----+
      |                          |
      +------> supervisor <------+           (no issues) --> END
                                              (issues)   --> planner

Every model call goes through src/model_client.py, the HW1 adapter. Nothing in
this file imports ollama or langchain directly.

Part 4 adds a Pydantic gate on the Planner's output: exactly three tags, each
3-30 characters, and a summary of at most 25 words. A rejected proposal never
reaches the Reviewer; the validation error is fed back to the Planner and it
tries again, until the turn ceiling stops the run.

Usage:
    python agent_graph.py                          # one streamed run
    python agent_graph.py --ceiling 2
    python agent_graph.py --input ../reports/hw02/cases/schema_input.json
    python agent_graph.py --force-reviewer-issues  # Step 6 loop test
    python agent_graph.py --json                   # one JSON record, no stream
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, ValidationError, field_validator

# src/model_client.py is the single adapter every model call goes through.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from model_client import DEFAULT_MODEL, ModelClient  # noqa: E402

TAG_COUNT = 3
TAG_MIN_CHARS = 3
TAG_MAX_CHARS = 30
MAX_SUMMARY_WORDS = 25
DEFAULT_CEILING = 10


# ===========================================================================
# Part 4.1 - the output contract, as a Pydantic model
# ===========================================================================


class PlannerOutput(BaseModel):
    """What the Planner must produce for the run to continue.

    The JSON *shape* is already enforced by Ollama's `format` parameter. What
    that cannot express is the semantic part of the contract: how long a tag
    may be and how many words a summary may contain. Those are the two rules
    below, and they are the ones that actually fail in practice.
    """

    tags: List[str] = Field(min_length=TAG_COUNT, max_length=TAG_COUNT)
    summary: str

    @field_validator("tags")
    @classmethod
    def _tag_lengths(cls, tags: List[str]) -> List[str]:
        for tag in tags:
            if not isinstance(tag, str):
                raise ValueError(f"tag {tag!r} is not a string")
            if not (TAG_MIN_CHARS <= len(tag) <= TAG_MAX_CHARS):
                raise ValueError(
                    f"tag {tag!r} is {len(tag)} characters; each tag must be "
                    f"{TAG_MIN_CHARS}-{TAG_MAX_CHARS} characters"
                )
        return tags

    @field_validator("summary")
    @classmethod
    def _summary_words(cls, summary: str) -> str:
        words = len(summary.split())
        if words > MAX_SUMMARY_WORDS:
            raise ValueError(
                f"summary is {words} words; at most {MAX_SUMMARY_WORDS} are allowed"
            )
        if words == 0:
            raise ValueError("summary is empty")
        return summary


def format_validation_error(error: ValidationError) -> str:
    """One readable line per broken rule, for feeding back to the Planner."""
    parts = []
    for item in error.errors():
        location = ".".join(str(x) for x in item.get("loc", ())) or "output"
        message = item.get("msg", "invalid")
        parts.append(f"{location}: {message}")
    return "; ".join(parts)


# ===========================================================================
# Part 3 Step 2 - the shared state
# ===========================================================================


class AgentState(TypedDict, total=False):
    """The memory every node reads from and writes to.

    The first block is the assignment's suggested state. The second block is
    what Part 4 needs in order to classify a run afterwards.
    """

    # --- inputs, present before the graph starts ---
    title: str
    content: str
    email: str
    strict: bool
    task: str
    llm: Any                       # the ModelClient instance

    # --- agent outputs ---
    planner_proposal: Optional[Dict[str, Any]]
    reviewer_feedback: Optional[Dict[str, Any]]
    turn_count: int

    # --- loop safety and bookkeeping (Part 4) ---
    turn_ceiling: int
    validation_error: Optional[str]
    planner_attempts: int
    reviewer_attempts: int
    status: str                    # running | complete | abandoned
    force_reviewer_issues: bool
    history: List[Dict[str, Any]]


def initial_state(
    title: str,
    content: str,
    email: str = "",
    turn_ceiling: int = DEFAULT_CEILING,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.0,
    strict: bool = True,
    force_reviewer_issues: bool = False,
) -> AgentState:
    return AgentState(
        title=title,
        content=content,
        email=email,
        strict=strict,
        task="Extract exactly three topical tags and a short summary.",
        llm=ModelClient(model=model, temperature=temperature),
        planner_proposal=None,
        reviewer_feedback=None,
        turn_count=0,
        turn_ceiling=turn_ceiling,
        validation_error=None,
        planner_attempts=0,
        reviewer_attempts=0,
        status="running",
        force_reviewer_issues=force_reviewer_issues,
        history=[],
    )


# ===========================================================================
# Prompts and JSON extraction (carried over from HW1's agents_demo.py)
# ===========================================================================

PLANNER_SYSTEM = (
    "You extract topical metadata from a document.\n"
    "You are given a TITLE and a CONTENT block.\n"
    f"Produce exactly {TAG_COUNT} short topical tags and a summary of at most "
    f"{MAX_SUMMARY_WORDS} words.\n"
    "Rules:\n"
    "- Every tag must be grounded in the given text: use words or phrases that "
    "appear in, or are directly stated by, the TITLE or CONTENT.\n"
    "- Do not use outside knowledge, and do not invent generic category labels.\n"
    f"- Each tag is {TAG_MIN_CHARS} to {TAG_MAX_CHARS} characters, lower case, "
    "no punctuation, no duplicates.\n"
    f"- The summary must be one sentence of at most {MAX_SUMMARY_WORDS} words "
    "and factually supported by the CONTENT. Count the words before answering.\n"
    "Respond with JSON only."
)

REVIEWER_SYSTEM = (
    "You review another agent's extraction against the source text.\n"
    "Check every item:\n"
    f"- exactly {TAG_COUNT} tags, no duplicates and no near-duplicates\n"
    "- each tag is grounded in the TITLE or CONTENT, not outside knowledge\n"
    "- each tag is specific rather than a generic category word\n"
    f"- the summary is at most {MAX_SUMMARY_WORDS} words and is supported by "
    "the CONTENT\n"
    "Set has_issues to true only if something above is actually wrong.\n"
    "In issues, state in one sentence what is wrong, or that nothing is wrong.\n"
    "Respond with JSON only."
)

PLANNER_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": TAG_COUNT,
            "maxItems": TAG_COUNT,
        },
        "summary": {"type": "string"},
    },
    "required": ["tags", "summary"],
}

REVIEWER_SCHEMA = {
    "type": "object",
    "properties": {
        "has_issues": {"type": "boolean"},
        "issues": {"type": "string"},
    },
    "required": ["has_issues", "issues"],
}

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
CODE_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json_object(text: str) -> Dict[str, Any]:
    """Return the first JSON object in a raw model reply."""
    cleaned = THINK_BLOCK.sub(" ", str(text))
    fenced = CODE_FENCE.search(cleaned)
    if fenced:
        cleaned = fenced.group(1)
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = cleaned.find("{", start + 1)

    raise ValueError(f"no JSON object found in model output: {cleaned[:200]!r}")


def build_input_block(state: AgentState) -> str:
    return f"TITLE:\n{state['title']}\n\nCONTENT:\n{state['content']}"


# ===========================================================================
# Part 3 Step 4 - the supervisor: a state-updating node and a routing function
# ===========================================================================


def next_worker(state: AgentState) -> Optional[str]:
    """Which agent still has work to do, or None if the run is over.

    Order matters. Each branch answers one question, and the first one that
    applies wins:
      1. is the run already over, either finished or abandoned?
      2. is there a proposal that passed validation?
      3. has that proposal been reviewed yet?
      4. did the review find something wrong?

    Both the supervisor node and the routing function read this one predicate,
    so the counter and the route can never disagree about what happens next.
    """
    if state.get("status") in ("complete", "abandoned"):
        return None

    if state.get("validation_error") or state.get("planner_proposal") is None:
        return "planner"

    feedback = state.get("reviewer_feedback")
    if feedback is None:
        return "reviewer"

    if feedback.get("has_issues"):
        return "planner"

    return None


def supervisor_node(state: AgentState) -> Dict[str, Any]:
    """Counts turns and stops the graph when the ceiling is reached.

    This node does no work of its own. Keeping the counter here, rather than in
    the agents, means there is exactly one place where a run can be declared
    over, which is what makes the ceiling a guarantee instead of a convention.

    One turn is one dispatch to an agent. A run that is right the first time
    therefore costs two turns: Planner once, Reviewer once. The supervisor
    visits that route straight to END are not counted, because no agent ran.
    """
    ceiling = state.get("turn_ceiling", DEFAULT_CEILING)
    pending = next_worker(state)

    if pending is None:
        print(f"---NODE: Supervisor (no work left, {state.get('turn_count', 0)} turns used) ---")
        return {}

    turn = state.get("turn_count", 0) + 1
    print(f"---NODE: Supervisor (turn {turn}/{ceiling} -> {pending}) ---")

    update: Dict[str, Any] = {"turn_count": turn}
    if turn > ceiling:
        print(f"    turn ceiling {ceiling} reached; abandoning the run")
        update["status"] = "abandoned"
    return update


def router_logic(state: AgentState) -> str:
    """Reads the state and names the next node. Writes nothing."""
    worker = next_worker(state)
    return worker if worker is not None else END


# ===========================================================================
# Part 3 Step 3 - the agent nodes
# ===========================================================================


def planner_node(state: AgentState) -> Dict[str, Any]:
    """Propose three tags and a summary, then validate the proposal.

    On a retry the Planner is told what was wrong: either the Pydantic error
    from its own last attempt, or the Reviewer's complaint about the previous
    proposal. That feedback is the only thing that changes between attempts.
    """
    print("---NODE: Planner ---")
    client: ModelClient = state["llm"]
    attempts = state.get("planner_attempts", 0) + 1
    history = list(state.get("history", []))

    user_parts = [build_input_block(state)]

    if state.get("validation_error"):
        # Part 4.2 - feed the validation error back to the Planner.
        user_parts.append(
            "YOUR PREVIOUS ANSWER WAS REJECTED BY THE OUTPUT VALIDATOR:\n"
            f"{state['validation_error']}\n"
            "Fix exactly that problem and answer again."
        )
    elif state.get("reviewer_feedback", {}) and state["reviewer_feedback"].get("has_issues"):
        user_parts.append(
            "A REVIEWER REJECTED YOUR PREVIOUS ANSWER:\n"
            f"previous: {json.dumps(state.get('planner_proposal'), ensure_ascii=False)}\n"
            f"reviewer said: {state['reviewer_feedback'].get('issues', '')}\n"
            "Address that and answer again."
        )

    response = client.complete(
        messages=[
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ],
        response_format=PLANNER_SCHEMA,
    )

    entry: Dict[str, Any] = {
        "node": "planner",
        "attempt": attempts,
        "turn": state.get("turn_count", 0),
        "latency_ms": round(response.latency_ms, 1),
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
    }

    try:
        raw = extract_json_object(response.text)
    except ValueError as err:
        entry.update({"valid": False, "error": str(err)})
        history.append(entry)
        print(f"    rejected: {err}")
        return {
            "planner_proposal": None,
            "validation_error": str(err),
            "reviewer_feedback": None,
            "planner_attempts": attempts,
            "history": history,
        }

    # Part 4.1 - the Pydantic gate.
    try:
        validated = PlannerOutput(**raw)
    except ValidationError as err:
        message = format_validation_error(err)
        entry.update({"valid": False, "error": message, "raw": raw})
        history.append(entry)
        print(f"    rejected by schema: {message}")
        return {
            "planner_proposal": None,
            "validation_error": message,
            "reviewer_feedback": None,
            "planner_attempts": attempts,
            "history": history,
        }

    proposal = validated.model_dump()
    entry.update({"valid": True, "proposal": proposal})
    history.append(entry)
    print(f"    accepted: {json.dumps(proposal, ensure_ascii=False)}")

    return {
        "planner_proposal": proposal,
        "validation_error": None,
        "reviewer_feedback": None,     # this proposal has not been reviewed yet
        "planner_attempts": attempts,
        "history": history,
    }


def reviewer_node(state: AgentState) -> Dict[str, Any]:
    """Check the validated proposal against the source text.

    Part 3 Step 6 asks for the correction loop to be demonstrated by making the
    Reviewer always complain. That is the --force-reviewer-issues flag rather
    than an edit to this function, so the loop test is reproducible and the
    normal path is never left modified by accident.
    """
    print("---NODE: Reviewer ---")
    attempts = state.get("reviewer_attempts", 0) + 1
    history = list(state.get("history", []))

    if state.get("force_reviewer_issues"):
        feedback = {
            "has_issues": True,
            "issues": "forced rejection for the loop test (--force-reviewer-issues)",
            "forced": True,
        }
        history.append(
            {"node": "reviewer", "attempt": attempts, "turn": state.get("turn_count", 0),
             "forced": True, "has_issues": True}
        )
        print("    forced issue; sending the task back to the Planner")
        return {"reviewer_feedback": feedback, "reviewer_attempts": attempts, "history": history}

    client: ModelClient = state["llm"]
    proposal = state.get("planner_proposal") or {}

    response = client.complete(
        messages=[
            {"role": "system", "content": REVIEWER_SYSTEM},
            {
                "role": "user",
                "content": build_input_block(state)
                + "\n\nPROPOSED EXTRACTION FROM THE PLANNER:\n"
                + json.dumps(proposal, ensure_ascii=False),
            },
        ],
        response_format=REVIEWER_SCHEMA,
    )

    try:
        raw = extract_json_object(response.text)
        feedback = {
            "has_issues": bool(raw.get("has_issues", False)),
            "issues": str(raw.get("issues", "")),
        }
    except ValueError as err:
        # An unreadable review is not a reason to loop; treat it as no issue
        # and let the run finish, with the failure recorded.
        feedback = {"has_issues": False, "issues": f"reviewer output unreadable: {err}"}

    history.append(
        {
            "node": "reviewer",
            "attempt": attempts,
            "turn": state.get("turn_count", 0),
            "latency_ms": round(response.latency_ms, 1),
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "has_issues": feedback["has_issues"],
            "issues": feedback["issues"],
        }
    )
    print(f"    has_issues={feedback['has_issues']}: {feedback['issues']}")

    update: Dict[str, Any] = {
        "reviewer_feedback": feedback,
        "reviewer_attempts": attempts,
        "history": history,
    }
    if not feedback["has_issues"]:
        update["status"] = "complete"
    return update


# ===========================================================================
# Part 3 Step 5 - assembling the graph
# ===========================================================================


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("planner", planner_node)
    graph.add_node("reviewer", reviewer_node)

    graph.set_entry_point("supervisor")

    # The supervisor is the only node with a choice to make.
    graph.add_conditional_edges(
        "supervisor",
        router_logic,
        {"planner": "planner", "reviewer": "reviewer", END: END},
    )

    # Both workers hand control straight back, so the turn counter and the
    # ceiling are applied after every single step.
    graph.add_edge("planner", "supervisor")
    graph.add_edge("reviewer", "supervisor")

    return graph.compile()


# ===========================================================================
# Running one graph
# ===========================================================================


def classify(state: Dict[str, Any]) -> str:
    """Part 4.3 - the four outcome buckets."""
    if state.get("status") != "complete":
        return "hit turn ceiling"
    retries = max(0, int(state.get("planner_attempts", 1)) - 1)
    if retries == 0:
        return "valid first attempt"
    if retries == 1:
        return "valid after 1 retry"
    return "valid after 2+ retries"


def run_once(
    title: str,
    content: str,
    turn_ceiling: int = DEFAULT_CEILING,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.0,
    force_reviewer_issues: bool = False,
    stream: bool = True,
) -> Dict[str, Any]:
    """Invoke the graph once and return a record describing what happened."""
    app = build_graph()
    state = initial_state(
        title=title,
        content=content,
        turn_ceiling=turn_ceiling,
        model=model,
        temperature=temperature,
        force_reviewer_issues=force_reviewer_issues,
    )

    # Two graph steps per turn (supervisor + one worker), plus headroom. Without
    # this, LangGraph's own recursion limit of 25 would stop a ceiling-10 run
    # before the supervisor ever got to.
    config = {"recursion_limit": 2 * turn_ceiling + 10}

    started = time.perf_counter()
    final: Dict[str, Any] = {}

    if stream:
        # Part 3 Step 6 - .stream() shows the output of each step as it happens.
        for chunk in app.stream(state, config=config):
            for node_name, update in chunk.items():
                # A node that changed nothing yields None here. The supervisor
                # does that on its last visit, when no agent still owes work.
                if not update:
                    continue
                final.update(update)
                keys = [k for k in update if k not in ("history", "llm")]
                print(f"    [stream] {node_name} updated: {', '.join(keys)}")
    else:
        final = dict(app.invoke(state, config=config))

    elapsed_ms = (time.perf_counter() - started) * 1000.0

    if stream:
        # .stream() yields only the per-node updates, so carry the inputs over.
        merged = dict(state)
        merged.update(final)
        final = merged

    client: ModelClient = state["llm"]
    stats = client.stats()

    return {
        "outcome": classify(final),
        "status": final.get("status", "running"),
        "turn_count": final.get("turn_count", 0),
        "turn_ceiling": turn_ceiling,
        "planner_attempts": final.get("planner_attempts", 0),
        "reviewer_attempts": final.get("reviewer_attempts", 0),
        "planner_proposal": final.get("planner_proposal"),
        "reviewer_feedback": final.get("reviewer_feedback"),
        "validation_error": final.get("validation_error"),
        "latency_ms": round(elapsed_ms, 1),
        "model": model,
        "temperature": temperature,
        "llm_calls": stats["turn_count"],
        "input_tokens": stats["cumulative_input_tokens"],
        "output_tokens": stats["cumulative_output_tokens"],
        "history": final.get("history", []),
    }


# ===========================================================================
# CLI
# ===========================================================================

DEFAULT_TITLE = "Sunrise Valley Creamy Peanut Butter, 16 oz jar"
DEFAULT_CONTENT = (
    "Sunrise Valley Foods is voluntarily recalling 16 oz jars of Creamy Peanut "
    "Butter with lot codes SV2451 through SV2458 and best-by dates from "
    "2027-03-11 to 2027-03-18. Routine internal testing found the affected lots "
    "may contain undeclared milk from a shared production line. People with an "
    "allergy or severe sensitivity to milk risk a serious or life-threatening "
    "allergic reaction. The product was distributed to retail stores in "
    "California, Nevada, and Oregon. Consumers should not eat the product and "
    "may return it to the place of purchase for a full refund."
)


def load_case(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {"title": DEFAULT_TITLE, "content": DEFAULT_CONTENT}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        "title": data.get("title") or data.get("productName") or DEFAULT_TITLE,
        "content": data.get("content") or data.get("description") or DEFAULT_CONTENT,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="HW2 stateful agent graph")
    parser.add_argument("--input", default=None, help="JSON file with title and content")
    parser.add_argument("--ceiling", type=int, default=DEFAULT_CEILING)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--force-reviewer-issues",
        action="store_true",
        help="Step 6 loop test: the Reviewer always reports a problem",
    )
    parser.add_argument("--json", action="store_true", help="print one JSON record only")
    args = parser.parse_args()

    case = load_case(args.input)
    record = run_once(
        title=case["title"],
        content=case["content"],
        turn_ceiling=args.ceiling,
        model=args.model,
        temperature=args.temperature,
        force_reviewer_issues=args.force_reviewer_issues,
        stream=not args.json,
    )

    if args.json:
        print(json.dumps(record, ensure_ascii=False))
        return 0

    print()
    print("=" * 70)
    print("RESULT")
    print("=" * 70)
    print(f"outcome          : {record['outcome']}")
    print(f"status           : {record['status']}")
    print(f"turns used       : {record['turn_count']} / {record['turn_ceiling']}")
    print(f"planner attempts : {record['planner_attempts']}")
    print(f"reviewer attempts: {record['reviewer_attempts']}")
    print(f"model calls      : {record['llm_calls']}")
    print(f"total latency    : {record['latency_ms']:.0f} ms")
    print()
    print(json.dumps(record["planner_proposal"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
