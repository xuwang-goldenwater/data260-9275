"""HW6 Part 3: what memory costs.

Replays the fixed 30-message conversation (reports/hw06/conversation_30.yaml) and
then the five probes (reports/hw06/memory_probes.yaml) once per setting:

    N4        SHORT_TERM_N = 4
    N12       SHORT_TERM_N = 12
    N30       SHORT_TERM_N = 30
    N30_comp  SHORT_TERM_N = 30 + compress_assistant policy (Part 3-4)

Every setting gets a NEW user_id and a NEW session, so no run can use summaries or
episodic facts left behind by an earlier run (the lifetime summary is per user).

Writes (appends) to reports/hw06/raw/:
    part3_turns.jsonl        one row per turn: tokens per section, latency, upkeep calls
    part3_probe_scores.csv   one row per probe answer, score column left empty for hand scoring

Run:  make memory-cost                     all four settings (~45-60 min on M1 8 GB)
      python code/hw06_memory_cost.py N4    one setting
Needs MongoDB (Docker) and Ollama; the API does not need to be running.
"""
import csv
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code" / "doc_app"))

import config      # noqa: E402
import memory      # noqa: E402

REPORT = ROOT / "reports" / "hw06"
RAW = REPORT / "raw"
TURNS = RAW / "part3_turns.jsonl"
SCORES = RAW / "part3_probe_scores.csv"

SETTINGS = {
    "N4": {"short_term_n": 4, "window_policy": "full"},
    "N12": {"short_term_n": 12, "window_policy": "full"},
    "N30": {"short_term_n": 30, "window_policy": "full"},
    "N30_comp": {"short_term_n": 30, "window_policy": "compress_assistant"},
}


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                       text=True).strip()
    except Exception:
        return "unknown"


def run_setting(name: str, conversation, probes, commit: str) -> None:
    spec = SETTINGS[name]
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    user_id = f"probe_{name}_{stamp}"
    session_id = memory.new_session_id()
    print(f"\n=== {name}: N={spec['short_term_n']} policy={spec['window_policy']} "
          f"user={user_id} session={session_id}", flush=True)
    base = {"run_id": f"{name}_{stamp}", "setting": name, "commit": commit,
            "seed": config.SEED, "verify_seed": config.VERIFY_SEED}

    turns = [("conversation", m["n"], None, m["text"]) for m in conversation]
    turns += [("probe", len(conversation) + i + 1, p["id"], p["question"])
              for i, p in enumerate(probes)]
    answers = []
    started = time.perf_counter()
    for kind, turn_no, probe_id, text in turns:
        result = memory.chat_turn(user_id, text, session_id, spec["short_term_n"],
                                  spec["window_policy"])
        row = memory.log_turn(TURNS, result, {**base, "turn": turn_no, "kind": kind,
                                              "probe_id": probe_id, "message": text})
        print(f"  {name} t{turn_no:02d} {kind[:5]} prompt={row['prompt_tokens']:5d} "
              f"window={row['tokens_short_term_window']:5d} "
              f"lt={row['tokens_long_term_summary']:4d} ep={row['tokens_episodic_facts']:3d} "
              f"{row['total_latency_ms'] / 1000:5.1f}s"
              + (f"  {probe_id}: {row['reply'][:70]!r}" if probe_id else ""), flush=True)
        if probe_id:
            answers.append({"run_id": base["run_id"], "setting": name, "probe_id": probe_id,
                            "question": text, "answer": row["reply"], "score": ""})
    new_file = not SCORES.exists()
    with open(SCORES, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(answers[0]))
        if new_file:
            writer.writeheader()
        writer.writerows(answers)
    print(f"=== {name} done in {(time.perf_counter() - started) / 60:.1f} min", flush=True)


def main() -> None:
    names = sys.argv[1:] or list(SETTINGS)
    unknown = [n for n in names if n not in SETTINGS]
    if unknown:
        sys.exit(f"unknown setting(s) {unknown}; choose from {list(SETTINGS)}")
    conversation = yaml.safe_load(open(REPORT / "conversation_30.yaml"))["messages"]
    probes = yaml.safe_load(open(REPORT / "memory_probes.yaml"))["probes"]
    assert len(conversation) == 30 and len(probes) == 5
    commit = git_commit()
    print(f"Xu Wang | DATA 260 HW6 Part 3 | memory cost | {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"model={config.CHAT_MODEL} num_ctx={config.NUM_CTX} seed={config.SEED} "
          f"commit={commit} settings={names}")
    RAW.mkdir(parents=True, exist_ok=True)
    memory.ensure_indexes()
    for name in names:
        run_setting(name, conversation, probes, commit)
    print(f"\nrows appended to {TURNS.relative_to(ROOT)} and {SCORES.relative_to(ROOT)}")
    print("next: fill the score column (1-5, rubric in memory_probes.yaml), then make memory-summary")


if __name__ == "__main__":
    main()
