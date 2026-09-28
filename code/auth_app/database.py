"""MySQL connection for HW4.

The schema itself is created by code/sql/hw04_schema.sql (make db-init);
this file only connects to it.
"""
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import declarative_base, sessionmaker

import config

DATABASE_URL = URL.create(
    "mysql+pymysql",
    username=config.MYSQL_USER,
    password=config.MYSQL_PASSWORD,
    host=config.MYSQL_HOST,
    port=config.MYSQL_PORT,
    database=config.DB_NAME,
    query={"charset": "utf8mb4"},
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# The assignment requires this exact name for the database connection variable.
# Every request gets its own Session from this factory (see get_db).
db_session_basede26 = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

Base = declarative_base()


def get_db():
    """FastAPI dependency: one Session per request, always closed afterwards."""
    db = db_session_basede26()
    try:
        yield db
    finally:
        db.close()
