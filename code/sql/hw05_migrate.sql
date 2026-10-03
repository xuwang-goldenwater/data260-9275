-- DATA 260 HW5 Part 1-I - migrate s9275_rel from the HW4 schema to the HW5 schema.
-- Applied by:  make migrate-hw05   (python code/db_init.py code/sql/hw05_migrate.sql)
--
-- Keeps the 200 firms and 5,000 recall notices seeded in HW4 and changes the
-- tables in place. Run it once. To rebuild from nothing:
--     make db-init  ->  make seed  ->  make migrate-hw05
--
-- What changes
--   firms           + contact_email (unique), created_at, updated_at
--   recall_notices  + recall_number (unique, format F-NNNN-YYYY),
--                   + units_affected (numeric, default 0), created_at, updated_at
--                   firm_id becomes NOT NULL, and its foreign key changes from
--                   ON DELETE SET NULL to ON DELETE RESTRICT

USE s9275_rel;

-- ---- firms (the related entity) -------------------------------------------

-- 1. Add the column as NULL-able first. Adding it NOT NULL + UNIQUE in one go
--    would give all 200 existing rows the same empty value and fail.
ALTER TABLE firms
  ADD COLUMN contact_email VARCHAR(255) NULL;

-- 2. Backfill the existing rows. id is unique, so the address is unique too.
UPDATE firms
   SET contact_email = CONCAT('recalls@firm', id, '.example.com')
 WHERE id > 0;

-- 3. Now every row has a value: tighten the column and add the timestamps.
ALTER TABLE firms
  MODIFY COLUMN contact_email VARCHAR(255) NOT NULL,
  ADD CONSTRAINT uq_firms_contact_email UNIQUE (contact_email),
  ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                 ON UPDATE CURRENT_TIMESTAMP;

-- ---- recall_notices (the primary entity) ----------------------------------

-- 4. The old foreign key says ON DELETE SET NULL. MySQL refuses to make
--    firm_id NOT NULL while that rule exists, so the key is dropped first and
--    re-created in step 8.
ALTER TABLE recall_notices
  DROP FOREIGN KEY fk_notices_firm;

-- 5. Notices created from the HW4 form have no firm. Attach them to firm 1 so
--    step 8 can make firm_id NOT NULL. The 5,000 seeded rows are not touched.
UPDATE recall_notices
   SET firm_id = 1
 WHERE firm_id IS NULL;

-- 6. New columns. recall_number starts NULL-able for the same reason as step 1.
ALTER TABLE recall_notices
  ADD COLUMN recall_number  CHAR(11)     NULL,
  ADD COLUMN units_affected INT UNSIGNED NOT NULL DEFAULT 0;

-- 7. Backfill. recall_number follows the FDA style F-NNNN-YYYY, built from the
--    row id and the recall year (unique while id <= 9999). units_affected gets
--    a repeatable value between 100 and 9,999 so totals are not all zero.
UPDATE recall_notices
   SET recall_number  = CONCAT('F-', LPAD(id, 4, '0'), '-', YEAR(recall_date)),
       units_affected = 100 + MOD(id * 7919, 9900)
 WHERE id > 0;

-- 8. Tighten and constrain.
--    UNIQUE  : two notices can never share a recall number
--    CHECK   : the database itself rejects a badly formatted number
--    RESTRICT: deleting a firm that still has notices is refused (error 1451)
ALTER TABLE recall_notices
  MODIFY COLUMN firm_id       INT      NOT NULL,
  MODIFY COLUMN recall_number CHAR(11) NOT NULL,
  ADD CONSTRAINT uq_notices_recall_number UNIQUE (recall_number),
  ADD CONSTRAINT ck_notices_recall_number
      CHECK (recall_number REGEXP '^F-[0-9]{4}-[0-9]{4}$'),
  ADD CONSTRAINT fk_notices_firm
      FOREIGN KEY (firm_id) REFERENCES firms (id) ON DELETE RESTRICT,
  ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                 ON UPDATE CURRENT_TIMESTAMP;

-- ---- checks (the runner prints the rows these return) ----------------------

SELECT COUNT(*) AS firms, COUNT(DISTINCT contact_email) AS distinct_emails FROM firms;

SELECT COUNT(*) AS notices, COUNT(DISTINCT recall_number) AS distinct_numbers,
       SUM(firm_id IS NULL) AS notices_without_firm
  FROM recall_notices;

SELECT id, name, state, contact_email, created_at FROM firms ORDER BY id LIMIT 3;

SELECT id, recall_number, product_name, units_affected, firm_id, recall_date
  FROM recall_notices ORDER BY id LIMIT 3;
