"""
HW5 Part 3 step 19 - a timeout and a bounded exponential-backoff retry for
storage operations.

    python code/retry_policy.py        # make retry-demo

The demo shows the cases the assignment asks for: success on the first
attempt, failure then success after a retry, and failure after every allowed
attempt (which ends in a clean ok:false envelope, not a crash).

How it plugs in: RetryingRepo wraps any repo (see domain_tools.py) and offers
the same three methods. The tools do not know it is there.

    RetryingRepo( MySQLRepo() )                 what the MCP server uses
    RetryingRepo( FlakyRepo( MySQLRepo() ) )    Part 3 fault injection
"""
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Callable, Optional

log = logging.getLogger("retry_policy")


# ---- 1. the kinds of failure -----------------------------------------------------

class TransientStorageError(Exception):
    """A failure that may go away if the same operation is tried again."""


class StorageTimeout(TransientStorageError):
    """One attempt did not answer within the policy's timeout."""


class RetriesExhausted(Exception):
    """Every allowed attempt failed. Not retried any further."""


# Connection-level errors from SQLAlchemy / PyMySQL, matched by class name so
# that this file does not have to import the database libraries.
TRANSIENT_DB_ERRORS = {"OperationalError", "InterfaceError"}


def is_transient(exc: BaseException) -> bool:
    """Retry only what a retry can fix. A bug or bad data fails the same way every time."""
    return (isinstance(exc, (TransientStorageError, ConnectionError, TimeoutError))
            or type(exc).__name__ in TRANSIENT_DB_ERRORS)


# ---- 2. the policy ---------------------------------------------------------------

@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3          # the first try plus two retries
    timeout_s: float = 2.0         # one attempt may take this long
    base_delay_s: float = 0.1      # wait before the first retry
    multiplier: float = 2.0        # each later wait is this many times longer
    max_delay_s: float = 1.0       # ... but never longer than this

    def delay_before(self, attempt: int) -> float:
        """Seconds to wait before attempt 2, 3, ...: base, base*2, base*4, capped."""
        return min(self.base_delay_s * self.multiplier ** (attempt - 2), self.max_delay_s)

    def describe(self) -> str:
        waits = ", ".join(f"{self.delay_before(a):g} s" for a in range(2, self.max_attempts + 1))
        return (f"{self.max_attempts} attempts, {self.timeout_s:g} s timeout per attempt, "
                f"wait before retries: {waits} (x{self.multiplier:g}, capped at {self.max_delay_s:g} s)")


DEFAULT_POLICY = RetryPolicy()


# ---- 3. timeout and retry ----------------------------------------------------------

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="storage")


def run_with_timeout(operation: Callable[[], Any], timeout_s: float) -> Any:
    """Run operation() in a worker thread and stop waiting after timeout_s.

    Python cannot kill a running thread, so a query that hangs keeps its
    thread until MySQL answers; the caller, however, gets control back on time.
    """
    future = _pool.submit(operation)
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeout:
        if future.done():              # the operation itself raised a TimeoutError
            raise
        future.cancel()
        raise StorageTimeout(f"no answer within {timeout_s:g} s") from None


def run_with_retry(operation: Callable[[], Any], policy: RetryPolicy = DEFAULT_POLICY,
                   sleep: Callable[[float], None] = time.sleep, name: str = "storage",
                   attempts: Optional[list] = None) -> Any:
    """Call operation() until it works or the policy runs out.

    attempts, when given, receives one dict per try: attempt number, how long
    it waited first, outcome, error text and duration. The experiment reads it.
    """
    attempts = attempts if attempts is not None else []
    for attempt in range(1, policy.max_attempts + 1):
        waited = 0.0
        if attempt > 1:
            waited = policy.delay_before(attempt)
            sleep(waited)                                   # exponential backoff
        started = time.perf_counter()
        try:
            result = run_with_timeout(operation, policy.timeout_s)
        except Exception as exc:
            reason = (str(exc).splitlines() or [""])[0][:200]      # database errors run to several lines
            attempts.append({"attempt": attempt, "waited_s": waited, "outcome": "failed",
                             "error": f"{type(exc).__name__}: {reason}",
                             "ms": round((time.perf_counter() - started) * 1000, 3)})
            if not is_transient(exc):
                raise                                       # retrying cannot help
            log.warning("%s attempt %d/%d failed: %s", name, attempt, policy.max_attempts, reason)
            continue
        attempts.append({"attempt": attempt, "waited_s": waited, "outcome": "ok", "error": None,
                         "ms": round((time.perf_counter() - started) * 1000, 3)})
        return result
    raise RetriesExhausted(f"{name} failed {policy.max_attempts} times; "
                           f"last error: {attempts[-1]['error']}")


