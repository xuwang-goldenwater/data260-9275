-- DATA 260 HW9 Part 1 - add the persisted view counter to recall notices.
-- Applied by:  python code/db_init.py code/sql/hw09_migrate.sql
--
-- Run it once, on top of the HW5 schema. To rebuild from nothing:
--     make db-init  ->  make seed  ->  make migrate-hw05  ->  this file
--
-- The live count is kept in Redis (key s9275:views:recall_notice:<id>, INCR);
-- this column only receives a copy every 10 views, so it can lag the Redis
-- count by up to 9.

USE s9275_rel;

-- DEFAULT 0 fills all 5,000 existing rows, so NOT NULL is safe in one step.
ALTER TABLE recall_notices
  ADD COLUMN view_count INT NOT NULL DEFAULT 0;

-- ---- checks (the runner prints the rows these return) ----------------------

SELECT COUNT(*) AS notices, SUM(view_count) AS total_views FROM recall_notices;

SELECT id, recall_number, product_name, view_count
  FROM recall_notices ORDER BY id LIMIT 3;
