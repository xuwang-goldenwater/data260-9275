"""
HW7 Part 4-I - the three MRKL tools, as plain functions with JSON schemas.

    csv_sql(sql)                       read-only SELECT over the uploaded trips
    policy_retriever(url, query, k=3)  fetch the pricing page, return short quotable snippets
    calculator(expression, units=None) safe arithmetic (no eval)

Every tool returns the same envelope:
    {"success": bool, "data"?: any, "error"?: str, "source"?: str, "ts"?: str}

Standard library only (sqlite3, csv, urllib, html.parser, ast), so the tools can
be tested without the model or any extra package.
"""
from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import math
import operator
import re
import sqlite3
import urllib.request
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOT_DIR = ROOT / "reports" / "hw07" / "raw" / "bike" / "snapshots"
MAX_ROWS = 200


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ok(data, source=None) -> dict:
    out = {"success": True, "data": data, "ts": now()}
    if source:
        out["source"] = source
    return out


def fail(error: str, source=None) -> dict:
    out = {"success": False, "error": error, "ts": now()}
    if source:
        out["source"] = source
    return out


# ---- JSON schemas (what the agent is told about each tool) ----------------------

SCHEMAS = {
    "csv_sql": {
        "name": "csv_sql",
        "description": ("Run ONE read-only SQL SELECT over the uploaded trips. Table `trips`, one row per "
                        "ride: ride_id, rideable_type, started_at, ended_at, start_station_name, "
                        "end_station_name, member_casual, plus derived columns: minutes (ride length "
                        "rounded UP to whole minutes), bike ('classic' or 'ebike'), month ('YYYY-MM'), "
                        "week_start ('YYYY-MM-DD', Monday), over45 (minutes beyond 45, else 0)."),
        "input": {"type": "object", "properties": {"sql": {"type": "string"}},
                  "required": ["sql"], "additionalProperties": False},
        "output": {"type": "object", "properties": {
            "rows": {"type": "array", "items": {"type": "object"}},
            "row_count": {"type": "number"}, "source": {"const": "uploaded.csv"}}},
    },
    "policy_retriever": {
        "name": "policy_retriever",
        "description": ("Fetch the bike-share pricing page at url, extract its text and return the k "
                        "short snippets that best match query (membership price, included minutes, "
                        "per-minute rates, unlock fees, overage rules). The page is saved as a "
                        "snapshot with its capture time and SHA-256."),
        "input": {"type": "object", "properties": {
            "url": {"type": "string"}, "query": {"type": "string"},
            "k": {"type": "integer", "minimum": 1, "maximum": 8}},
            "required": ["url", "query"], "additionalProperties": False},
        "output": {"type": "object", "properties": {
            "prices": {"type": ["object", "null"], "description": "six named prices parsed from the page table"},
            "passages": {"type": "array", "items": {
            "type": "object", "properties": {"text": {"type": "string"}, "source": {"type": "string"},
                                             "score": {"type": "number"}}}}}},
    },
    "calculator": {
        "name": "calculator",
        "description": "Safe arithmetic. expression may contain only digits, + - * / ( ) . and spaces.",
        "input": {"type": "object", "properties": {
            "expression": {"type": "string", "pattern": r"^[0-9+\-*/().\s]+$"},
            "units": {"type": "string"}},
            "required": ["expression"], "additionalProperties": False},
        "output": {"type": "object", "properties": {"value": {"type": "number"},
                                                    "units": {"type": "string"}}},
    },
}


# ---- 1. csv_sql ------------------------------------------------------------------

def _parse_ts(text: str) -> datetime:
    return datetime.fromisoformat(text.strip()[:19])


class TripStore:
    """The uploaded CSV, loaded into an in-memory SQLite table `trips`."""

    def __init__(self, csv_text: str):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        if not rows:
            raise ValueError("the CSV has no rows")
        missing = {"rideable_type", "started_at", "ended_at"} - set(rows[0])
        if missing:
            raise ValueError(f"the CSV is missing columns: {sorted(missing)}")
        self.skipped = 0
        cols = list(rows[0].keys())
        derived = ["minutes", "bike", "month", "week_start", "over45"]
        self.conn.execute(f"CREATE TABLE trips ({', '.join(c + ' TEXT' for c in cols)}, "
                          "minutes INTEGER, bike TEXT, month TEXT, week_start TEXT, over45 INTEGER)")
        for r in rows:
            try:
                start, end = _parse_ts(r["started_at"]), _parse_ts(r["ended_at"])
            except ValueError:
                self.skipped += 1            # reported as a caveat
                continue
            minutes = max(1, math.ceil((end - start).total_seconds() / 60))
            bike = "classic" if r["rideable_type"] == "classic_bike" else "ebike"
            week = (start - timedelta(days=start.weekday())).date().isoformat()
            values = [r[c] for c in cols] + [minutes, bike, start.strftime("%Y-%m"), week,
                                             max(0, minutes - 45)]
            self.conn.execute(f"INSERT INTO trips VALUES ({', '.join('?' * (len(cols) + len(derived)))})",
                              values)
        self.conn.commit()
        self.row_count = len(rows) - self.skipped


