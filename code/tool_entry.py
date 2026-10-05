"""
HW5 Part 4 step 22 - execute_tool(name, inputs): the one way into the three
domain tools. The Part 5 agent calls nothing else.

    python code/tool_entry.py get_notice '{"recall_number": "F-0001-2025"}'
    python code/tool_entry.py --safety-demo          # make safety-demo (Part 5)

What it guarantees, whatever it is given:
  - the answer is a JSON *string* (a model reads text, not Python objects)
  - the string always holds the same envelope, {ok, data, error}
  - it never raises: bad name, bad inputs, database down - all become ok:false

Part 5 adds one business safety rule here (see safety_check below). It lives
in execute_tool, so it binds the agent; a person using the MCP server through
the Inspector is not restricted by it.

The work itself is done by call_tool() in domain_tools.py; the default storage
is MySQL behind the Part 3 timeout + retry policy. A test passes its own repo
through the `repo` argument instead (dependency injection).
"""
import json
import logging
import sys
from typing import Any, Optional

from domain_tools import call_tool, fail

log = logging.getLogger("tool_entry")

_default_repo = None


def default_repo():
    """MySQL with timeout + retries, created the first time it is needed."""
    global _default_repo
    if _default_repo is None:
        from domain_tools import MySQLRepo
        from retry_policy import RetryingRepo
        _default_repo = RetryingRepo(MySQLRepo())
    return _default_repo


# ---- Part 5: the safety rule ---------------------------------------------------------

SAFETY_PREFIX = "blocked by safety rule"


def safety_check(name: str, inputs: Any) -> Optional[str]:
    """The domain rule: the assistant must not rank named firms by recalls.

    recall_summary with group_by "firm" returns the ten companies with the most
    recall notices. Published by an assistant, built from data that may be
    incomplete, that list is a "worst offenders" table of real business names:
    a reputational and legal risk. Totals by category, state or year name no
    company, so they stay allowed.

    This is not an input check. {"group_by": "firm"} is valid input (Part 3
    accepts it); the rule refuses it on policy grounds.

    Returns the reason when the call must not run, or None when it may.
    """
    if name == "recall_summary" and isinstance(inputs, dict):
        if str(inputs.get("group_by", "")).strip().lower() == "firm":
            return (f"{SAFETY_PREFIX}: recall_summary may not group by firm, because the "
                    f"assistant must not rank named companies by recalls. "
                    f"Group by category, state or year instead.")
    return None


def is_safety_block(envelope: dict) -> bool:
    """True when an envelope is a refusal from the safety rule (the agent loop stops on these)."""
    return envelope.get("ok") is False and str(envelope.get("error", "")).startswith(SAFETY_PREFIX)


def execute_tool(name: str, inputs: Any, repo: Optional[Any] = None) -> str:
    """Run one domain tool and return its {ok, data, error} envelope as a JSON string.

    name    "search_notices", "get_notice" or "recall_summary"
    inputs  the tool's arguments: a dict, or the same thing as a JSON string
            (models often hand over their arguments as text)
    repo    storage to use; leave it out for MySQL
    """
    try:
        if isinstance(inputs, str):                      # arguments arrived as text
            try:
                inputs = json.loads(inputs)
            except ValueError:
                return json.dumps(fail("inputs is not valid JSON"))
        blocked = safety_check(name, inputs)             # Part 5: policy first, before any work
        if blocked:
            log.warning("%s %s -> %s", name, inputs, blocked)
            return json.dumps(fail(blocked))
        envelope = call_tool(name, inputs, repo if repo is not None else default_repo())
    except Exception as exc:                             # last line of defence; call_tool
        log.error("execute_tool(%r) failed: %r", name, exc)   # already catches tool errors
        envelope = fail(f"{name} could not be completed: {type(exc).__name__}")
    # default=str: a date or Decimal that slipped into data becomes text instead of an error
    return json.dumps(envelope, default=str)


def safety_demo():
    """Part 5-I: one allowed call and one blocked call, through execute_tool."""
    from datetime import datetime

    from domain_tools import config

    print(f"{config.DEMO_NAME} | DATA 260 HW5 Part 5 | {config.PREFIX} | safety rule demo | "
          f"{datetime.now():%Y-%m-%d %H:%M:%S}")
    print("Rule: the assistant must not rank named firms by recalls "
          "(recall_summary with group_by = firm).\n")
    for label, inputs in [("ALLOWED", {"group_by": "category", "year": 2025}),
                          ("BLOCKED", {"group_by": "firm", "year": 2025})]:
        text = execute_tool("recall_summary", inputs)
        envelope = json.loads(text)
        print(f"{label}  execute_tool(\"recall_summary\", {json.dumps(inputs)})")
        if envelope["ok"]:
            groups = ", ".join(f"{g['key']}: {g['notices']}" for g in envelope["data"]["groups"])
            print(f"  ok    : true")
            print(f"  data  : total_notices {envelope['data']['total_notices']}; {groups}")
            print(f"  error : null\n")
        else:
            print(f"  returned: {text}\n")


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.ERROR)
    if len(sys.argv) < 2:
        sys.exit("usage: python code/tool_entry.py <tool> '<json inputs>'   |   --safety-demo")
    if sys.argv[1] == "--safety-demo":
        safety_demo()
    else:
        print(execute_tool(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else {}))
