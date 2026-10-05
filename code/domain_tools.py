"""
HW5 Parts 2B-5 - the three domain tools over s9275_rel (recall notices).

This file has no MCP in it. It is the core that every later layer reuses:

    domain_server.py   Part 2B   thin MCP wrapper around these tools
    (Part 3)                      timeouts, retries, fault injection
    (Part 4)                      execute_tool(name, inputs) and the offline tests
    (Part 5)                      safety rule and the agent loop

Every tool answers with the same envelope:

    {"ok": true,  "data": {...}, "error": null}       success
    {"ok": false, "data": null,  "error": "reason"}   anything else

Show the three input schemas:   python code/domain_tools.py
Call one tool against MySQL:    python code/domain_tools.py search_notices '{"query": "hummus"}'
"""
import json
import logging
import sys
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent / "auth_app"))
import config  # noqa: E402   Section 0 values and CATEGORIES (no database import)

log = logging.getLogger("domain_tools")     # whoever runs this decides where logs go (stderr)


# ---- 1. the envelope -----------------------------------------------------------

def ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def fail(error: str) -> dict:
    return {"ok": False, "data": None, "error": error}


# ---- 2. what each tool accepts -------------------------------------------------
# One Pydantic model per tool. The model is the single definition of the tool's
# input: it checks a call, and it produces the JSON schema shown to a client.

Category = Literal[config.CATEGORIES]  # type: ignore[valid-type]

RECALL_NUMBER_PATTERN = r"^F-\d{4}-\d{4}$"


class ToolInput(BaseModel):
    # extra="forbid": an argument the tool does not know is an error, not ignored
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SearchNoticesInput(ToolInput):
    """Search recall notices by product name, newest first. Each result has the
    recall number, product, category, date, units affected and the firm's name."""

    query: str = Field(min_length=2, max_length=100,
                       description="Part of a product name, e.g. 'peanut butter'")
    category: Optional[Category] = Field(default=None,
                                         description="Only notices in this recall category")
    limit: int = Field(default=5, ge=1, le=20, description="How many notices to return (1-20)")


class GetNoticeInput(ToolInput):
    """Everything about one recall notice, looked up by its recall number:
    product, category, date, units affected, and the issuing firm with its
    contact email. Use this for any question about a specific notice or its firm."""

    recall_number: str = Field(pattern=RECALL_NUMBER_PATTERN,
                               description="Recall number in the form F-NNNN-YYYY, e.g. F-0001-2025")


class RecallSummaryInput(ToolInput):
    """Statistics only: count notices and add up units_affected per group.
    Not for looking up a particular notice or a firm's details."""

    group_by: Literal["category", "state", "year", "firm"] = Field(
        description="What to group by; 'firm' returns the 10 firms with the most notices")
    year: Optional[int] = Field(default=None, ge=2021, le=2026,
                                description="Only notices recalled in this year (2021-2026)")


INPUT_MODELS: dict[str, type[ToolInput]] = {
    "search_notices": SearchNoticesInput,
    "get_notice": GetNoticeInput,
    "recall_summary": RecallSummaryInput,
}


def input_schema(name: str) -> dict:
    """The JSON schema of one tool's input (Part 3 documents these)."""
    return INPUT_MODELS[name].model_json_schema()


def check_inputs(name: str, inputs: Any) -> tuple[Optional[ToolInput], Optional[str]]:
    """Validate one call. Returns (params, None) when it is fine, (None, reason) when not.

    Never raises: a bad call is an ordinary outcome here, and the caller turns
    the reason into fail(reason).
    """
    if name not in INPUT_MODELS:
        return None, f"unknown tool {name!r}; available tools: {', '.join(INPUT_MODELS)}"
    if not isinstance(inputs, dict):
        return None, "inputs must be a JSON object such as {\"query\": \"hummus\"}"
    try:
        return INPUT_MODELS[name](**inputs), None
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            field = ".".join(str(part) for part in err["loc"]) or "inputs"
            problems.append(f"{field}: {err['msg']}")
        return None, "; ".join(problems)


# ---- 3. where the data comes from ---------------------------------------------
# A "repo" is any object with these three methods. The tools below only ever
# talk to a repo, never to MySQL directly, so Part 4 can hand them an
# in-memory repo and run without a database.
#
#     search(query, category, limit) -> list of notice dicts, newest first
#     get(recall_number)             -> one notice dict, or None
#     summary(group_by, year)        -> list of {"key", "notices", "units_affected"}

