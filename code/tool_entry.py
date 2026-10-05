"""
HW5 Part 4 step 22 - execute_tool(name, inputs): the one way into the three
domain tools. The Part 5 agent calls nothing else.

    python code/tool_entry.py get_notice '{"recall_number": "F-0001-2025"}'

What it guarantees, whatever it is given:
  - the answer is a JSON *string* (a model reads text, not Python objects)
  - the string always holds the same envelope, {ok, data, error}
  - it never raises: bad name, bad inputs, database down - all become ok:false

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
        envelope = call_tool(name, inputs, repo if repo is not None else default_repo())
    except Exception as exc:                             # last line of defence; call_tool
        log.error("execute_tool(%r) failed: %r", name, exc)   # already catches tool errors
        envelope = fail(f"{name} could not be completed: {type(exc).__name__}")
    # default=str: a date or Decimal that slipped into data becomes text instead of an error
    return json.dumps(envelope, default=str)


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    if len(sys.argv) < 2:
        sys.exit("usage: python code/tool_entry.py <tool> '<json inputs>'")
    print(execute_tool(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else {}))
