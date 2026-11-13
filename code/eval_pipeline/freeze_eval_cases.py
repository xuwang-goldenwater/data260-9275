"""
DATA 260 - HW10 Part 3.1: freeze the 20 Writer drafts used to validate the judge.

Source: the Writer drafts of the 50-request latency run (reports/hw10/raw/eval_results.jsonl).
Selection does NOT look at any judge score - it is stratified by question kind and the
Reviewer's verdict only, random.Random(9275):
    record questions   12  (6 the Reviewer approved, 6 it rejected)
    not-found numbers   4
    off-domain          4
Writes, in reports/hw10/:
    eval_cases.json      case_id, trace_id, kind, question, facts, draft  (no scores)
    human_labels.csv     case_id, human_label  - label column left empty for Xu to fill
    labeling_sheet.md    what Xu reads while labelling: rubric + each case, no scores

Rule (Part 3.1): eval_cases.json and the filled human_labels.csv are committed BEFORE
validate_judge.py runs, and the labels are never changed after the judge results exist.

    python code/eval_pipeline/freeze_eval_cases.py
"""

from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code" / "eval_pipeline"))
REPORT = ROOT / "reports/hw10"
RAW = REPORT / "raw"
SEED = 9275
PLAN = [("record", "approved", 6), ("record", "rejected", 6),
        ("not_found", None, 4), ("off_domain", None, 4)]


def main() -> None:
    if (REPORT / "eval_cases.json").exists():
        raise SystemExit("eval_cases.json already exists - the cases are frozen, not re-drawn")
    kind = {q["trace_id"]: q["kind"]
            for q in json.loads((RAW / "latency_questions.json").read_text())["questions"]}
    results = [json.loads(line) for line in (RAW / "eval_results.jsonl").read_text().splitlines()]
    pool = [r for r in results if r["trace_id"] in kind and r.get("draft")]

    rng = random.Random(SEED)
    picked = []
    for k, verdict, n in PLAN:
        group = sorted((r for r in pool if kind[r["trace_id"]] == k
                        and (verdict is None or r["review_status"] == verdict)),
                       key=lambda r: r["trace_id"])
        if len(group) < n:
            raise SystemExit(f"only {len(group)} drafts for {k}/{verdict}, need {n}")
        picked += rng.sample(group, n)
    rng.shuffle(picked)            # so the sheet is not ordered by kind or verdict

    cases = [{"case_id": f"c{i:02d}", "trace_id": r["trace_id"], "kind": kind[r["trace_id"]],
              "question": r["question"], "facts": r["facts"], "draft": r["draft"]}
             for i, r in enumerate(picked, 1)]
    (REPORT / "eval_cases.json").write_text(json.dumps(
        {"source": "reports/hw10/raw/eval_results.jsonl (Writer drafts, latency run)",
         "selection": "stratified by kind and Reviewer verdict, random.Random(9275), no judge scores used",
         "cases": cases}, indent=2))

    with (REPORT / "human_labels.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["case_id", "human_label"])
        for c in cases:
            w.writerow([c["case_id"], ""])

    from judge import HELPFULNESS_RUBRIC
    lines = ["# HW10 Part 3 - labelling sheet (Writer helpfulness, 1-5)", "",
             "Label each draft from the question and the database facts only. Same rubric as the judge:", ""]
    lines += [f"- **{i}** - {t}" for i, t in enumerate(HELPFULNESS_RUBRIC, 1)]
    for c in cases:
        facts = c["facts"]
        if not facts:
            ftxt = "_no database record looked up (no recall number in the question)_"
        elif facts.get("not_found"):
            ftxt = f"_recall {facts['not_found']} does not exist in the database_"
        else:
            ftxt = ", ".join(f"{k}={v}" for k, v in facts.items())
        lines += ["", "---", "", f"## {c['case_id']}", "",
                  f"**Question:** {c['question']}", "", f"**Facts:** {ftxt}", "",
                  f"**Draft:** {c['draft']}", "", "**Your label (1-5):** ____"]
    (REPORT / "labeling_sheet.md").write_text("\n".join(lines) + "\n")
    print(f"{len(cases)} cases -> {REPORT}/eval_cases.json, human_labels.csv (empty), labeling_sheet.md")


if __name__ == "__main__":
    main()