_WRITE = re.compile(r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|"
                    r"reindex|truncate)\b", re.IGNORECASE)


def check_select(sql: str) -> str | None:
    """Part 5 tool defense: exactly one read-only SELECT. Returns the problem, or None."""
    stmt = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.DOTALL).strip().rstrip(";").strip()
    if ";" in stmt:
        return "only one SQL statement is allowed"
    if not re.match(r"^(select|with)\b", stmt, re.IGNORECASE):
        return "only SELECT queries are allowed"
    if _WRITE.search(re.sub(r"'[^']*'", "''", stmt)):     # ignore words inside string literals
        return "the query contains a write/DDL keyword; csv_sql is read-only"
    return None


def csv_sql(sql: str, store: TripStore, read_only: bool = True) -> dict:
    """read_only=False exists only to show the Part 5 'before tool defense' behaviour."""
    if read_only:
        problem = check_select(sql)
        if problem:
            return fail(f"csv_sql refused: {problem}", source="uploaded.csv")
        store.conn.execute("PRAGMA query_only = ON")           # second lock, inside SQLite
    else:
        store.conn.execute("PRAGMA query_only = OFF")
    try:
        if read_only:
            cur = store.conn.execute(sql)
        else:
            cur = store.conn.cursor()
            cur.executescript(sql) if ";" in sql.strip().rstrip(";") else cur.execute(sql)
        rows = [dict(r) for r in cur.fetchmany(MAX_ROWS)] if cur.description else []
        store.conn.commit()
    except sqlite3.Error as exc:
        hint = ""
        if "no such column" in str(exc):
            hint = " If this is a placeholder (e.g. UNLOCK), replace it with the number from the pricing page."
        return fail(f"SQL error: {exc}.{hint}", source="uploaded.csv")
    return ok({"rows": rows, "row_count": len(rows), "source": "uploaded.csv"}, source="uploaded.csv")


# ---- 2. policy_retriever -----------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Visible text, one line per block element, with the nearest heading kept."""

    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCKS = {"p", "div", "li", "td", "th", "tr", "h1", "h2", "h3", "h4", "h5", "br", "section",
              "strong", "span", "a"}

    def __init__(self):
        super().__init__()
        self.lines, self._buf, self._skip, self._tag = [], [], 0, None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag in self.BLOCKS:
            self._flush()
        self._tag = tag

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag in self.BLOCKS:
            self._flush(heading=tag in {"h1", "h2", "h3", "h4", "h5"})

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)

    def _flush(self, heading=False):
        text = " ".join(" ".join(self._buf).split())
        self._buf = []
        if text:
            self.lines.append(("# " if heading else "") + text)


def table_rows(raw: list[str]) -> list[str]:
    """Rebuild a comparison table as one quotable line per row.

    A pricing table comes out of the HTML as a run of column headings
    ("# Single ride", "# Day pass", ...), then each row as a label line
    ("Classic bike prices") followed by one cell per column. Joining a row's
    cells with their column names keeps "45 min free, then $0.17/min" tied to
    "Month pass" instead of floating free. Returns [] when there is no table.
    """
    cols, i = [], 0
    while i < len(raw):                              # first run of 3+ headings = the columns
        run = []
        while i < len(raw) and raw[i].startswith("# "):
            run.append(raw[i][2:])
            i += 1
        if len(run) >= 3:
            cols = run
            break
        i += 1
    if not cols:
        return []
    rows, n = [], len(cols)
    cells = raw[i:i + n]
    if all("$" in c for c in cells):                 # the plan-price row right under the headings
        rows.append("TABLE plan price - " + "; ".join(f"{c}: {v}" for c, v in zip(cols, cells)))
    done = set()
    for j in range(i, len(raw) - n):
        label = raw[j]
        if label.lower().endswith("prices") and label not in done:
            cells = raw[j + 1:j + 1 + n]
            if all("$" in c or "free" in c.lower() for c in cells):
                rows.append(f"TABLE {label} - " + "; ".join(f"{c}: {v}" for c, v in zip(cols, cells)))
                done.add(label)
    return rows


_PAGES: dict[str, dict] = {}            # url -> snapshot, so one run uses one capture


