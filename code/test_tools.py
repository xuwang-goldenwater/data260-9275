"""
HW5 Part 4 steps 23-24 - offline tests for execute_tool and the three domain tools.

    python code/test_tools.py        # make test-tools

Plain assert statements, no test framework. Each test prints PASS or FAIL and
the run ends with an X/Y summary (exit code 1 if anything failed).

Offline by dependency injection: every test hands execute_tool an
InMemoryRepo built from the six notices below, so no MySQL, no network and no
model is involved. The last test checks that claim.
"""
import json
import logging
import sys
import traceback
from datetime import datetime

from domain_tools import config
from retry_policy import DEFAULT_POLICY, RetryingRepo, TransientStorageError
from tool_entry import execute_tool

# ---- fixture: a tiny copy of the domain data ------------------------------------

FIRMS = {
    1: {"id": 1, "name": "Harbor Snacks Co.", "state": "GA"},
    2: {"id": 2, "name": "Maple Snacks Co.", "state": "NV"},
    3: {"id": 3, "name": "Meadow Bakery Inc.", "state": "AZ"},
}

NOTICES = [
    # id, recall_number, product_name, category, recall_date, units_affected, firm id
    (1, "F-0001-2025", "Blue Heron Enoki Mushrooms, 32 oz tub", "Undeclared Allergen", "2025-06-23", 8019, 1),
    (2, "F-0002-2021", "Green Leaf Almond Granola, 16 oz", "Undeclared Allergen", "2021-02-25", 6038, 2),
    (3, "F-0003-2023", "Sunrise Valley Tahini, 6-pack", "Mislabeling", "2023-12-29", 4057, 1),
    (10, "F-0010-2025", "Harbor Point Hummus, 8 oz", "Mislabeling", "2025-03-01", 500, 3),
    (11, "F-0011-2025", "Good Grain Hummus, 16 oz", "Foreign Material", "2025-09-14", 1200, 3),
    (12, "F-0012-2026", "Morning Dew Creamy Peanut Butter, 16 oz", "Undeclared Allergen", "2026-08-30", 3114, 2),
]


class InMemoryRepo:
    """Same three methods as MySQLRepo, answered from a Python list.
    self.calls records which methods were used, so a test can check that a
    rejected call never reached storage."""

    def __init__(self):
        self.calls = []
        self.rows = [
            {"id": i, "recall_number": number, "product_name": name, "category": category,
             "recall_date": day, "units_affected": units, "firm": dict(FIRMS[firm_id])}
            for i, number, name, category, day, units, firm_id in NOTICES
        ]

    def search(self, query, category, limit):
        self.calls.append("search")
        hits = [r for r in self.rows
                if query.lower() in r["product_name"].lower()
                and (category is None or r["category"] == category)]
        hits.sort(key=lambda r: (r["recall_date"], r["id"]), reverse=True)     # newest first
        return hits[:limit]

    def get(self, recall_number):
        self.calls.append("get")
        for r in self.rows:
            if r["recall_number"] == recall_number:
                return dict(r)
        return None

    def summary(self, group_by, year):
        self.calls.append("summary")
        key_of = {"category": lambda r: r["category"], "state": lambda r: r["firm"]["state"],
                  "firm": lambda r: r["firm"]["name"], "year": lambda r: int(r["recall_date"][:4])}[group_by]
        groups = {}
        for r in self.rows:
            if year is not None and int(r["recall_date"][:4]) != year:
                continue
            g = groups.setdefault(key_of(r), {"key": key_of(r), "notices": 0, "units_affected": 0})
            g["notices"] += 1
            g["units_affected"] += r["units_affected"]
        if group_by == "year":
            return sorted(groups.values(), key=lambda g: g["key"])
        return sorted(groups.values(), key=lambda g: (-g["notices"], g["key"]))


class BrokenRepo:
    """Storage that is down: every method raises."""

    def search(self, *args):
        raise RuntimeError("database is on fire")
    get = summary = search


class FailingFirst(InMemoryRepo):
    """Storage that fails its first `failures` calls, then behaves."""

    def __init__(self, failures):
        super().__init__()
        self.failures = failures

    def get(self, recall_number):
        if len(self.calls) < self.failures:
            self.calls.append("get (failed)")
            raise TransientStorageError("connection lost")
        return super().get(recall_number)


