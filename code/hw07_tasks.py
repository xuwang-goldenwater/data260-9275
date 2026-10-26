"""
HW7 Parts 2-3 - the three fixed verification tasks, the error-recovery case,
and one deterministic check per task.

A check reads only the run record (the tool calls, what each tool returned,
and the final answer). No model is involved, so the same run always gets the
same verdict. Each check returns
    {"passed", "chain_ok", "answer_ok", "reasons", "unsupported_claims"}
chain_ok    the required tool calls were made, in an order that uses the
            earlier results (search -> detail, summary -> example)
answer_ok   the final answer states the facts those tool results contain
unsupported_claims  recall numbers in the answer that no tool ever returned
"""
from __future__ import annotations

import re

RECALL_RX = re.compile(r"F-\d{4}-\d{4}")


# ---- helpers over a run record ----------------------------------------------------

def ok_results(run: dict, tool: str) -> list[tuple[dict, dict]]:
    """(inputs, data) for every call of `tool` that ran and returned ok: true."""
    out = []
    for c in run["calls"]:
        res = c.get("result")
        if c["tool"] == tool and res and res.get("ok"):
            out.append((c["inputs"], res["data"]))
    return out


def observed_recall_numbers(run: dict) -> set[str]:
    seen = set()
    for c in run["calls"]:
        if c.get("result") and c["result"].get("ok"):
            seen.update(RECALL_RX.findall(str(c["result"]["data"])))
    return seen


def unsupported(run: dict) -> list[str]:
    return sorted(set(RECALL_RX.findall(run["final_answer"])) - observed_recall_numbers(run))


def verdict(chain_ok: bool, answer_ok: bool, reasons: list[str], run: dict) -> dict:
    claims = unsupported(run)
    if claims:
        reasons.append(f"unsupported recall numbers in answer: {claims}")
    if run["stop_reason"] != "completed":
        reasons.append(f"run did not complete (stop reason {run['stop_reason']})")
    passed = chain_ok and answer_ok and not claims and run["stop_reason"] == "completed"
    return {"passed": passed, "chain_ok": chain_ok, "answer_ok": answer_ok,
            "reasons": reasons or ["all checks passed"], "unsupported_claims": claims}


# ---- task A: search, then detail-lookup the first result -------------------------

def verify_a(run: dict) -> dict:
    reasons = []
    searches = [d for _, d in ok_results(run, "search_notices") if d["count"] > 0]
    if not searches:
        return verdict(False, False, ["no search_notices call returned results"], run)
    first = searches[0]["notices"][0]["recall_number"]
    details = [d for inp, d in ok_results(run, "get_notice") if d["recall_number"] == first]
    chain_ok = bool(details)
    if not chain_ok:
        reasons.append(f"get_notice was not called on the first search result {first}")
        return verdict(False, False, reasons, run)
    email = details[0]["firm"].get("contact_email", "")
    answer = run["final_answer"].lower()
    answer_ok = first.lower() in answer and email.lower() in answer
    if not answer_ok:
        reasons.append(f"answer must name {first} and the firm email {email}")
    return verdict(chain_ok, answer_ok, reasons, run)


# ---- task B: aggregate question, then one supporting example ----------------------

def verify_b(run: dict) -> dict:
    reasons = []
    summaries = [d for inp, d in ok_results(run, "recall_summary")
                 if d["group_by"] == "category" and d["year"] == 2025]
    if not summaries:
        return verdict(False, False, ["no recall_summary(group_by=category, year=2025)"], run)
    top = max(summaries[0]["groups"], key=lambda g: g["notices"])
    examples = [d for inp, d in ok_results(run, "search_notices")
                if inp.get("category") == top["key"] and d["count"] > 0]
    chain_ok = bool(examples)
    if not chain_ok:
        reasons.append(f"no search_notices in the top category {top['key']!r} returned an example")
        return verdict(False, False, reasons, run)
    example_numbers = {n["recall_number"] for d in examples for n in d["notices"]}
    answer = run["final_answer"]
    answer_ok = (top["key"].lower() in answer.lower() and str(top["notices"]) in answer
                 and any(r in answer for r in example_numbers))
    if not answer_ok:
        reasons.append(f"answer must name {top['key']}, its count {top['notices']} "
                       f"and one example recall number from the search")
    return verdict(chain_ok, answer_ok, reasons, run)


# ---- task C: compare two entities (search + two detail lookups) -------------------

def verify_c(run: dict) -> dict:
    reasons = []
    searches = [d for _, d in ok_results(run, "search_notices") if d["count"] >= 2]
    if not searches:
        return verdict(False, False, ["no search_notices call returned two results"], run)
    pair = [n["recall_number"] for n in searches[0]["notices"][:2]]
    details = {d["recall_number"]: d for _, d in ok_results(run, "get_notice")}
    missing = [r for r in pair if r not in details]
    chain_ok = not missing
    if missing:
        reasons.append(f"get_notice missing for {missing}")
        return verdict(False, False, reasons, run)
    units = {r: details[r]["units_affected"] for r in pair}
    best = max(units.values())
    winners = [r for r, u in units.items() if u == best]
    answer = run["final_answer"]
    # both recall numbers named, and the larger unit count stated
    answer_ok = all(r in answer for r in pair) and (str(best) in answer or f"{best:,}" in answer)
    if not answer_ok:
        reasons.append(f"answer must name both {pair} and say {winners[0]} affected more "
                       f"units ({best} vs {min(units.values())})")
    return verdict(chain_ok, answer_ok, reasons, run)


TASKS = {
    "A": {"label": "search, then detail-lookup the first result",
          "question": ("Search for Hummus recall notices, then look up the first result in "
                       "detail and tell me its recall number, the firm that issued it and "
                       "the firm's contact email."),
          "verify": verify_a, "min_tool_calls": 2},
    "B": {"label": "aggregate question, then one supporting example",
          "question": ("Which category had the most recall notices in 2025, and how many? "
                       "Then search for Peanut notices in that category and give one example "
                       "with its recall number."),
          "verify": verify_b, "min_tool_calls": 2},
    "C": {"label": "compare two entities: search + two detail lookups",
          "question": ("Compare the two most recent Chicken Salad recall notices: search for "
                       "them, look up both in detail, and tell me which one affected more "
                       "units, with both recall numbers and unit counts."),
          "verify": verify_c, "min_tool_calls": 3},
}

ERROR_CASE = {
    "label": "nonexistent ID",
    "question": "Give me the full details of recall notice F-9999-2026.",
}


def verify_error_case(run: dict) -> dict:
    """The tool must report not-found, and the agent must answer instead of crashing."""
    lookups = [c for c in run["calls"] if c["tool"] == "get_notice" and c.get("result")]
    not_found = any(not c["result"]["ok"] and "not found" in c["result"]["error"] for c in lookups)
    answered = run["stop_reason"] == "completed" and bool(run["final_answer"])
    return {"passed": not_found and answered, "tool_returned_not_found": not_found,
            "agent_answered": answered}
