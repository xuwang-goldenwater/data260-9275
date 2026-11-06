"""
DATA 260 HW9 Part 4.2 - reusable lessons (reports/hw09/part4/lessons.json).

A lesson is created when the Evaluator reports the SAME failure type for the 2nd time
(a repeated failure pattern), not after a single slip. Each failure type has one
lesson text, written so it carries no answer values - only what to do.

Lesson fields
    lesson_id, failure_pattern, correction, created_at, use_count     (required)
    applies_to       question feature that makes the lesson relevant (answerer.features)
    failure_type     Evaluator failure type it came from
    created_from     the question ids whose failures triggered it
    status           candidate -> kept | removed   (decided by 4.3 validation)
    validation       before/after numbers from 4.3

Relevance: before answering, the agent gets only lessons whose applies_to is one of the
question's features (a multi-part question never sees the off-domain lesson).
Every time a lesson is put into a prompt, its use_count goes up and the file is saved.

    python code/self_improve/lessons.py     # offline self-test, writes nothing
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LESSONS_FILE = ROOT / "reports/hw09/part4/lessons.json"
REPEAT = 2   # failures of the same type before a lesson is created

TEMPLATES = {
    "answered_off_domain": {
        "applies_to": "no_recall_number",
        "failure_pattern": "The question is not about grocery recall notices and the answer "
                           "still answers it.",
        "correction": "Reply that you can only answer questions about grocery recall notices. "
                      "Do not answer the question itself."},
    "fabricated_not_found": {
        "applies_to": "record_not_found",
        "failure_pattern": "The recall number is not in the database and the answer still "
                           "gives details for it.",
        "correction": "Say that this recall number was not found in the database. Do not give "
                      "any product, firm, units or date."},
    "missing_field": {
        "applies_to": "multi_part",
        "failure_pattern": "The question asks for two things and the answer gives only one.",
        "correction": "Before answering, list every item the question asks for, then state "
                      "each value from the database record."},
    "wrong_value": {
        "applies_to": "record_found",
        "failure_pattern": "The answer states a value that differs from the database record.",
        "correction": "Copy every value exactly as it appears in the database record. Do not "
                      "guess, round or add numbers that are not in the record."},
}


class LessonStore:
    def __init__(self, path: Path = LESSONS_FILE, statuses: tuple[str, ...] = ("candidate", "kept")):
        self.path = path
        self.statuses = statuses            # which lessons this run may load
        self.lessons: list[dict] = json.loads(path.read_text()) if path.exists() else []
        self.failures: Counter = Counter()  # failure type -> count, this run
        self.sources: dict[str, list[str]] = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.lessons, indent=2))

    def relevant(self, features: list[str]) -> list[dict]:
        """Lessons for this question; each one loaded counts as one use."""
        picked = [x for x in self.lessons
                  if x["status"] in self.statuses and x["applies_to"] in features]
        for x in picked:
            x["use_count"] += 1
        if picked:
            self.save()
        return picked

    def record_failure(self, failure_type: str, question_id: str) -> dict | None:
        """Count one Evaluator failure; return the new lesson if this one repeats a pattern."""
        self.failures[failure_type] += 1
        self.sources.setdefault(failure_type, []).append(question_id)
        exists = any(x["failure_type"] == failure_type for x in self.lessons)
        if self.failures[failure_type] < REPEAT or exists or failure_type not in TEMPLATES:
            return None
        t = TEMPLATES[failure_type]
        lesson = {"lesson_id": f"lesson_{len(self.lessons) + 1:03d}",
                  "failure_pattern": t["failure_pattern"], "correction": t["correction"],
                  "created_at": date.today().isoformat(), "use_count": 0,
                  "applies_to": t["applies_to"], "failure_type": failure_type,
                  "created_from": list(self.sources[failure_type]),
                  "status": "candidate", "validation": None}
        self.lessons.append(lesson)
        self.save()
        return lesson


if __name__ == "__main__":
    import tempfile
    print("Xu Wang | DATA 260 HW9 Part 4.2 | LessonStore self-test")
    with tempfile.TemporaryDirectory() as tmp:
        s = LessonStore(Path(tmp) / "lessons.json")
        print("1st off-domain failure ->", s.record_failure("answered_off_domain", "train_01"))
        new = s.record_failure("answered_off_domain", "train_07")
        print("2nd off-domain failure ->", json.dumps(new, indent=2))
        print("3rd off-domain failure ->", s.record_failure("answered_off_domain", "x"),
              "(lesson exists, no duplicate)")
        print("relevant for ['no_recall_number']:",
              [x["lesson_id"] for x in s.relevant(["no_recall_number"])])
        print("relevant for ['multi_part', 'record_found']:",
              [x["lesson_id"] for x in s.relevant(["multi_part", "record_found"])])
        print("use_count now:", s.lessons[0]["use_count"])
