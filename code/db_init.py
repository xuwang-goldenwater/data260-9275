"""
HW4 - apply code/sql/hw04_schema.sql to MySQL (creates s9275_rel and its tables).

    python code/db_init.py        # or: make db-init

Destructive by design: the schema file drops and recreates every table.
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
        for stmt in statements(SCHEMA_FILE.read_text(encoding="utf-8")):
            cur.execute(stmt)
            print("ok:", " ".join(stmt.split())[:80])
        cur.execute(f"SHOW TABLES FROM {config.DB_NAME}")
        print(f"tables in {config.DB_NAME}:", [row[0] for row in cur.fetchall()])
    conn.close()


if __name__ == "__main__":
    main()
