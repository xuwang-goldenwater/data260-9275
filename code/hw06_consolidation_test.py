"""HW6 Part 4-5: consolidate the 55-line MEMORY.md and grade it against the answer key.

    reports/hw06/memory/MEMORY.original.md       55 lines (committed before this runs)
    reports/hw06/memory/memory_55_key.yaml       expected merges and resolutions (also before)
 -> reports/hw06/memory/MEMORY.consolidated.md   result of the same code path as /compact
 -> reports/hw06/memory/MEMORY.consolidated.compact_report.json
 -> reports/hw06/memory/consolidation_eval.json  which merges/resolutions were right or wrong

Run:  make memory-consolidate      (one model call, ~1-2 min on qwen2.5:3b)
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code"))
import file_memory as fm                      # noqa: E402
from file_memory_cli import FileMemorySession  # noqa: E402

DIR = ROOT / "reports" / "hw06" / "memory"
ORIGINAL = DIR / "MEMORY.original.md"
CONSOLIDATED = DIR / "MEMORY.consolidated.md"
KEY = DIR / "memory_55_key.yaml"


def grade(report: dict, key: dict, facts) -> dict:
    groups = [set(d["lines"]) for d in report["duplicates_merged"]]
    cons = report["contradictions_resolved"]
    superseded = {n for c in cons for n in c["superseded"]}
    text = {f.line: f.text for f in facts}
    out = {"duplicates": {}, "contradictions": {}, "traps": {}, "false_merges": []}

    for name, d in key["duplicates"].items():
        want = set(d["lines"])
        best = max((g & want for g in groups), key=len, default=set())
        out["duplicates"][name] = {
            "topic": d["topic"], "expected_lines": sorted(want), "merged_together": sorted(best),
            "verdict": "merged" if best == want else ("partly merged" if len(best) >= 2 else "not merged")}
    for name, c in key["contradictions"].items():
        hit = next((x for x in cons if c["keep"] in [x["keep"], *x["superseded"]]
                    or set(c["superseded"]) & ({x["keep"]} | set(x["superseded"]))), None)
        if hit is None:
            verdict = "missed (both lines kept, conflict left unresolved)"
        elif hit["keep"] == c["keep"] and set(c["superseded"]) <= set(hit["superseded"]):
            verdict = "correct"
        else:
            verdict = "WRONG (kept the wrong line)"
        out["contradictions"][name] = {"topic": c["topic"], "expected_keep": c["keep"],
                                       "model": hit, "verdict": verdict}
    for name, t in key["traps"].items():
        dropped = [n for n in t["lines"] if n in superseded]
        out["traps"][name] = {
            "topic": t["topic"], "lines": t["lines"],
            "verdict": "correct (both kept)" if not dropped else
                       f"WRONG: superseded {[text[n] for n in dropped]}"}
    # merges that join facts the key says are different (e.g. a unique fact swallowed)
    key_groups = [set(d["lines"]) for d in key["duplicates"].values()]
    for g in groups:
        if not any(g <= k for k in key_groups):
            out["false_merges"].append({"lines": sorted(g), "texts": [text[n] for n in sorted(g)]})
    wrong = [n for n, v in out["contradictions"].items() if not v["verdict"].startswith("correct")]
    wrong += [n for n, v in out["traps"].items() if v["verdict"].startswith("WRONG")]
    out["incorrectly_resolved"] = wrong
    return out


def main() -> None:
    print(f"Xu Wang | DATA 260 HW6 Part 4 | consolidation test | {datetime.now():%Y-%m-%d %H:%M:%S}")
    original = ORIGINAL.read_text(encoding="utf-8")
    key = yaml.safe_load(KEY.read_text(encoding="utf-8"))
    total_lines = len(original.splitlines())
    print(f"original: {total_lines} lines in file, {fm.count_memory_lines(original)} counted, "
          f"{len(fm.fact_lines(original))} facts; due: {fm.needs_consolidation(original)}")

    shutil.copyfile(ORIGINAL, CONSOLIDATED)          # /compact works in place on this copy
    session = FileMemorySession(CONSOLIDATED, fm.AGENT_PATH, "xu_wang")
    print(session.cmd_compact())

    report = json.loads(CONSOLIDATED.with_suffix(".compact_report.json").read_text())
    result = grade(report, key, fm.parse_facts(original))
    after = CONSOLIDATED.read_text(encoding="utf-8")
    result["summary"] = {
        "file_lines_before": total_lines, "file_lines_after": len(after.splitlines()),
        "counted_lines_before": report["lines_before"], "counted_lines_after": report["lines_after"],
        "under_40": report["lines_after"] < fm.MAX_MEMORY_LINES,
        "facts_before": report["facts_before"], "facts_after": report["facts_after"],
        "silently_deleted_lines": report["not_accounted"],
        "plan_errors": report["plan_errors"],
    }
    (DIR / "consolidation_eval.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("\nduplicates:")
    for n, v in result["duplicates"].items():
        print(f"  {n} {v['topic']:<34} {v['verdict']:<14} {v['merged_together']}")
    print("contradictions:")
    for n, v in result["contradictions"].items():
        print(f"  {n} {v['topic']:<34} {v['verdict']}")
    print("traps:")
    for n, v in result["traps"].items():
        print(f"  {n} {v['topic'][:34]:<34} {v['verdict']}")
    if result["false_merges"]:
        print(f"false merges: {result['false_merges']}")
    print(f"\nincorrectly resolved: {result['incorrectly_resolved'] or 'none'}")
    print(f"summary: {result['summary']}")


if __name__ == "__main__":
    main()
