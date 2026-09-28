"""
HW4 Part 3 step 8 - EXPLAIN the list query before and after one index.

    make explain-index

1. Drops ix_recall_notices_recall_date if it exists (so "before" is honest).
2. EXPLAIN + EXPLAIN ANALYZE of the exact SQL the fixed endpoint sends for
   page 1 at each benchmark page size (10, 50, 200), plus the median of 20
   timed executions of each.
3. Applies code/sql/hw04_add_index.sql.
4. Repeats step 2. The index is left in place afterwards.

Why three page sizes: on a 5,000-row table MySQL's cost model only prefers
reading the index backwards for small LIMITs. For larger LIMITs it decides
that scanning the whole (small) table and sorting it is cheaper, and keeps
the old plan even though the index exists. Showing all three sizes makes
that visible instead of hiding it.

Output: reports/hw04/raw/explain_before_after.json and explain_before_after.txt
"""
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.dialects import mysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code" / "auth_app"))
import config  # noqa: E402
from database import engine  # noqa: E402
from models import RecallNotice  # noqa: E402
from routers.notices import page_query  # noqa: E402
from sqlalchemy.orm import joinedload  # noqa: E402

RAW_DIR = ROOT / "reports" / "hw04" / "raw"
PAGE_SIZES = [10, 50, 200]
INDEX_NAME = "ix_recall_notices_recall_date"
INDEX_SQL = (ROOT / "code" / "sql" / "hw04_add_index.sql").read_text(encoding="utf-8")


def list_sql(page=1, page_size=50) -> str:
    """The fixed endpoint's statement, compiled to literal MySQL SQL."""
    stmt = page_query(page, page_size).options(joinedload(RecallNotice.firm))
    return str(stmt.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))


def index_exists(conn) -> bool:
    return conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.statistics "
        "WHERE table_schema = :db AND table_name = 'recall_notices' AND index_name = :ix"),
        {"db": config.DB_NAME, "ix": INDEX_NAME}).scalar() > 0


def inspect(conn, sql: str) -> dict:
    result = conn.execute(text("EXPLAIN " + sql))
    columns = list(result.keys())
    explain_rows = [dict(zip(columns, row)) for row in result.fetchall()]
    analyze = conn.execute(text("EXPLAIN ANALYZE " + sql)).scalar()
    timings = []
    for _ in range(20):
        t0 = time.perf_counter()
        conn.execute(text(sql)).fetchall()
        timings.append((time.perf_counter() - t0) * 1000)
    return {"explain": explain_rows, "explain_analyze": analyze,
            "median_ms_of_20_runs": round(statistics.median(timings), 3)}


def fmt(label: str, block: dict) -> str:
    out = [f"===== {label} ====="]
    keys = ["id", "select_type", "table", "type", "possible_keys", "key", "rows", "filtered", "Extra"]
    out.append(" | ".join(keys))
    for row in block["explain"]:
        out.append(" | ".join(str(row.get(k)) for k in keys))
    out.append("")
    out.append("EXPLAIN ANALYZE:")
    out.append(block["explain_analyze"])
    out.append(f"median of 20 executions: {block['median_ms_of_20_runs']} ms")
    return "\n".join(out)


def main():
    print(f"===== explain-index {datetime.now().isoformat(timespec='seconds')} =====")
    queries = {size: list_sql(1, size) for size in PAGE_SIZES}
    results = {"before": {}, "after": {}}
    with engine.connect() as conn:
        if index_exists(conn):
            conn.execute(text(f"DROP INDEX {INDEX_NAME} ON recall_notices"))
        conn.execute(text("ANALYZE TABLE recall_notices"))
        for size, sql in queries.items():
            results["before"][size] = inspect(conn, sql)

        create_index = "\n".join(line for line in INDEX_SQL.splitlines()
                                 if not line.startswith("--"))
        conn.execute(text(create_index))
        conn.execute(text("ANALYZE TABLE recall_notices"))
        for size, sql in queries.items():
            results["after"][size] = inspect(conn, sql)
        assert index_exists(conn)

    parts = []
    for size, sql in queries.items():
        parts.append(f"################ page_size = {size} ################")
        parts.append("query:\n" + sql)
        parts.append(fmt(f"BEFORE (no index on recall_date), page_size {size}",
                         results["before"][size]))
        parts.append(fmt(f"AFTER  (index {INDEX_NAME}), page_size {size}",
                         results["after"][size]))
    summary = ["page_size | before: type / key / Extra | after: type / key / Extra | median ms before -> after"]
    for size in PAGE_SIZES:
        b = results["before"][size]["explain"][0]
        a = results["after"][size]["explain"][0]
        summary.append(f"{size} | {b['type']} / {b['key']} / {b['Extra']} | {a['type']} / {a['key']} / {a['Extra']} | "
                       f"{results['before'][size]['median_ms_of_20_runs']} -> {results['after'][size]['median_ms_of_20_runs']}")
    parts.append("################ summary ################\n" + "\n".join(summary))

    report = "\n\n".join(parts)
    print(report)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / "explain_before_after.txt").write_text(report + "\n", encoding="utf-8")
    (RAW_DIR / "explain_before_after.json").write_text(json.dumps(
        {"index": INDEX_NAME, "queries": queries, "results": results},
        indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
