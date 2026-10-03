"""
Print the two HW5 tables (definition + first rows) for the database screenshot.

    python code/db_show.py        # or: make db-show

Read-only: it runs SHOW CREATE TABLE and SELECT, nothing else.
"""
import sys
from pathlib import Path

import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parent / "auth_app"))
import config  # noqa: E402

TABLES = ["firms", "recall_notices"]
SAMPLES = [
    "SELECT id, name, state, contact_email, created_at FROM firms ORDER BY id LIMIT 5",
    "SELECT id, recall_number, LEFT(product_name, 36) AS product_name, units_affected, "
    "firm_id, created_at FROM recall_notices ORDER BY id LIMIT 5",
]


def print_table(cur):
    """Draw the result of the last query as a text grid, like the mysql client does."""
    columns = [col[0] for col in cur.description]
    rows = [[str(value) for value in row] for row in cur.fetchall()]
    widths = [max(len(columns[i]), *(len(r[i]) for r in rows)) for i in range(len(columns))]
    border = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def line(values):
        return "| " + " | ".join(v.ljust(w) for v, w in zip(values, widths)) + " |"

    print(border)
    print(line(columns))
    print(border)
    for row in rows:
        print(line(row))
    print(border)


def main():
    conn = pymysql.connect(host=config.MYSQL_HOST, port=config.MYSQL_PORT,
                           user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
                           database=config.DB_NAME, charset="utf8mb4")
    with conn.cursor() as cur:
        print(f"database: {config.DB_NAME}\n")
        for name in TABLES:
            cur.execute(f"SHOW CREATE TABLE {name}")
            print(cur.fetchone()[1], "\n")          # column 1 is the CREATE TABLE text
        for sql in SAMPLES:
            cur.execute(sql)
            print_table(cur)
            print()
    conn.close()


if __name__ == "__main__":
    main()