def run(name, inputs, repo):
    """Call execute_tool the way the agent will, and check the contract every time:
    a JSON string that decodes to exactly {ok, data, error}."""
    text = execute_tool(name, inputs, repo=repo)
    assert isinstance(text, str), f"execute_tool returned {type(text).__name__}, not str"
    envelope = json.loads(text)
    assert set(envelope) == {"ok", "data", "error"}, f"unexpected keys {sorted(envelope)}"
    if envelope["ok"]:
        assert envelope["error"] is None, "error must be null on success"
    else:
        assert envelope["data"] is None and envelope["error"], "a failure needs data null and an error text"
    return envelope


# ---- valid inputs, one or more per tool -----------------------------------------

def test_search_valid():
    """search_notices: valid query finds both hummus notices, newest first"""
    result = run("search_notices", {"query": "hummus"}, InMemoryRepo())
    assert result["ok"] is True
    numbers = [n["recall_number"] for n in result["data"]["notices"]]
    assert numbers == ["F-0011-2025", "F-0010-2025"], numbers
    assert result["data"]["count"] == 2
    assert result["data"]["notices"][0]["firm"]["name"] == "Meadow Bakery Inc."


def test_search_category_and_limit():
    """search_notices: category filter and limit are applied"""
    repo = InMemoryRepo()
    by_category = run("search_notices", {"query": "hummus", "category": "Mislabeling"}, repo)
    assert [n["recall_number"] for n in by_category["data"]["notices"]] == ["F-0010-2025"]
    limited = run("search_notices", {"query": "oz", "limit": 2}, repo)
    assert limited["data"]["count"] == 2, limited["data"]["count"]


def test_get_notice_valid():
    """get_notice: valid recall number returns that notice and its firm"""
    result = run("get_notice", {"recall_number": "F-0001-2025"}, InMemoryRepo())
    assert result["ok"] is True
    assert result["data"]["product_name"] == "Blue Heron Enoki Mushrooms, 32 oz tub"
    assert result["data"]["units_affected"] == 8019
    assert result["data"]["firm"]["state"] == "GA"


def test_summary_by_category():
    """recall_summary: by category, counts and unit totals add up"""
    result = run("recall_summary", {"group_by": "category"}, InMemoryRepo())
    assert result["ok"] is True
    data = result["data"]
    assert data["total_notices"] == 6 and data["group_count"] == 3
    assert data["total_units_affected"] == 8019 + 6038 + 4057 + 500 + 1200 + 3114
    top = data["groups"][0]
    assert top == {"key": "Undeclared Allergen", "notices": 3, "units_affected": 8019 + 6038 + 3114}, top


def test_summary_year_filter():
    """recall_summary: by state for one year only counts that year"""
    result = run("recall_summary", {"group_by": "state", "year": 2025}, InMemoryRepo())
    assert result["data"]["total_notices"] == 3
    assert {g["key"]: g["notices"] for g in result["data"]["groups"]} == {"AZ": 2, "GA": 1}


# ---- the three invalid inputs documented in Part 3 --------------------------------

def test_search_rejects_limit_500():
    """search_notices: limit 500 is rejected (Part 3 case 1) and storage is not touched"""
    repo = InMemoryRepo()
    result = run("search_notices", {"query": "peanut butter", "limit": 500}, repo)
    assert result["ok"] is False
    assert "limit" in result["error"] and "20" in result["error"], result["error"]
    assert repo.calls == [], f"storage was called: {repo.calls}"


def test_get_notice_rejects_bad_number():
    """get_notice: recall_number 'ABC-12' is rejected (Part 3 case 2) before any lookup"""
    repo = InMemoryRepo()
    result = run("get_notice", {"recall_number": "ABC-12"}, repo)
    assert result["ok"] is False
    assert "recall_number" in result["error"] and "pattern" in result["error"], result["error"]
    assert repo.calls == []


def test_summary_rejects_unknown_group():
    """recall_summary: group_by 'color' is rejected (Part 3 case 3)"""
    repo = InMemoryRepo()
    result = run("recall_summary", {"group_by": "color"}, repo)
    assert result["ok"] is False
    assert "group_by" in result["error"], result["error"]
    assert repo.calls == []


# ---- errors must not crash -------------------------------------------------------

def test_get_notice_not_found():
    """get_notice: well-formed but unknown number -> ok false, 'not found'"""
    repo = InMemoryRepo()
    result = run("get_notice", {"recall_number": "F-9999-2026"}, repo)
    assert result["ok"] is False and "not found" in result["error"], result
    assert repo.calls == ["get"], "this one is valid input, so storage is asked"


