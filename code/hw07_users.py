"""
HW7 Part 1-III - users table for JWT auth with roles.

    python code/hw07_users.py        (make users-hw07)

Safe to run more than once:
  1. adds users.username (UNIQUE) and users.role (reader/writer/moderator)
     if they are not there yet; existing rows are backfilled first
  2. creates or resets the three demo accounts, one per role

Passwords are stored only as bcrypt hashes. The plain-text demo passwords
below exist so Postman and verify_hw07.py can log in; override them in .env.
"""
import os
import sys
from pathlib import Path

import bcrypt
import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parent / "auth_app"))
import config  # noqa: E402

ROLES = ("reader", "writer", "moderator")

DEMO_USERS = [
    # (username, role, password)
    (f"{config.PREFIX}_reader", "reader", os.getenv("HW7_READER_PASSWORD", "reader-9275")),
    (f"{config.PREFIX}_writer", "writer", os.getenv("HW7_WRITER_PASSWORD", "writer-9275")),
    (f"{config.PREFIX}_moderator", "moderator", os.getenv("HW7_MODERATOR_PASSWORD", "moderator-9275")),
]


def column_exists(cur, name: str) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = 'users' AND column_name = %s",
        (config.DB_NAME, name),
    )
    return cur.fetchone()[0] == 1


def migrate(cur) -> None:
    if not column_exists(cur, "username"):
        print("adding users.username")
        cur.execute("ALTER TABLE users ADD COLUMN username VARCHAR(50) NULL AFTER id")
        # Old HW4 rows get a unique username before the column is tightened.
        cur.execute("UPDATE users SET username = CONCAT('user', id) WHERE username IS NULL")
        cur.execute("ALTER TABLE users MODIFY COLUMN username VARCHAR(50) NOT NULL, "
                    "ADD CONSTRAINT uq_users_username UNIQUE (username)")
    if not column_exists(cur, "role"):
        print("adding users.role")
        cur.execute("ALTER TABLE users ADD COLUMN role "
                    "ENUM('reader','writer','moderator') NOT NULL DEFAULT 'reader'")


def upsert_users(cur) -> None:
    for username, role, password in DEMO_USERS:
        pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
        cur.execute(
            "INSERT INTO users (username, name, email, password_hash, role) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE password_hash = VALUES(password_hash), role = VALUES(role)",
            (username, f"{config.DEMO_NAME} ({role})", f"{role}@{config.PREFIX}.example.com",
             pw_hash, role),
        )
        print(f"user {username:<18} role={role}")


def main() -> None:
    print(f"{config.DEMO_NAME} | DATA 260 HW7 Part 1 - users table ({config.DB_NAME})")
    conn = pymysql.connect(host=config.MYSQL_HOST, port=config.MYSQL_PORT,
                           user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
                           database=config.DB_NAME, charset="utf8mb4", autocommit=True)
    with conn.cursor() as cur:
        migrate(cur)
        upsert_users(cur)
        # Show the table without the hashes' full text: proof they are hashes.
        cur.execute("SELECT id, username, role, LEFT(password_hash, 7) AS hash_prefix, "
                    "LENGTH(password_hash) AS hash_len FROM users ORDER BY id")
        print("id  username            role       hash_prefix  hash_len")
        for row in cur.fetchall():
            print(f"{row[0]:<3} {row[1]:<19} {row[2]:<10} {row[3]:<12} {row[4]}")
    conn.close()
    print("done")


if __name__ == "__main__":
    main()