class MySQLRepo:
    """The real repo: reads s9275_rel through the SQLAlchemy models of Part 1."""

    def __init__(self):
        # Imported here, not at the top of the file: code that uses a different
        # repo never loads SQLAlchemy and never opens a database connection.
        from database import db_session_basede26
        from models import Firm, RecallNotice
        self.Session, self.Firm, self.Notice = db_session_basede26, Firm, RecallNotice

    @staticmethod
    def _notice(n, f) -> dict:
        return {
            "id": n.id,
            "recall_number": n.recall_number,
            "product_name": n.product_name,
            "category": n.category,
            "recall_date": n.recall_date.isoformat(),
            "units_affected": n.units_affected,
            "firm": {"id": f.id, "name": f.name, "state": f.state},
        }

    def search(self, query: str, category: Optional[str], limit: int) -> list[dict]:
        from sqlalchemy import select
        N, F = self.Notice, self.Firm
        # % and _ are wildcards in LIKE; escape them so they match literally
        text = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = (select(N, F).join(F, N.firm_id == F.id)
                .where(N.product_name.like(f"%{text}%", escape="\\"))
                .order_by(N.recall_date.desc(), N.id.desc())
                .limit(limit))
        if category is not None:
            stmt = stmt.where(N.category == category)
        with self.Session() as db:
            return [self._notice(n, f) for n, f in db.execute(stmt).all()]

    def get(self, recall_number: str) -> Optional[dict]:
        from sqlalchemy import select
        N, F = self.Notice, self.Firm
        stmt = select(N, F).join(F, N.firm_id == F.id).where(N.recall_number == recall_number)
        with self.Session() as db:
            row = db.execute(stmt).first()
        if row is None:
            return None
        n, f = row
        notice = self._notice(n, f)
        notice["firm"]["contact_email"] = f.contact_email
        notice["created_at"] = n.created_at.isoformat(sep=" ")
        notice["updated_at"] = n.updated_at.isoformat(sep=" ")
        return notice

    def summary(self, group_by: str, year: Optional[int]) -> list[dict]:
        from datetime import date
        from sqlalchemy import extract, func, select
        N, F = self.Notice, self.Firm
        key = {"category": N.category, "state": F.state, "firm": F.name,
               "year": extract("year", N.recall_date)}[group_by]
        notices = func.count(N.id)
        stmt = (select(key, notices, func.sum(N.units_affected))
                .join(F, N.firm_id == F.id)
                .group_by(key)
                .order_by(key if group_by == "year" else notices.desc(), key))
        if year is not None:
            stmt = stmt.where(N.recall_date.between(date(year, 1, 1), date(year, 12, 31)))
        with self.Session() as db:
            rows = db.execute(stmt).all()
        return [{"key": int(k) if group_by == "year" else k,
                 "notices": int(count), "units_affected": int(units)}
                for k, count, units in rows]


# ---- 4. the three tools ------------------------------------------------------------
# Each one takes a repo and already-checked params, and returns an envelope.

TOP_FIRMS = 10


def search_notices(repo, p: SearchNoticesInput) -> dict:
    notices = repo.search(p.query, p.category, p.limit)
    return ok({"count": len(notices), "notices": notices})


def get_notice(repo, p: GetNoticeInput) -> dict:
    notice = repo.get(p.recall_number)
    if notice is None:
        return fail(f"recall notice {p.recall_number} not found")
    return ok(notice)


def recall_summary(repo, p: RecallSummaryInput) -> dict:
    groups = repo.summary(p.group_by, p.year)
    data = {
        "group_by": p.group_by,
        "year": p.year,
        "total_notices": sum(g["notices"] for g in groups),
        "total_units_affected": sum(g["units_affected"] for g in groups),
        "group_count": len(groups),
        "groups": groups,
    }
    if p.group_by == "firm":            # 200 firms is too long a list; the totals still cover all
        data["groups"] = groups[:TOP_FIRMS]
        data["note"] = f"groups lists the top {TOP_FIRMS} of {len(groups)} firms by number of notices"
    return ok(data)


TOOLS = {
    "search_notices": search_notices,
    "get_notice": get_notice,
    "recall_summary": recall_summary,
}


# ---- 5. one way in ---------------------------------------------------------------

def call_tool(name: str, inputs: Any, repo) -> dict:
    """Check the inputs, run the tool, always come back with an envelope.

    A bad call returns fail(reason). So does a tool that breaks while running
    (database down, for example): the exception is logged and turned into a
    short error, it does not escape to the caller.
    """
    params, error = check_inputs(name, inputs)
    if error:
        log.info("rejected %s %s: %s", name, inputs, error)
        return fail(error)
    try:
        return TOOLS[name](repo, params)
    except Exception as exc:
        reason = str(exc).splitlines()[0][:200] if str(exc) else ""
        log.error("%s failed: %s: %s", name, type(exc).__name__, reason)
        log.debug("traceback for the failure above", exc_info=True)
        return fail(f"{name} could not be completed: {type(exc).__name__}: {reason}")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        for tool_name in INPUT_MODELS:
            print(f"--- {tool_name}")
            print(json.dumps(input_schema(tool_name), indent=2))
    else:
        logging.basicConfig(stream=sys.stderr, level=logging.INFO)
        tool_inputs = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        print(json.dumps(call_tool(sys.argv[1], tool_inputs, MySQLRepo()), indent=2))
