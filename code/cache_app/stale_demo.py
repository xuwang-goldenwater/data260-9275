"""
DATA 260 HW9 Part 3.5 - a stale answer, then invalidation by data version.

Record: recall F-0001-2025 (recall_notices.id = 1), cached question S1
        "How many units were affected by recall F-0001-2025?"  (answer: 8019 units)

Invalidation strategy: per-record version number in Redis.
  - every cache entry stores data_version = the record's version when it was answered
  - the application's write path (update_recall_notice_units below) changes the row
    AND increments s9275:ver:recall_notice:<id>
  - on a hit, ask() compares the stored version with the current one; if they differ,
    the entry is deleted and the question goes to the agents (VERSION_CHECK=1)

Steps
  1. ask S1                                   -> hit, 8019 (cache and database agree)
  2. update units_affected 8019 -> 8500       (database changes, version 0 -> 1)
  3. ask S1 with VERSION_CHECK off            -> STALE HIT: still says 8019
  4. ask S1 with VERSION_CHECK on             -> stale detected, entry deleted, agents rerun: 8500
  5. ask S1 again                             -> hit on the fresh answer (8500)
  6. restore 8019 (version 1 -> 2, so the 8500 answer is now outdated too and will be
     replaced on its next hit)

Needs Redis, MySQL, Kafka + the 3 HW8 agents (step 4 runs them once). Run after
threshold_sweep.py prepare, so S1 is already cached.

    python code/cache_app/stale_demo.py
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime

from sqlalchemy import text

import semantic_cache as sc
from semantic_cache import ROOT, SemanticCache, version_key

sys.path.insert(0, str(ROOT / "code" / "auth_app"))
from database import db_session_basede26 as session  # noqa: E402   same MySQL session as HW4-HW8

NOTICE_ID = 1
RECALL = "F-0001-2025"
QUESTION = "How many units were affected by recall F-0001-2025?"
OLD_UNITS, NEW_UNITS = 8019, 8500


def db_units(session) -> int:
    with session() as db:
        return db.execute(text("SELECT units_affected FROM recall_notices WHERE id = :id"),
                          {"id": NOTICE_ID}).scalar_one()


def update_recall_notice_units(cache: SemanticCache, session, units: int) -> int:
    """The application's write path: change the row, then bump the record's version."""
    with session() as db:
        db.execute(text("UPDATE recall_notices SET units_affected = :u WHERE id = :id"),
                   {"u": units, "id": NOTICE_ID})
        db.commit()
    return cache.r.incr(version_key(NOTICE_ID))


def show(step: str, r: dict, session, cache: SemanticCache) -> dict:
    current = db_units(session)
    in_answer = str(current) in r["answer"].replace(",", "")
    print(f"    is_cached={r['is_cached']}  similarity={r['similarity']}  latency={r['latency_ms']} ms")
    print(f"    answer : {r['answer'][:150]}")
    print(f"    database units_affected = {current}   record version = "
          f"{cache.current_version(NOTICE_ID)}   answer matches database: {in_answer}")
    return {"step": step, **r, "db_units": current, "answer_matches_db": in_answer}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "huggingface_hub", "sentence_transformers", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    print("Xu Wang | DATA 260 HW9 Part 3.5 | stale answer + version invalidation | PREFIX s9275")

    cache = SemanticCache(threshold=0.90, recall_guard=True)     # the shipped config (3.4)
    cache.embed("warm-up")
    log = []

    print(f"\n[1] ask S1 - cache and database agree ({RECALL})")
    log.append(show("1 before update", cache.ask(QUESTION), session, cache))

    print(f"\n[2] update {RECALL} units_affected {OLD_UNITS} -> {NEW_UNITS} through the write path")
    v = update_recall_notice_units(cache, session, NEW_UNITS)
    print(f"    database now {db_units(session)}, {version_key(NOTICE_ID)} = {v}")

    print("\n[3] ask S1 with VERSION_CHECK = off  (no invalidation)")
    sc.VERSION_CHECK = False
    log.append(show("3 stale hit", cache.ask(QUESTION), session, cache))

    print("\n[4] ask S1 with VERSION_CHECK = on   (compare stored version with current)")
    sc.VERSION_CHECK = True
    log.append(show("4 invalidated", cache.ask(QUESTION), session, cache))

    print("\n[5] ask S1 again - the fresh answer is now cached")
    log.append(show("5 fresh hit", cache.ask(QUESTION), session, cache))

    print(f"\n[6] restore {RECALL} units_affected -> {OLD_UNITS}")
    v = update_recall_notice_units(cache, session, OLD_UNITS)
    print(f"    database now {db_units(session)}, {version_key(NOTICE_ID)} = {v} "
          f"(the cached {NEW_UNITS} answer is now outdated and will be replaced on its next hit)")

    out = ROOT / "reports/hw09/raw/stale_demo.json"
    out.write_text(json.dumps({"run_at": datetime.now().isoformat(timespec="seconds"),
                               "steps": log}, indent=2))
    print(f"\nsaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
