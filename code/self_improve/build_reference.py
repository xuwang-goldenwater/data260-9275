"""
DATA 260 HW9 Part 4 - build the reference dataset and the three input files.

reference_notices.json   30 real recall notices from s9275_rel (the Evaluator's ground truth)
training_data.json       10 questions  - used while developing the agents, lessons come from here
validation_data.json     10 questions  - decides whether a new lesson is kept
test_data.json           12 questions  - held out, final evaluation only

The three input files hold ONLY {"id", "question"} - no expected answers.
The 30 records are split 10 / 10 / 10 over the three files, so no test question is
about a record seen in training or validation.

Question kinds (same mix in every split):
    single      one field of one recall          "Which firm issued recall F-....?"
    two-field   two fields of one recall         "...firm..., and how many units...?"
    not-found   a well-formed recall number that is not in the database
    off-domain  nothing to do with recall notices

Reproducible: random.Random(SEED 9275); only HW4-seeded rows (id <= 5000) are used,
the two rows created by earlier UI/Postman tests are left out.

    python code/self_improve/build_reference.py
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code" / "auth_app"))
from database import db_session_basede26  # noqa: E402

SEED = 9275
OUT = ROOT / "reports/hw09/part4"

SINGLE = {
    "units_affected": "How many units were affected by recall {r}?",
    "firm_name":      "Which firm issued recall {r}?",
    "recall_date":    "When was recall {r} issued?",
    "product_name":   "What product was recalled under {r}?",
    "category":       "What is the recall category of {r}?",
    "firm_state":     "In which state is the firm behind recall {r} located?",
}
TWO_FIELD = [
    "Which firm issued recall {r}, and how many units were affected?",
    "What product was recalled under {r}, and when was it issued?",
    "What is the recall category of {r}, and in which state is the firm located?",
    "How many units were affected by recall {r}, and when was it issued?",
]
OFF_DOMAIN = [
    "What is the capital of France?",
    "How long should I boil an egg?",
    "Who wrote the novel Pride and Prejudice?",
    "What is the best way to learn to play the guitar?",
    "How many planets are in the solar system?",
]
# kinds per split: (single, two-field, not-found, off-domain)
MIX = {"training": (3, 3, 2, 2), "validation": (4, 3, 2, 1), "test": (4, 4, 2, 2)}


def load_records(rng: random.Random) -> list[dict]:
    sql = text("""
        SELECT n.id, n.recall_number, n.product_name, n.category, n.recall_date,
               n.units_affected, f.name AS firm_name, f.state AS firm_state
          FROM recall_notices n JOIN firms f ON f.id = n.firm_id
         WHERE n.id <= 5000 ORDER BY n.id""")
    with db_session_basede26() as db:
        rows = [dict(r._mapping) for r in db.execute(sql)]
    picked = rng.sample(rows, 30)
    for r in picked:
        r["recall_date"] = r["recall_date"].isoformat()
    return picked


def unused_numbers(rng: random.Random, n: int) -> list[str]:
    with db_session_basede26() as db:
        taken = {r[0] for r in db.execute(text("SELECT recall_number FROM recall_notices"))}
    out = []
    while len(out) < n:
        num = f"F-{rng.randint(6000, 9999):04d}-{rng.choice([2022, 2023, 2024, 2025])}"
        if num not in taken and num not in out:
            out.append(num)
    return out


def main() -> None:
    print("Xu Wang | DATA 260 HW9 Part 4 | reference + input datasets | PREFIX s9275")
    rng = random.Random(SEED)
    records = load_records(rng)
    missing = unused_numbers(rng, sum(m[2] for m in MIX.values()))
    off = list(OFF_DOMAIN)
    fields = list(SINGLE)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "reference_notices.json").write_text(json.dumps({
        "source": "s9275_rel.recall_notices JOIN firms",
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "seed": SEED, "records": records}, indent=2))

    rec_i = 0
    for split, (n_single, n_two, n_missing, n_off) in MIX.items():
        own = records[rec_i:rec_i + 10]
        rec_i += 10
        qs = []
        for k in range(n_single):
            field = fields[(k + len(split)) % len(fields)]       # spread fields across splits
            qs.append(SINGLE[field].format(r=own[k]["recall_number"]))
        for k in range(n_two):
            qs.append(TWO_FIELD[k % len(TWO_FIELD)].format(r=own[n_single + k]["recall_number"]))
        for _ in range(n_missing):
            qs.append(SINGLE[rng.choice(fields)].format(r=missing.pop()))
        for _ in range(n_off):
            qs.append(off.pop(0))
        rng.shuffle(qs)
        prefix = {"training": "train", "validation": "val", "test": "test"}[split]
        items = [{"id": f"{prefix}_{i:02d}", "question": q} for i, q in enumerate(qs, 1)]
        (OUT / f"{split}_data.json").write_text(json.dumps(items, indent=2))
        print(f"\n{split}_data.json ({len(items)} questions)")
        for it in items:
            print(f"  {it['id']}  {it['question']}")

    print(f"\nreference_notices.json: {len(records)} records, e.g.")
    print("  " + json.dumps(records[0]))
    print(f"\nsaved to {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
