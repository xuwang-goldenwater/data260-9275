"""
Apply a .sql file to MySQL, one statement at a time.

    python code/db_init.py                              # make db-init (HW4 schema)
    python code/db_init.py code/sql/hw05_migrate.sql    # make migrate-hw05

With no argument it applies code/sql/hw04_schema.sql, which is destructive by
design: that file drops and recreates every table.
Connection settings come from MYSQL_USER / MYSQL_PASSWORD / MYSQL_HOST /
MYSQL_PORT in the repo's .env (see .env.example).
"""
import re
import sys
from pathlib import Path

import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parent / "auth_app"))
import config  # noqa: E402

SCHEMA_FILE = Path(__file__).resolve().parent / "sql" / "hw04_schema.sql"


def statements(sql_text: str):
    """Split a plain SQL file on ';' after dropping -- comments."""
    without_comments = re.sub(r"--[^\n]*", "", sql_text)
    return [s.strip() for s in without_comments.split(";") if s.strip()]


def main():
    conn = pymysql.connect(host=config.MYSQL_HOST, port=config.MYSQL_PORT,
                           user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
                           charset="utf8mb4", autocommit=True)
    with conn.cursor() as cur:
        sql_file = Path(sys.argv[1]) if len(sys.argv) > 1 else SCHEMA_FILE
        print("applying", sql_file)
        for stmt in statements(sql_file.read_text(encoding="utf-8")):
            cur.execute(stmt)
            print("ok:", " ".join(stmt.split())[:80])
            if cur.description:                       # a SELECT: show what it returned
                print("   ", [col[0] for col in cur.description])
                for row in cur.fetchall():
                    print("   ", row)
        cur.execute(f"SHOW TABLES FROM {config.DB_NAME}")
        print(f"tables in {config.DB_NAME}:", [row[0] for row in cur.fetchall()])
    conn.close()


if __name__ == "__main__":
    main()