# ---- 4. the wrapper the rest of the code uses ---------------------------------------

class RetryingRepo:
    """Any repo, with the timeout and retry policy applied to each of its methods."""

    def __init__(self, inner, policy: RetryPolicy = DEFAULT_POLICY,
                 sleep: Callable[[float], None] = time.sleep):
        self.inner, self.policy, self.sleep = inner, policy, sleep
        self.last_attempts: list = []      # what happened during the most recent call

    def _run(self, name: str, operation: Callable[[], Any]) -> Any:
        self.last_attempts = []
        return run_with_retry(operation, self.policy, self.sleep, name, self.last_attempts)

    def search(self, query, category, limit):
        return self._run("search", lambda: self.inner.search(query, category, limit))

    def get(self, recall_number):
        return self._run("get", lambda: self.inner.get(recall_number))

    def summary(self, group_by, year):
        return self._run("summary", lambda: self.inner.summary(group_by, year))


# ---- demo -------------------------------------------------------------------------

class ScriptedRepo:
    """Demo storage: fails the first `failures` calls, or answers after `slow_s` seconds."""

    NOTICE = {"id": 1, "recall_number": "F-0001-2025", "product_name": "Blue Heron Enoki Mushrooms, 32 oz tub",
              "category": "Undeclared Allergen", "recall_date": "2025-06-23", "units_affected": 8019,
              "firm": {"id": 73, "name": "Harbor Snacks Co.", "state": "GA"}}

    def __init__(self, failures: int = 0, slow_s: float = 0.0):
        self.failures, self.slow_s, self.calls = failures, slow_s, 0

    def get(self, recall_number):
        self.calls += 1
        if self.slow_s:
            time.sleep(self.slow_s)
        if self.calls <= self.failures:
            raise TransientStorageError("connection lost (scripted)")
        return dict(self.NOTICE)


def demo():
    import json
    from datetime import datetime

    from domain_tools import call_tool, config     # domain_tools puts auth_app on the path

    print(f"{config.DEMO_NAME} | DATA 260 HW5 Part 3 | {config.PREFIX} | retry demo | "
          f"{datetime.now():%Y-%m-%d %H:%M:%S}")
    cases = [
        ("Case 1 - success on the first attempt", ScriptedRepo(failures=0), DEFAULT_POLICY),
        ("Case 2 - first attempt fails, the retry succeeds", ScriptedRepo(failures=1), DEFAULT_POLICY),
        ("Case 3 - every allowed attempt fails -> clean error, no crash", ScriptedRepo(failures=99), DEFAULT_POLICY),
        ("Case 4 - storage too slow: each attempt hits the timeout", ScriptedRepo(slow_s=0.6),
         RetryPolicy(timeout_s=0.2)),
    ]
    for title, storage, policy in cases:
        repo = RetryingRepo(storage, policy)
        started = time.perf_counter()
        envelope = call_tool("get_notice", {"recall_number": "F-0001-2025"}, repo)
        total_ms = (time.perf_counter() - started) * 1000

        print(f"\n{title}")
        print(f"  policy : {policy.describe()}")
        for a in repo.last_attempts:
            waited = f"waited {a['waited_s']:g} s, " if a["waited_s"] else ""
            detail = "ok" if a["outcome"] == "ok" else f"FAILED  {a['error']}"
            print(f"  attempt {a['attempt']}: {waited}{detail}")
        shown = dict(envelope)
        if shown["ok"]:
            shown["data"] = {"recall_number": shown["data"]["recall_number"], "...": "..."}
        print(f"  result : {json.dumps(shown)}")
        print(f"  total  : {total_ms:.0f} ms, {len(repo.last_attempts)} attempt(s)")


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.CRITICAL)   # the demo prints every attempt itself
    demo()
