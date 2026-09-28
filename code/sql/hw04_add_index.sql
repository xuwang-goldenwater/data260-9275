-- DATA 260 HW4 Part 3 step 8 - the one index added for the EXPLAIN comparison.
-- The list endpoints sort by recall_date DESC, id DESC and take one page.
-- Without this index MySQL reads every row and sorts them (type=ALL, Using filesort).
-- InnoDB secondary indexes carry the primary key, so (recall_date) also covers
-- the id tie-breaker and the index can be read backwards in order.
CREATE INDEX ix_recall_notices_recall_date ON recall_notices (recall_date);