def fetch_page(url: str) -> dict:
    if url in _PAGES:
        return _PAGES[url]
    if url.startswith("file://") or Path(url).exists():
        raw = Path(url.removeprefix("file://")).read_bytes()
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (DATA260 HW7 s9275)"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
    html = raw.decode("utf-8", errors="replace")
    parser = _TextExtractor()
    parser.feed(html)
    lines, seen = table_rows(parser.lines), set()
    for line in parser.lines:                       # the pricing table repeats once per column
        if line not in seen and line not in lines:
            seen.add(line)
            lines.append(line)
    text = "\n".join(lines)
    snap = {"url": url, "captured_at": now(), "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "html_sha256": hashlib.sha256(raw).hexdigest(), "chars": len(text), "lines": lines}
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stem = snap["sha256"][:12]
    (SNAPSHOT_DIR / f"{stem}.txt").write_text(text, encoding="utf-8")
    meta = {k: v for k, v in snap.items() if k != "lines"} | {"text_file": f"{stem}.txt"}
    (SNAPSHOT_DIR / f"{stem}.json").write_text(json.dumps(meta, indent=2))
    snap["meta"] = meta
    _PAGES[url] = snap
    return snap


_MONEY = r"\$(\d+(?:\.\d+)?)"


def parse_prices(lines: list[str]) -> dict | None:
    """The six numbers the decision needs, read with regexes from the TABLE rows.

    Deterministic (no model): the cell under "Single ride" and "Month pass" in
    the plan-price, classic and ebike rows. None if the page has no such table.
    """
    rows = {}
    for ln in lines:
        if ln.startswith("TABLE ") and " - " in ln:
            label, cells = ln.split(" - ", 1)
            rows[label] = dict(c.split(": ", 1) for c in cells.split("; ") if ": " in c)
    try:
        plan, classic, ebike = rows["TABLE plan price"], rows["TABLE Classic bike prices"], rows["TABLE Ebike prices"]
        single_c = re.findall(_MONEY, classic["Single ride"])      # $1.00 to unlock, then $0.19/min
        single_e = re.findall(_MONEY, ebike["Single ride"])        # $1.00 unlock + $0.49/min
        return {"single_ride_unlock": float(single_c[0]),
                "single_ride_classic_per_min": float(single_c[1]),
                "single_ride_ebike_per_min": float(single_e[-1]),
                "month_pass_price": float(re.findall(_MONEY, plan["Month pass"])[0]),
                "month_pass_classic_overage_per_min": float(re.findall(_MONEY, classic["Month pass"])[-1]),
                "month_pass_ebike_per_min": float(re.findall(_MONEY, ebike["Month pass"])[-1])}
    except (KeyError, IndexError, ValueError):
        return None


_WORD = re.compile(r"[a-z0-9$.]+")
PRICE_WORDS = {"$", "min", "month", "unlock", "free", "ebike", "classic", "member", "pass", "per"}


def policy_retriever(url: str, query: str, k: int = 3) -> dict:
    try:
        snap = fetch_page(url)
    except Exception as exc:
        return fail(f"could not fetch {url}: {type(exc).__name__}: {exc}", source=url)
    q = set(_WORD.findall(query.lower()))
    heading, scored = "", []
    for line in snap["lines"]:
        if line.startswith("# "):
            heading = line[2:]
            continue
        text = line if len(line) <= 420 else line[:420] + "..."
        words = set(_WORD.findall(text.lower()))
        score = len(q & words) + 0.5 * len(PRICE_WORDS & words) + (1 if "$" in text else 0)
        if text.startswith("TABLE "):
            score += 3
        if score > 0:
            scored.append({"text": f"[{heading}] {text}" if heading and not text.startswith("TABLE ")
                           else text,
                           "source": url, "score": round(score, 2)})
    scored.sort(key=lambda p: -p["score"])
    return ok({"prices": parse_prices(snap["lines"]), "passages": scored[:max(1, min(k, 8))],
               "snapshot": snap["meta"]}, source=url)


# ---- 3. calculator ------------------------------------------------------------------

_ALLOWED = re.compile(r"^[0-9+\-*/().\s]+$")
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.USub: operator.neg, ast.UAdd: operator.pos}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


def calculator(expression: str, units: str | None = None) -> dict:
    if not _ALLOWED.match(expression or ""):
        return fail("expression may contain only digits, + - * / ( ) . and spaces. Replace every "
                    "name with the number from an earlier tool result, e.g. 600*1.00 + 4401*0.19")
    try:
        value = _eval(ast.parse(expression, mode="eval"))
    except ZeroDivisionError:
        return fail("division by zero")
    except (SyntaxError, ValueError) as exc:
        return fail(f"invalid expression: {exc}")
    out = {"value": round(value, 4)}
    if units:
        out["units"] = units
    return ok(out)
