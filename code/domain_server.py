"""
HW5 Part 2B - MCP server over the s9275_rel domain data (recall notices), STDIO.

    make inspect-domain
    (= npx @modelcontextprotocol/inspector python code/domain_server.py)

Exactly three tools: search_notices (search), get_notice (detail lookup),
recall_summary (aggregate). Every one of them answers with the same envelope:

    {"ok": true,  "data": {...}, "error": null}
    {"ok": false, "data": null,  "error": "reason"}

This file is only the MCP wrapper. The envelope, the input checks and the
queries live in domain_tools.py, which Parts 3-5 reuse without MCP.

STDIO rule: stdout carries the JSON-RPC messages, so there is no print() here;
all logging goes to stderr.
"""
import logging
import sys
from typing import Annotated, Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from domain_tools import MySQLRepo, call_tool
from retry_policy import RetryingRepo

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("domain_server")

mcp = FastMCP("s9275_recalls")

_repo = None


def repo() -> RetryingRepo:
    """One repo for the whole process, created on the first tool call: MySQL,
    wrapped in the Part 3 timeout + retry policy.

    Not created at import time, so the server still starts and lists its tools
    when MySQL is down; the tool call then returns an ok:false envelope.
    """
    global _repo
    if _repo is None:
        _repo = RetryingRepo(MySQLRepo())
    return _repo


# The parameters below carry descriptions but no limits (no ge=/le=/pattern=).
# That is deliberate. If the limits were declared here, FastMCP would reject a
# bad call itself, with its own error format, before our code runs. Leaving
# them out lets every call reach call_tool(), so a bad call comes back in the
# same {ok, data, error} envelope as a good one.

@mcp.tool()
def search_notices(
    query: Annotated[str, Field(description="Part of a product name, 2-100 characters, e.g. peanut butter")],
    category: Annotated[Optional[str], Field(
        description="Optional. One of: Undeclared Allergen, Bacterial Contamination, "
                    "Foreign Material, Mislabeling")] = None,
    limit: Annotated[int, Field(description="How many notices to return, 1-20")] = 5,
) -> dict[str, Any]:
    """Search recall notices by product name, newest first.
    Returns {ok, data, error}; data = {count, notices: [...]}."""
    return call_tool("search_notices", {"query": query, "category": category, "limit": limit}, repo())


@mcp.tool()
def get_notice(
    recall_number: Annotated[str, Field(description="Recall number, format F-NNNN-YYYY, e.g. F-0001-2025")],
) -> dict[str, Any]:
    """Full details of one recall notice and its firm, looked up by recall number.
    Returns {ok, data, error}; data = the notice."""
    return call_tool("get_notice", {"recall_number": recall_number}, repo())


@mcp.tool()
def recall_summary(
    group_by: Annotated[str, Field(description="One of: category, state, year, firm")],
    year: Annotated[Optional[int], Field(description="Optional. Only this recall year, 2021-2026")] = None,
) -> dict[str, Any]:
    """Count recall notices and add up units_affected, grouped by category, state, year or firm.
    Returns {ok, data, error}; data = {total_notices, total_units_affected, groups: [...]}."""
    return call_tool("recall_summary", {"group_by": group_by, "year": year}, repo())


if __name__ == "__main__":
    log.info("starting s9275_recalls over stdio")
    mcp.run(transport="stdio")
