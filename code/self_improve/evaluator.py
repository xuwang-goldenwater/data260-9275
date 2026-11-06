"""
DATA 260 HW9 Part 4 - Evaluator Agent.

Checks an answer against reference_notices.json (the ground truth) and returns

    {"result": "PASS" | "REVISE", "explanation": "...", "feedback": "..." | None,
     "failure_type": None | "missing_field" | "wrong_value" | "fabricated_not_found"
                     | "answered_off_domain",
     "question_kind": "record" | "not_found" | "off_domain"}

Deterministic on purpose (lecture: "an agent can improve only when its evaluator can
reliably distinguish a better result from a worse one"). HW8 showed a 3b model as
judge rejecting a correct answer; a rule cannot be talked into a wrong verdict.

Feedback names WHAT is wrong (which field, which number), never the correct value,
so a revision has to look the fact up again instead of copying it from the evaluator.

    python code/self_improve/evaluator.py      # self-test on hand-written answers
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_FILE = ROOT / "reports/hw09/part4/reference_notices.json"
RECALL_NUMBER = re.compile(r"\bF-\d{4}-\d{4}\b", re.IGNORECASE)

# question keyword -> field it asks for (order matters: state before firm)
FIELD_PATTERNS = [
    ("firm_state",     re.compile(r"\bwhich state\b|\blocated\b", re.I)),
    ("firm_name",      re.compile(r"\bwhich (firm|company)\b|\bwho issued\b", re.I)),
    ("units_affected", re.compile(r"\bunits?\b", re.I)),
    ("recall_date",    re.compile(r"\bwhen\b|\bdate\b", re.I)),
    ("product_name",   re.compile(r"\bproduct\b", re.I)),
    ("category",       re.compile(r"\bcategory\b", re.I)),
]
NOT_FOUND = re.compile(r"not found|no record|does not exist|doesn't exist|no such|"
                       r"could not find|couldn't find|not in the (recall )?database|"
                       r"no recall notice|no information", re.I)
DECLINE = re.compile(r"only answer|can only|outside|out of scope|not related|unrelated|"
                     r"cannot answer|can't answer|unable to answer|not able to answer", re.I)
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin",
    "WY": "Wyoming"}


def load_reference() -> dict:
    data = json.loads(REFERENCE_FILE.read_text())
    return {r["recall_number"]: r for r in data["records"]}


def asked_fields(question: str) -> list[str]:
    return [f for f, pat in FIELD_PATTERNS if pat.search(question)]


def dates_in(text: str) -> set[str]:
    """ISO dates plus 'May 29, 2023' / '29 May 2023', all as YYYY-MM-DD."""
    found = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text))
    for m, d, y in re.findall(r"\b([A-Za-z]+)\.? (\d{1,2}),? (\d{4})\b", text):
        if m.lower() in MONTHS:
            found.add(date(int(y), MONTHS[m.lower()], int(d)).isoformat())
    for d, m, y in re.findall(r"\b(\d{1,2}) ([A-Za-z]+),? (\d{4})\b", text):
        if m.lower() in MONTHS:
            found.add(date(int(y), MONTHS[m.lower()], int(d)).isoformat())
    return found


def states(text: str) -> set[str]:
    """Two-letter codes plus full state names, all as codes."""
    codes = {c for c in re.findall(r"\b([A-Z]{2})\b", text) if c in STATES}
    lower = text.lower()
    codes |= {c for c, name in STATES.items() if name.lower() in lower}
    return codes


def states_field(answer: str, value: str) -> bool:
    return value in states(answer)


def contains_value(field: str, answer: str, value) -> bool:
    a = answer.lower()
    if field == "units_affected":
        return str(value) in re.findall(r"\d+", answer.replace(",", ""))
    if field == "recall_date":
        return value in dates_in(answer)
    if field == "firm_state":
        return states_field(answer, value)
    if field == "product_name":
        return value.split(",")[0].lower() in a           # brand + product, size optional
    return str(value).lower() in a                          # firm_name, category


def invented_numbers(answer: str, record: dict) -> list[str]:
    """Numbers in the answer that appear nowhere in the record (recall number removed)."""
    allowed = set(re.findall(r"\d+", " ".join(str(v) for v in record.values())))
    for iso in dates_in(answer):                          # 'May 29, 2023' -> 29 and 2023 ok
        allowed |= set(iso.split("-")) | {str(int(p)) for p in iso.split("-")}
    text = RECALL_NUMBER.sub(" ", answer).replace(",", "")
    return [n for n in re.findall(r"\d+", text) if n not in allowed]


def evaluate(question: str, answer: str, reference: dict) -> dict:
    numbers = [n.upper() for n in RECALL_NUMBER.findall(question)]

    # --- off-domain: no recall number in the question ---------------------------
    if not numbers:
        if DECLINE.search(answer):
            return _pass("off_domain", "The answer declines a question outside recall notices.")
        return _revise("off_domain", "answered_off_domain",
                       "The question is not about recall notices, but the answer gives "
                       "information that is not in the reference dataset.",
                       "Do not answer it. Say that you can only answer questions about "
                       "grocery recall notices.")

    record = reference.get(numbers[0])

    # --- recall number that is not in the reference dataset -----------------------
    if record is None:
        extra = re.findall(r"\d+", RECALL_NUMBER.sub(" ", answer).replace(",", ""))
        if NOT_FOUND.search(answer) and not extra:
            return _pass("not_found", f"{numbers[0]} is not in the reference dataset and "
                                      "the answer says it was not found.")
        return _revise("not_found", "fabricated_not_found",
                       f"{numbers[0]} is not in the reference dataset, but the answer "
                       "gives details for it as if it existed.",
                       f"Recall {numbers[0]} does not exist. Say it was not found and do "
                       "not give any product, firm, units or date.")

    # --- a real record: every asked field present, no invented numbers ------------
    fields = asked_fields(question)
    missing = [f for f in fields if not contains_value(f, answer, record[f])]
    invented = invented_numbers(answer, record)
    if not missing and not invented:
        return _pass("record", f"All asked fields ({', '.join(fields)}) match the reference "
                               f"record for {numbers[0]}.")
    problems, feedback = [], []
    if missing:
        problems.append(f"missing or wrong: {', '.join(missing)}")
        feedback.append(f"The answer does not correctly state {', '.join(missing)}. "
                        "Read that field from the record again and state it.")
    if invented:
        problems.append(f"numbers not in the record: {invented}")
        feedback.append(f"The answer contains numbers that are not in the record "
                        f"({', '.join(invented)}). Remove them.")
    ftype = "missing_field" if missing and len(missing) < len(fields) else "wrong_value"
    return _revise("record", ftype,
                   f"{numbers[0]}: " + "; ".join(problems) + ".", " ".join(feedback))


def _pass(kind: str, explanation: str) -> dict:
    return {"result": "PASS", "explanation": explanation, "feedback": None,
            "failure_type": None, "question_kind": kind}


def _revise(kind: str, ftype: str, explanation: str, feedback: str) -> dict:
    return {"result": "REVISE", "explanation": explanation, "feedback": feedback,
            "failure_type": ftype, "question_kind": kind}


if __name__ == "__main__":
    print("Xu Wang | DATA 260 HW9 Part 4 | Evaluator self-test")
    ref = load_reference()
    r = ref["F-4837-2023"]          # Coastal Catch Baby Spinach, 2023-05-29, 1203, Heartland Farms LLC, CO
    two = next(n for n in ref.values() if n["recall_number"] == "F-2764-2022")
    tests = [
        ("When was recall F-4837-2023 issued?",
         "Recall F-4837-2023 was issued on May 29, 2023.", "PASS"),
        ("When was recall F-4837-2023 issued?",
         "Recall F-4837-2023 was issued on 2023-06-12.", "REVISE"),
        ("Which firm issued recall F-2764-2022, and how many units were affected?",
         f"Recall F-2764-2022 was issued by {two['firm_name']}.", "REVISE"),
        ("Which firm issued recall F-2764-2022, and how many units were affected?",
         f"{two['firm_name']} issued it; {two['units_affected']:,} units were affected.", "PASS"),
        ("When was recall F-9873-2024 issued?",
         "Recall F-9873-2024 was not found in the recall database.", "PASS"),
        ("When was recall F-9873-2024 issued?",
         "Recall F-9873-2024 was issued on March 3, 2024.", "REVISE"),
        ("What is the capital of France?", "The capital of France is Paris.", "REVISE"),
        ("What is the capital of France?",
         "I can only answer questions about grocery recall notices.", "PASS"),
        ("In which state is the firm behind recall F-4837-2023 located?",
         f"The firm, {r['firm_name']}, is located in Colorado.", "PASS"),
    ]
    ok = 0
    for q, a, want in tests:
        v = evaluate(q, a, ref)
        ok += v["result"] == want
        print(f"\n[{'ok' if v['result'] == want else 'XX'}] {v['result']:<6} "
              f"({v['failure_type']})  Q: {q}\n    A: {a}\n    explanation: {v['explanation']}"
              + (f"\n    feedback: {v['feedback']}" if v["feedback"] else ""))
    print(f"\n{ok}/{len(tests)} as expected")
