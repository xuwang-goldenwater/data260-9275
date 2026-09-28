"""Count the SQL statements each HTTP request sends to MySQL (Part 3).

A middleware in main.py calls start_request() at the beginning of every
request. That puts a fresh counter into a ContextVar. SQLAlchemy fires
`before_cursor_execute` once for every statement it sends, and the listener
below adds 1 to whichever counter belongs to the current request.

The counter is a small mutable object, not an int, because FastAPI runs sync
endpoints in a worker thread with a *copy* of the context: the copy still
points at the same object, so increments made in the thread are visible to
the middleware that reads the total at the end.
"""
from contextvars import ContextVar
from typing import Optional

from sqlalchemy import event

from database import engine


class RequestCounter:
    def __init__(self):
        self.total = 0
        self.statements = []       # kept short; only used when debugging

    def add(self, sql: str):
        self.total += 1
        if len(self.statements) < 5:
            self.statements.append(" ".join(sql.split())[:120])


_current: ContextVar[Optional[RequestCounter]] = ContextVar("sql_counter", default=None)


def start_request() -> RequestCounter:
    counter = RequestCounter()
    _current.set(counter)
    return counter


def current() -> Optional[RequestCounter]:
    return _current.get()


@event.listens_for(engine, "before_cursor_execute")
def _count(conn, cursor, statement, parameters, context, executemany):
    counter = _current.get()
    if counter is not None:
        counter.add(statement)
