"""
DATA 260 HW9 Part 1 - Redis-backed view counter for recall notices.

Every view does one Redis INCR (in memory, no SQL). Only every 10th view
writes the count to MySQL (recall_notices.view_count), so the database sees
1 UPDATE per 10 views instead of 10.

Run the demo (Redis container + MySQL running, hw09_migrate.sql applied):
    python code/cache_app/recall_cache.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import redis
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code" / "auth_app"))
from database import db_session_basede26  # noqa: E402   same MySQL session as HW4-HW8

PREFIX = "s9275"
SYNC_EVERY = 10
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

log = logging.getLogger("recall_cache")


class RecallCache:
    """Redis in front of s9275_rel. Part 1 adds only increment_recall_notice_views."""

    def __init__(self, redis_url: str = REDIS_URL):
        self.redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.Session = db_session_basede26
        self.last_synced = False   # True if the latest call wrote to MySQL

    def increment_recall_notice_views(self, notice_id: int) -> int:
        """Count one view of a recall notice and return the running total."""
        # 1. Increment in Redis. INCR is atomic: two requests at the same time
        #    get two different numbers, so no view is lost.
        key = f"{PREFIX}:views:recall_notice:{notice_id}"
        count = self.redis_client.incr(key)

        # 2. Every 10th view, copy the count to the database row.
        #    updated_at = updated_at keeps the column's ON UPDATE CURRENT_TIMESTAMP
        #    from firing: a view is not a change to the recall notice itself.
        self.last_synced = False
        if count % SYNC_EVERY == 0:
            with self.Session() as db:
                db.execute(
                    text("UPDATE recall_notices SET view_count = :c, updated_at = updated_at "
                         "WHERE id = :id"),
                    {"c": count, "id": notice_id},
                )
                db.commit()
            self.last_synced = True
            log.info("Synced views to database: notice %s view_count=%s", notice_id, count)

        # 3. Return the current count.
        return count


def demo(notice_id: int = 1, accesses: int = 25) -> None:
    logging.basicConfig(level=logging.INFO, format="  [log] %(message)s")
    print("Xu Wang | DATA 260 HW9 Part 1 | PREFIX s9275")
    cache = RecallCache()

    # Start from zero so the run is repeatable (demo only, not part of the method).
    cache.redis_client.delete(f"{PREFIX}:views:recall_notice:{notice_id}")
    with cache.Session() as db:
        db.execute(text("UPDATE recall_notices SET view_count = 0, updated_at = updated_at "
                        "WHERE id = :id"), {"id": notice_id})
        db.commit()

    print(f"\n=== Testing Counter === (recall_notices.id = {notice_id})\n")
    for i in range(1, accesses + 1):
        total = cache.increment_recall_notice_views(notice_id)
        print(f"Access #{i}: Total = {total}")
        if cache.last_synced:
            print("✓ Synced views to database")

    with cache.Session() as db:
        db_value = db.execute(text("SELECT view_count FROM recall_notices WHERE id = :id"),
                              {"id": notice_id}).scalar_one()
    redis_value = cache.redis_client.get(f"{PREFIX}:views:recall_notice:{notice_id}")
    print(f"\nRedis  {PREFIX}:views:recall_notice:{notice_id} = {redis_value}")
    print(f"MySQL  recall_notices.view_count (id={notice_id})   = {db_value}")


if __name__ == "__main__":
    demo()
