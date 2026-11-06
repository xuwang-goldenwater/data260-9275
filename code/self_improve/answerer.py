"""
DATA 260 HW9 Part 4 - Answering Agent.

    answer(question, lessons=[], previous=None, feedback=None, drop_field=None)

1. Look the recall number up in s9275_rel (HW5 MySQLRepo.get) - its own tool, not the
   Evaluator's reference file.
2. Build one prompt: question + record (or "no record") + any lessons it was given
   + (attempt 2 only) its previous answer and the Evaluator's feedback.
3. One call to qwen2.5:3b through the HW1 adapter src/model_client.py, temperature 0.

The system prompt is a plain help-desk prompt with no special rules: whatever the
agent learns about not-found numbers, off-domain questions or multi-part questions
has to come from lessons or feedback, which is what Part 4 measures.

drop_field: the controlled test case (4.1). On attempt 1 that field is removed from
the record the agent sees, so the first answer is reliably incomplete and the
feedback / revision path is exercised. Attempt 2 always gets the full record.

    python code/self_improve/answerer.py "Which firm issued recall F-2764-2022?"
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "code"))

MODEL = "qwen2.5:3b"
SEED = 9275
RECALL_NUMBER = re.compile(r"\bF-\d{4}-\d{4}\b", re.IGNORECASE)

SYSTEM = ("You are a help-desk assistant for a grocery recall-notice database. "
          "Answer the user's question in one or two sentences.")


class AnsweringAgent:
    def __init__(self, model: str = MODEL):
        from model_client import ModelClient
        self.client = ModelClient(model=model, temperature=0.0,
                                  options={"num_ctx": 4096, "seed": SEED})
        self._repo = None

    def lookup(self, question: str) -> tuple[Optional[str], Optional[dict]]:
        """(recall_number or None, flattened record or None)."""
        m = RECALL_NUMBER.search(question)
        if not m:
            return None, None
        number = m.group(0).upper()
        if self._repo is None:
            from domain_tools import MySQLRepo
            self._repo = MySQLRepo()
        n = self._repo.get(number)
        if n is None:
            return number, None
        return number, {"recall_number": n["recall_number"], "product_name": n["product_name"],
                        "category": n["category"], "recall_date": n["recall_date"],
                        "units_affected": n["units_affected"], "firm_name": n["firm"]["name"],
                        "firm_state": n["firm"]["state"]}

    @staticmethod
    def features(question: str, number: Optional[str], record: Optional[dict]) -> set[str]:
        """What kind of question this is - used to pick relevant lessons."""
        if number is None:
            return {"no_recall_number"}
        f = {"recall_lookup"}
        f.add("record_not_found" if record is None else "record_found")
        if ", and " in question or " and " in question.split(number)[-1]:
            f.add("multi_part")
        return f

    def answer(self, question: str, lessons: Optional[list[dict]] = None,
               previous: Optional[str] = None, feedback: Optional[str] = None,
               drop_field: Optional[str] = None) -> dict:
        t0 = time.perf_counter()
        number, record = self.lookup(question)
        shown = dict(record) if record else None
        if shown and drop_field and previous is None:
            shown.pop(drop_field, None)                 # controlled incomplete first attempt

        parts = [f"Question: {question}"]
        if number is None:
            parts.append("Database lookup: the question contains no recall number.")
        elif shown is None:
            parts.append(f"Database lookup: no recall notice {number} in the database.")
        else:
            parts.append("Database record:\n" + "\n".join(f"- {k}: {v}" for k, v in shown.items()))
        if previous is not None:
            parts.append(f"Your previous answer:\n{previous}\n\nEvaluator feedback:\n{feedback}\n\n"
                         "Write a corrected answer.")
        prompt = "\n\n".join(parts)

        # Lessons go into the system message as rules. First validation run (lessons at the
        # end of the user message): the 3b model loaded lesson_001 and still answered
        # "Jane Austen" - a trailing note was ignored. See results/validate_run1_*.json.
        system = SYSTEM
        if lessons:
            system += ("\n\nRules learned from earlier mistakes. Always follow them:\n" +
                       "\n".join(f"- [{x['lesson_id']}] Past mistake: {x['failure_pattern']} "
                                 f"Rule: {x['correction']}" for x in lessons))
        reply = self.client.complete([{"role": "system", "content": system},
                                      {"role": "user", "content": prompt}], max_tokens=200)
        return {"answer": reply.text.strip(), "prompt": prompt, "system": system,
                "features": sorted(self.features(question, number, record)),
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}


if __name__ == "__main__":
    print("Xu Wang | DATA 260 HW9 Part 4 | Answering Agent | qwen2.5:3b")
    q = " ".join(sys.argv[1:]) or "Which firm issued recall F-2764-2022, and how many units were affected?"
    out = AnsweringAgent().answer(q)
    print(f"\n--- prompt ---\n{out['prompt']}\n\n--- answer ({out['latency_ms']} ms) ---\n"
          f"{out['answer']}\n\nfeatures: {out['features']}")
