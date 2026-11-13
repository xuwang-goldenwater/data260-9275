"""
DATA 260 - HW10 Part 3.2 + 3.3: validate the judge against Xu's human labels.

Inputs (frozen and committed first, in 134994a):
    reports/hw10/eval_cases.json     20 Writer drafts
    reports/hw10/human_labels.csv    one hand-assigned 1-5 helpfulness label per draft
The script refuses to run if human_labels.csv has uncommitted changes, and records the
commit that last touched it, so the labels provably predate these judge scores.

Judge: judge.py helpfulness metric (qwen3:4b, temperature 0, seed 9275, num_ctx 4096,
num_predict 300, JSON output, 90 s timeout), exactly as in Part 2. It is run 3 times over
the same 20 inputs, in the same order, with nothing changed between runs.

Outputs in reports/hw10/part3/:
    judge_runs.csv          case_id, human_label, run1, run2, run3, judge_mean  (raw data)
    judge_reasons.jsonl     every judge reason and its time, per run and case
    judge_validation.json   Spearman rho (+ p) and mean absolute difference vs the human
                            labels for each run and for the 3-run mean; repeatability:
                            share of cases whose score changed, share of changed run pairs,
                            mean and max absolute change

Stop the agents and the evaluator first, so the judge has the GPU to itself:
    python code/eval_pipeline/validate_judge.py
"""

from __future__ import annotations

import csv
import itertools
import json
import subprocess
import sys
import time
from pathlib import Path

from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code" / "eval_pipeline"))
from judge import (JUDGE_MODEL, JUDGE_OPTIONS, JUDGE_TIMEOUT_S, JudgeError,  # noqa: E402
                   helpfulness_metric, score)

REPORT = ROOT / "reports/hw10"
OUT = REPORT / "part3"
LABELS = REPORT / "human_labels.csv"
RUNS = 3


def labels_commit() -> str:
    rel = str(LABELS.relative_to(ROOT))
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=ROOT).returncode != 0:
        raise SystemExit("human_labels.csv has uncommitted changes - labels must be committed first")
    return subprocess.run(["git", "log", "-1", "--format=%h %s", "--", rel], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()


def compare(human: list[int], judge: list[float | None]) -> dict:
    pairs = [(h, j) for h, j in zip(human, judge) if j is not None]
    hs, js = [p[0] for p in pairs], [p[1] for p in pairs]
    rho, p = spearmanr(hs, js) if len(set(js)) > 1 and len(set(hs)) > 1 else (float("nan"), float("nan"))
    return {"n": len(pairs), "spearman_rho": round(float(rho), 3), "spearman_p": round(float(p), 4),
            "mean_abs_diff": round(sum(abs(h - j) for h, j in pairs) / len(pairs), 3),
            "mean_judge_minus_human": round(sum(j - h for h, j in pairs) / len(pairs), 3),
            "exact_agreement": round(sum(h == j for h, j in pairs) / len(pairs), 3),
            "within_1": round(sum(abs(h - j) <= 1 for h, j in pairs) / len(pairs), 3)}


def main() -> None:
    commit = labels_commit()
    cases = json.loads((REPORT / "eval_cases.json").read_text())["cases"]
    human = {r["case_id"]: int(r["human_label"]) for r in csv.DictReader(LABELS.open())}
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"labels frozen in: {commit}")
    print(f"judge {JUDGE_MODEL} options={JUDGE_OPTIONS} timeout={JUDGE_TIMEOUT_S}s, {RUNS} runs x {len(cases)} drafts")

    metric = helpfulness_metric()
    scores: dict[str, list] = {c["case_id"]: [] for c in cases}
    with (OUT / "judge_reasons.jsonl").open("w") as fh:
        for run in range(1, RUNS + 1):
            t0 = time.time()
            for c in cases:
                try:
                    r = score(metric, c["question"], c["draft"], c["facts"])
                except JudgeError as exc:
                    r = {"score": None, "reason": None, "error": str(exc), "seconds": None}
                scores[c["case_id"]].append(r["score"])
                fh.write(json.dumps({"run": run, "case_id": c["case_id"], **r}) + "\n")
                print(f"  run {run} {c['case_id']} judge={r['score']} human={human[c['case_id']]} "
                      f"({r['seconds']}s)", flush=True)
            print(f"run {run} done in {(time.time() - t0) / 60:.1f} min")

    ids = [c["case_id"] for c in cases]
    with (OUT / "judge_runs.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["case_id", "kind", "human_label"] + [f"run{i}" for i in range(1, RUNS + 1)] + ["judge_mean"])
        for c in cases:
            s = scores[c["case_id"]]
            ok = [x for x in s if x is not None]
            w.writerow([c["case_id"], c["kind"], human[c["case_id"]], *s,
                        round(sum(ok) / len(ok), 3) if ok else ""])

    h = [human[i] for i in ids]
    per_run = {f"run{r + 1}": compare(h, [scores[i][r] for i in ids]) for r in range(RUNS)}
    means = [(sum(x for x in scores[i] if x is not None) / max(1, sum(x is not None for x in scores[i])))
             if any(x is not None for x in scores[i]) else None for i in ids]
    changes = [abs(a - b) for i in ids for a, b in itertools.combinations(scores[i], 2)
               if a is not None and b is not None]
    changed_cases = [i for i in ids if len({x for x in scores[i] if x is not None}) > 1]
    result = {
        "labels_commit": commit,
        "judge": {"model": JUDGE_MODEL, "options": JUDGE_OPTIONS, "timeout_s": JUDGE_TIMEOUT_S,
                  "metric": "Helpfulness (judge.py)", "runs": RUNS},
        "vs_human": {**per_run, "mean_of_3_runs": compare(h, means)},
        "repeatability": {
            "cases": len(ids),
            "cases_with_any_change": len(changed_cases),
            "share_cases_changed": round(len(changed_cases) / len(ids), 3),
            "run_pairs_compared": len(changes),
            "share_pairs_changed": round(sum(c > 0 for c in changes) / len(changes), 3) if changes else None,
            "mean_abs_change": round(sum(changes) / len(changes), 3) if changes else None,
            "max_abs_change": max(changes) if changes else None,
            "changed_case_ids": changed_cases,
            "judge_errors": sum(x is None for i in ids for x in scores[i]),
        },
    }
    (OUT / "judge_validation.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