def test_unknown_tool_and_bad_inputs():
    """execute_tool: unknown tool, unknown argument, missing argument -> ok false"""
    repo = InMemoryRepo()
    assert "unknown tool" in run("delete_notice", {"id": 1}, repo)["error"]
    assert "colour" in run("search_notices", {"query": "hummus", "colour": "red"}, repo)["error"]
    assert "Field required" in run("get_notice", {}, repo)["error"]
    assert repo.calls == []


def test_inputs_as_json_text():
    """execute_tool: inputs may arrive as JSON text; broken JSON -> ok false"""
    repo = InMemoryRepo()
    assert run("get_notice", '{"recall_number": "F-0002-2021"}', repo)["data"]["id"] == 2
    assert run("get_notice", '{"recall_number": "F-0002-2021"', repo)["error"] == "inputs is not valid JSON"
    assert run("get_notice", "[1, 2]", repo)["ok"] is False


def test_storage_error_becomes_envelope():
    """execute_tool: storage that raises -> ok false, no exception escapes"""
    for name, inputs in [("search_notices", {"query": "hummus"}),
                         ("get_notice", {"recall_number": "F-0001-2025"}),
                         ("recall_summary", {"group_by": "year"})]:
        result = run(name, inputs, BrokenRepo())
        assert result["ok"] is False
        assert "could not be completed" in result["error"] and "on fire" in result["error"], result["error"]


# ---- the Part 3 retry policy, without waiting ------------------------------------

def test_retry_recovers():
    """retry policy: one transient failure, then success on attempt 2 after a 0.1 s wait"""
    waits = []
    repo = RetryingRepo(FailingFirst(failures=1), DEFAULT_POLICY, sleep=waits.append)
    result = run("get_notice", {"recall_number": "F-0001-2025"}, repo)
    assert result["ok"] is True
    assert [a["outcome"] for a in repo.last_attempts] == ["failed", "ok"]
    assert waits == [0.1], waits


def test_retries_exhausted():
    """retry policy: three failures -> clean ok false, waits were 0.1 s then 0.2 s"""
    waits = []
    repo = RetryingRepo(FailingFirst(failures=99), DEFAULT_POLICY, sleep=waits.append)
    result = run("get_notice", {"recall_number": "F-0001-2025"}, repo)
    assert result["ok"] is False and "failed 3 times" in result["error"], result
    assert len(repo.last_attempts) == 3 and waits == [0.1, 0.2], (repo.last_attempts, waits)


# ---- proof that the run was offline ------------------------------------------------

def test_ran_offline():
    """offline: no database driver, ORM or model client was imported by this run"""
    loaded = [m for m in ("sqlalchemy", "pymysql", "ollama", "httpx") if m in sys.modules]
    assert loaded == [], f"these were imported: {loaded}"


TESTS = [
    test_search_valid,
    test_search_category_and_limit,
    test_get_notice_valid,
    test_summary_by_category,
    test_summary_year_filter,
    test_search_rejects_limit_500,
    test_get_notice_rejects_bad_number,
    test_summary_rejects_unknown_group,
    test_get_notice_not_found,
    test_unknown_tool_and_bad_inputs,
    test_inputs_as_json_text,
    test_storage_error_becomes_envelope,
    test_retry_recovers,
    test_retries_exhausted,
    test_ran_offline,          # keep last: it inspects what the tests above imported
]


def main():
    logging.disable(logging.CRITICAL)        # rejected calls log to stderr; keep the report clean
    print(f"{config.DEMO_NAME} | DATA 260 HW5 Part 4 | {config.PREFIX} | offline tool tests | "
          f"{datetime.now():%Y-%m-%d %H:%M:%S}\n")
    passed = 0
    for number, test in enumerate(TESTS, start=1):
        label = f"{number:02d} {test.__doc__.strip()}"
        try:
            test()
        except AssertionError as exc:
            line = traceback.extract_tb(exc.__traceback__)[-1].line      # the assert that failed
            print(f"FAIL  {label}\n        {line}" + (f"\n        got: {exc}" if str(exc) else ""))
        except Exception as exc:
            print(f"FAIL  {label}\n        unexpected {type(exc).__name__}: {exc}")
        else:
            print(f"PASS  {label}")
            passed += 1
    print(f"\n{passed}/{len(TESTS)} tests passed")
    sys.exit(0 if passed == len(TESTS) else 1)


if __name__ == "__main__":
    main()
