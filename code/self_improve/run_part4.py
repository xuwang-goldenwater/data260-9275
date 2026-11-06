"""
DATA 260 HW9 Part 4 - runner for the two-agent system.

    python code/self_improve/run_part4.py train      # 4.1 revision + 4.2 lesson creation
    python code/self_improve/run_part4.py validate   # 4.3 keep / remove each lesson
    python code/self_improve/run_part4.py test       # 4.4 four variants on test_data.json

Communication between the agents: run_one() passes the question to the Answering Agent,
the answer to the Evaluator, and the Evaluator's feedback back to the Answering Agent.
The agents never call each other; run_one() is the loop and the stopping rule:
    stop at PASS, or after MAX_ATTEMPTS = 2 answers, whichever comes first.

Rules
  - train starts lessons.json from empty. A failure of the controlled case (drop_field)
    is injected, so it is NOT counted toward a lesson.
  - validate compares single-attempt runs (no repair) without / with each candidate
    lesson, so the lesson's own effect is visible; no lessons are created there.
  - test only reads lessons; nothing is created, kept or removed from test results.
Results go to reports/hw09/part4/results/.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from answerer import AnsweringAgent
from evaluator import evaluate, load_reference
from lessons import LESSONS_FILE, LessonStore

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "reports/hw09/part4"
RESULTS = DATA / "results"
MAX_ATTEMPTS = 2
CONTROLLED = {"train_05": "units_affected"}   # 4.1: first answer misses the units field


def load(split: str) -> list[dict]:
    return json.loads((DATA / f"{split}_data.json").read_text())


def run_one(agent, ref, item, store=None, max_attempts=MAX_ATTEMPTS,
            drop_field=None, learn=False, verbose=False) -> dict:
    q, qid = item["question"], item["id"]
    number, record = agent.lookup(q)
    feats = sorted(agent.features(q, number, record))
    lessons = store.relevant(feats) if store else []
    t0 = time.perf_counter()
    attempts, previous, feedback = [], None, None
    if verbose:
        print(f"\n=== {qid}: {q}")
        print(f"    features: {feats}   lessons loaded: {[x['lesson_id'] for x in lessons] or 'none'}")
        if drop_field:
            print(f"    CONTROLLED CASE: '{drop_field}' hidden from the record on attempt 1")
    for n in range(1, max_attempts + 1):
        out = agent.answer(q, lessons=lessons, previous=previous, feedback=feedback,
                           drop_field=drop_field)
        verdict = evaluate(q, out["answer"], ref)
        attempts.append({"attempt": n, "answer": out["answer"], **verdict,
                         "answer_ms": out["latency_ms"]})
        if verbose:
            print(f"  attempt {n} answer : {out['answer']}")
            print(f"  evaluator        : {verdict['result']} - {verdict['explanation']}")
            if verdict["feedback"]:
                print(f"  feedback         : {verdict['feedback']}")
        if verdict["result"] == "REVISE" and learn and store and not drop_field:
            new = store.record_failure(verdict["failure_type"], qid)
            if new and verbose:
                print(f"  >>> repeated failure '{verdict['failure_type']}' "
                      f"({', '.join(new['created_from'])}) -> NEW LESSON {new['lesson_id']}: "
                      f"{new['correction']}")
        if verdict["result"] == "PASS":
            break
        previous, feedback = out["answer"], verdict["feedback"]
    final = attempts[-1]
    if verbose:
        print(f"  FINAL: {final['result']} after {len(attempts)} attempt(s)")
    return {"id": qid, "question": q, "features": feats,
            "lessons_loaded": [x["lesson_id"] for x in lessons], "attempts": attempts,
            "n_attempts": len(attempts), "final_result": final["result"],
            "final_answer": final["answer"], "question_kind": final["question_kind"],
            "final_failure": final["failure_type"],
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}


def save(name: str, payload) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / name).write_text(json.dumps(payload, indent=2))
    print(f"\nsaved {(RESULTS / name).relative_to(ROOT)}")


# ---- 4.1 + 4.2 -----------------------------------------------------------------------
def train() -> None:
    if LESSONS_FILE.exists():
        LESSONS_FILE.unlink()                       # lessons come only from this run
    agent, ref, store = AnsweringAgent(), load_reference(), LessonStore()
    rows = [run_one(agent, ref, it, store=store, drop_field=CONTROLLED.get(it["id"]),
                    learn=True, verbose=True) for it in load("training")]
    print("\n=== training summary ===")
    for r in rows:
        print(f"{r['id']}  {r['final_result']:<6} attempts={r['n_attempts']}  "
              f"first={r['attempts'][0]['result']:<6} lessons={r['lessons_loaded']}")
    print(f"\nlessons.json now holds {len(store.lessons)} lesson(s):")
    for x in store.lessons:
        print(f"  {x['lesson_id']} [{x['failure_type']}, from {x['created_from']}] {x['correction']}")
    save("train.json", {"run_at": datetime.now().isoformat(timespec="seconds"), "rows": rows,
                        "lessons": store.lessons})


# ---- 4.3 -------------------------------------------------------------------------------
def run_set(agent, ref, items, store, max_attempts) -> list[dict]:
    return [run_one(agent, ref, it, store=store, max_attempts=max_attempts) for it in items]


def validate() -> None:
    agent, ref, items = AnsweringAgent(), load_reference(), load("validation")
    store = LessonStore(statuses=("kept",))
    for x in store.lessons:                     # each validation run decides from scratch
        x["status"], x["validation"] = "candidate", None
    store.save()
    unrelated = {"off_domain", "not_found"}
    report = []
    before = run_set(agent, ref, items, store, max_attempts=1)
    first_before = before
    for lesson in [x for x in store.lessons if x["status"] == "candidate"]:
        lesson["status"] = "testing"
        store.statuses = ("kept", "testing")
        after = run_set(agent, ref, items, store, max_attempts=1)
        b_pass = {r["id"] for r in before if r["final_result"] == "PASS"}
        a_pass = {r["id"] for r in after if r["final_result"] == "PASS"}
        b_unsup = sum(r["question_kind"] in unrelated and r["final_result"] != "PASS" for r in before)
        a_unsup = sum(r["question_kind"] in unrelated and r["final_result"] != "PASS" for r in after)
        checks = {
            "failures_improve_or_same": len(items) - len(a_pass) <= len(items) - len(b_pass),
            "previously_correct_still_correct": b_pass <= a_pass,
            "no_new_unsupported_answers_on_unrelated": a_unsup <= b_unsup,
        }
        keep = all(checks.values())
        lesson["status"] = "kept" if keep else "removed"
        lesson["validation"] = {"pass_before": len(b_pass), "pass_after": len(a_pass),
                                "of": len(items), "unsupported_before": b_unsup,
                                "unsupported_after": a_unsup,
                                "regressions": sorted(b_pass - a_pass),
                                "fixed": sorted(a_pass - b_pass), **checks}
        store.statuses = ("kept",)
        store.save()
        print(f"\n=== {lesson['lesson_id']} ({lesson['failure_type']}) -> "
              f"{'KEPT' if keep else 'REMOVED'}")
        print(f"    validation PASS {len(b_pass)}/{len(items)} -> {len(a_pass)}/{len(items)}   "
              f"fixed {sorted(a_pass - b_pass)}   regressions {sorted(b_pass - a_pass)}   "
              f"unsupported on unrelated {b_unsup} -> {a_unsup}")
        for k, v in checks.items():
            print(f"    {'ok ' if v else 'NO '} {k}")
        for r in after:
            if lesson["lesson_id"] in r["lessons_loaded"]:
                print(f"    reuse: {r['id']} \"{r['question']}\"  loaded {r['lessons_loaded']}")
                print(f"           answer: {r['final_answer'][:140]}  -> {r['final_result']}")
        report.append({"lesson_id": lesson["lesson_id"], "kept": keep, "after": after})
        if keep:
            before = after                         # next lesson is judged on top of this one
    print("\nlessons.json:")
    for x in store.lessons:
        print(f"  {x['lesson_id']} {x['status']:<8} use_count={x['use_count']}  {x['failure_pattern']}")
    save("validate.json", {"run_at": datetime.now().isoformat(timespec="seconds"),
                           "baseline_without_new_lessons": first_before, "report": report,
                           "lessons": store.lessons})


# ---- 4.4 -------------------------------------------------------------------------------
VARIANTS = [
    ("Baseline", None, 1),
    ("Evaluator Repair", None, 2),
    ("Lesson Memory", ("candidate", "kept", "removed"), 2),     # every saved lesson
    ("Validated Improvement", ("kept",), 2),                    # only lessons that passed 4.3
]


def test() -> None:
    agent, ref, items = AnsweringAgent(), load_reference(), load("test")
    table, all_rows = [], {}
    for name, statuses, max_attempts in VARIANTS:
        store = LessonStore(statuses=statuses) if statuses else None
        print(f"\n=== {name} ===")
        rows = run_set(agent, ref, items, store, max_attempts)
        for r in rows:
            print(f"  {r['id']}  {r['final_result']:<6} attempts={r['n_attempts']} "
                  f"lessons={r['lessons_loaded']}  {r['latency_ms']:>8.0f} ms  "
                  f"{r['final_failure'] or ''}")
        correct = sum(r["final_result"] == "PASS" for r in rows)
        table.append({"variant": name, "correct": correct, "incorrect": len(rows) - correct,
                      "avg_attempts": sum(r["n_attempts"] for r in rows) / len(rows),
                      "avg_latency_ms": sum(r["latency_ms"] for r in rows) / len(rows)})
        all_rows[name] = rows
    print(f"\n=== Part 4.4 results on test_data.json ({len(items)} questions) ===")
    print(f"{'Variant':<22} {'Correct':>8} {'Incorrect':>10} {'Avg attempts':>13} {'Avg latency':>12}")
    for t in table:
        print(f"{t['variant']:<22} {t['correct']:>8} {t['incorrect']:>10} "
              f"{t['avg_attempts']:>13.2f} {t['avg_latency_ms'] / 1000:>10.2f} s")
    save("test.json", {"run_at": datetime.now().isoformat(timespec="seconds"),
                       "table": table, "rows": all_rows})


if __name__ == "__main__":
    print("Xu Wang | DATA 260 HW9 Part 4 | two-agent system | qwen2.5:3b | PREFIX s9275")
    {"train": train, "validate": validate, "test": test}[sys.argv[1]]()
