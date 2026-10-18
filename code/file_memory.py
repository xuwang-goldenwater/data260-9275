"""HW6 Part 4: file-based memory with AGENT.md (instructions) and MEMORY.md (facts).

MEMORY.md format:
    <!-- last_consolidated: 2026-10-18T16:50:00-07:00 -->
    # MEMORY.md
    ## Facts
    - [2026-10-12] User's daughter Mia is allergic to tree nuts.
    ## Resolved contradictions
    - [2026-10-18] Kept "..." (2026-10-11); superseded "..." (2026-09-02). Rule: newer date wins.

Functions the assignment asks for:
    load_memory_files        read AGENT.md and MEMORY.md
    build_system_prompt      put both into the system prompt
    read_last_consolidated   the timestamp in the first-line comment
    count_memory_lines       non-empty, non-comment lines
    needs_consolidation      > 40 lines, or last consolidation > 24 hours ago
plus consolidate() for /compact and dream() for /dream.

Consolidation never deletes silently. The model only proposes a plan (which lines are
duplicates, which contradict, which fact wins); the code renders the file from the plan,
keeping every line the plan does not mention, and writes each superseded fact into
"## Resolved contradictions". verify_no_silent_deletion() then re-reads the rendered text and
checks that every original fact still appears (verbatim, as a merged sentence, or as a
superseded fact).
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code" / "doc_app"))

AGENT_PATH = ROOT / "AGENT.md"
MEMORY_PATH = ROOT / "MEMORY.md"
MAX_MEMORY_LINES = 40
MAX_AGE = timedelta(hours=24)
# A merged sentence must stay close in meaning to every line it replaces (MiniLM cosine).
# Found in testing: a plan that merged "User's name is Xu Wang." and "User studies ... at SJSU."
# into one unrelated sentence deleted both facts while the text check still passed.
DUP_MIN_COSINE = 0.5

TIMESTAMP_RE = re.compile(r"<!--\s*last_consolidated:\s*(\S+)\s*-->")
FACT_RE = re.compile(r"^-\s*\[(\d{4}-\d{2}-\d{2})\]\s*(.+)$")


# ---------------------------------------------------------------- loading + prompt

def load_memory_files(agent_path: Path = AGENT_PATH,
                      memory_path: Path = MEMORY_PATH) -> Tuple[str, str]:
    """Return (AGENT.md text, MEMORY.md text). A missing MEMORY.md is an empty memory;
    a missing AGENT.md is an error because the agent has no instructions."""
    if not agent_path.exists():
        raise FileNotFoundError(f"AGENT.md not found at {agent_path}")
    memory = memory_path.read_text(encoding="utf-8") if memory_path.exists() else ""
    return agent_path.read_text(encoding="utf-8"), memory


def build_system_prompt(agent_text: str, memory_text: str) -> str:
    """AGENT.md first (how to behave), then MEMORY.md (what is known)."""
    return (
        "You are the project assistant for this repository. Follow the instructions in "
        "AGENT.md. Use the facts in MEMORY.md when they are relevant; if a fact is not in "
        "memory, say you do not know. Use the 'Code review mode' format only when the user "
        "asks you to review code.\n\n"
        "===== AGENT.md =====\n" + agent_text.strip() + "\n\n"
        "===== MEMORY.md =====\n" + (memory_text.strip() or "(empty)") + "\n"
    )


# ---------------------------------------------------------------- consolidation checks

def read_last_consolidated(memory_text: str) -> Optional[datetime]:
    """The time in <!-- last_consolidated: ISO-8601 -->, or None if absent or unreadable."""
    match = TIMESTAMP_RE.search(memory_text)
    if not match:
        return None
    try:
        when = datetime.fromisoformat(match.group(1))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def count_memory_lines(memory_text: str) -> int:
    """Non-empty lines outside HTML comments (headings count; the timestamp does not)."""
    return sum(1 for line in _strip_comments(memory_text).splitlines() if line.strip())


def fact_lines(memory_text: str) -> List[str]:
    """Lines of the form '- [YYYY-MM-DD] fact' anywhere in the file."""
    return [ln.strip() for ln in _strip_comments(memory_text).splitlines()
            if FACT_RE.match(ln.strip())]


def needs_consolidation(memory_text: str, now: Optional[datetime] = None) -> Tuple[bool, List[str]]:
    """True when MEMORY.md has more than 40 counted lines or its last consolidation is
    older than 24 hours (a file never consolidated counts as old). Returns the reasons."""
    now = now or datetime.now(timezone.utc)
    reasons = []
    lines = count_memory_lines(memory_text)
    if lines > MAX_MEMORY_LINES:
        reasons.append(f"{lines} lines > {MAX_MEMORY_LINES}")
    last = read_last_consolidated(memory_text)
    if last is None:
        reasons.append("never consolidated")
    elif now - last > MAX_AGE:
        reasons.append(f"last consolidated {(now - last).total_seconds() / 3600:.1f} h ago > 24 h")
    return bool(reasons), reasons


# ---------------------------------------------------------------- consolidation

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "duplicates": {"type": "array", "items": {"type": "object", "properties": {
            "lines": {"type": "array", "items": {"type": "integer"}},
            "merged_fact": {"type": "string"}}, "required": ["lines", "merged_fact"]}},
        "contradictions": {"type": "array", "items": {"type": "object", "properties": {
            "keep": {"type": "integer"},
            "superseded": {"type": "array", "items": {"type": "integer"}},
            "reason": {"type": "string"}}, "required": ["keep", "superseded", "reason"]}},
    },
    "required": ["duplicates", "contradictions"],
}


@dataclass
class Fact:
    line: int          # 1-based number among the fact lines
    date: str
    text: str


@dataclass
class ConsolidationReport:
    lines_before: int
    lines_after: int
    facts_before: int
    facts_after: int
    duplicates_merged: List[Dict[str, Any]] = field(default_factory=list)
    contradictions_resolved: List[Dict[str, Any]] = field(default_factory=list)
    not_accounted: List[int] = field(default_factory=list)
    plan_errors: List[str] = field(default_factory=list)
    model_tokens: Dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def parse_facts(memory_text: str) -> List[Fact]:
    facts = []
    for i, line in enumerate(fact_lines(memory_text), start=1):
        m = FACT_RE.match(line)
        facts.append(Fact(i, m.group(1), m.group(2).strip()))
    return facts


def _plan_prompt(facts: List[Fact]) -> str:
    numbered = "\n".join(f"L{f.line}: [{f.date}] {f.text}" for f in facts)
    return (
        "You are consolidating a memory file about one user. Each line has a number and the "
        "date it was learned.\n"
        "1. duplicates: groups of lines that state the SAME fact (same meaning, maybe other "
        "words). Give the line numbers and one merged sentence.\n"
        "2. contradictions: lines that cannot both be true now. Keep the line with the newer "
        "date and list the older ones as superseded. Give a short reason.\n"
        "Only list real duplicates and real contradictions; leave every other line out.\n\n"
        + numbered
    )


def _validate_plan(plan: Dict[str, Any], facts: List[Fact],
                   similarity=None) -> Tuple[List[Dict], List[Dict], List[str]]:
    """Drop plan entries that point at lines that do not exist or are used twice, and
    duplicate groups whose merged sentence does not mean the same as each member.
    similarity(a, b) -> cosine; None skips the meaning check."""
    by_line = {f.line: f for f in facts}
    valid = {f.line for f in facts}
    used: set = set()
    errors: List[str] = []
    dups, cons = [], []
    for c in plan.get("contradictions", []):
        lines = [c.get("keep")] + list(c.get("superseded", []))
        if not all(isinstance(n, int) and n in valid for n in lines) or len(lines) < 2:
            errors.append(f"contradiction with invalid lines {lines}")
            continue
        if used & set(lines):
            errors.append(f"contradiction reuses lines {sorted(used & set(lines))}")
            continue
        used |= set(lines)
        cons.append({"keep": c["keep"], "superseded": list(c["superseded"]),
                     "reason": str(c.get("reason", ""))[:200]})
    for d in plan.get("duplicates", []):
        lines = list(d.get("lines", []))
        if len(lines) < 2 or not all(isinstance(n, int) and n in valid for n in lines):
            errors.append(f"duplicate group with invalid lines {lines}")
            continue
        if used & set(lines):
            errors.append(f"duplicate group reuses lines {sorted(used & set(lines))}")
            continue
        merged = str(d.get("merged_fact", "")).strip()[:200]
        if similarity is not None:
            far = [n for n in lines if similarity(by_line[n].text, merged or by_line[lines[0]].text)
                   < DUP_MIN_COSINE]
            if far:
                errors.append(f"duplicate group {lines} rejected: merged sentence {merged!r} "
                              f"does not mean the same as lines {far}")
                continue
        used |= set(lines)
        dups.append({"lines": lines, "merged_fact": merged})
    return dups, cons, errors


def render_consolidated(facts: List[Fact], dups: List[Dict], cons: List[Dict],
                        now: datetime) -> Tuple[str, List[int]]:
    """Build the new MEMORY.md and return it with the line numbers nobody accounted for."""
    by_line = {f.line: f for f in facts}
    kept: List[str] = []
    resolved: List[str] = []
    accounted: set = set()

    for d in dups:
        newest = max((by_line[n] for n in d["lines"]), key=lambda f: f.date)
        text = d["merged_fact"] or newest.text
        kept.append(f"- [{newest.date}] {text}")
        accounted |= set(d["lines"])
    for c in cons:
        winner = by_line[c["keep"]]
        kept.append(f"- [{winner.date}] {winner.text}")
        old = "; ".join(f"\"{by_line[n].text}\" ({by_line[n].date})" for n in c["superseded"])
        resolved.append(f"- [{now:%Y-%m-%d}] Kept \"{winner.text}\" ({winner.date}); "
                        f"superseded {old}. Reason: {c['reason'] or 'newer date wins'}")
        accounted |= {c["keep"], *c["superseded"]}
    # facts the plan did not mention are unique facts: kept as they are
    kept.extend(f"- [{f.date}] {f.text}" for f in facts if f.line not in accounted)
    kept.sort(key=lambda ln: ln[3:13])                 # by date

    out = [f"<!-- last_consolidated: {now.isoformat(timespec='seconds')} -->",
           "# MEMORY.md", "", "## Facts", *kept]
    if resolved:
        out += ["", "## Resolved contradictions", *resolved]
    text = "\n".join(out) + "\n"
    return text, verify_no_silent_deletion(facts, dups, text)


def verify_no_silent_deletion(facts: List[Fact], dups: List[Dict], new_text: str) -> List[int]:
    """Independent check on the RENDERED file: return the original lines that vanished.

    A line survives if its text is in the new file, or it belongs to a duplicate group whose
    merged sentence is in the new file.
    """
    merged_for = {n: d["merged_fact"] for d in dups for n in d["lines"] if d["merged_fact"]}
    lost = []
    for f in facts:
        if f.text in new_text:
            continue
        if f.line in merged_for and merged_for[f.line] in new_text:
            continue
        lost.append(f.line)
    return lost


def consolidate(memory_text: str, model=None,
                now: Optional[datetime] = None) -> Tuple[str, ConsolidationReport]:
    """Merge duplicates and resolve contradictions explicitly. Returns (new text, report)."""
    now = now or datetime.now().astimezone()
    facts = parse_facts(memory_text)
    report = ConsolidationReport(count_memory_lines(memory_text), 0, len(facts), 0)
    if not facts:
        report.lines_after = report.lines_before
        return memory_text, report
    if model is None:
        import memory as chat_memory              # doc_app/memory.py: same HW1 adapter + model
        model = chat_memory.get_model()
    resp = model.complete([{"role": "user", "content": _plan_prompt(facts)}],
                          response_format=PLAN_SCHEMA, max_tokens=1200)
    report.model_tokens = {"input": resp.input_tokens, "output": resp.output_tokens}
    try:
        plan = json.loads(resp.text)
    except json.JSONDecodeError:
        plan = {"duplicates": [], "contradictions": []}
        report.plan_errors.append("model plan was not valid JSON; nothing merged")
    import memory as chat_memory
    def similarity(a: str, b: str) -> float:
        va, vb = chat_memory.embed([a, b])
        return float(va @ vb)
    dups, cons, errors = _validate_plan(plan, facts, similarity)
    report.plan_errors += errors
    new_text, missing = render_consolidated(facts, dups, cons, now)
    report.duplicates_merged = dups
    report.contradictions_resolved = cons
    report.not_accounted = missing
    report.lines_after = count_memory_lines(new_text)
    report.facts_after = len([ln for ln in new_text.split("## Resolved")[0].splitlines()
                              if FACT_RE.match(ln.strip())])
    return new_text, report


# ---------------------------------------------------------------- /dream


def dream(recent_user_messages: List[str], memory_text: str, model=None,
          today: Optional[str] = None) -> List[str]:
    """Durable facts from recent conversation that MEMORY.md does not hold yet.

    Reuses Part 2's guards (memory.statement_part + memory.grounded) so a question or an
    invented detail cannot enter the file. Returns the new lines; the caller appends them.
    """
    import memory as chat_memory
    model = model or chat_memory.get_model()
    today = today or datetime.now().strftime("%Y-%m-%d")
    statements = " ".join(s for s in (chat_memory.statement_part(m) for m in recent_user_messages) if s)
    if not statements:
        return []
    known = "\n".join(f.text for f in parse_facts(memory_text)) or "(none)"
    prompt = (
        "From the user's messages below, list facts worth remembering for future sessions "
        "(identity, family, allergies, stores, plans, preferences, project decisions). "
        "Only facts the user states; never guess. Skip facts already known. "
        "At most 5, each a short sentence starting with 'User' or \"User's <relative>\".\n\n"
        f"Already known:\n{known}\n\nUser's messages:\n{statements}"
    )
    schema = {"type": "object", "properties": {"facts": {"type": "array", "maxItems": 5,
              "items": {"type": "string"}}}, "required": ["facts"]}
    resp = model.complete([{"role": "user", "content": prompt}], response_format=schema,
                          max_tokens=300)
    try:
        candidates = [str(f).strip() for f in json.loads(resp.text).get("facts", [])]
    except json.JSONDecodeError:
        return []
    known_lower = {f.text.lower().rstrip(".") for f in parse_facts(memory_text)}
    new = [c for c in candidates if c and chat_memory.grounded(c, statements)
           and c.lower().rstrip(".") not in known_lower]
    return [f"- [{today}] {c}" for c in new]


def append_lines(memory_path: Path, lines: List[str]) -> None:
    """Append fact lines under ## Facts (creating the file if needed)."""
    text = memory_path.read_text(encoding="utf-8") if memory_path.exists() else ""
    if not text.strip():
        text = "# MEMORY.md\n\n## Facts\n"
    if "## Resolved contradictions" in text:
        head, tail = text.split("## Resolved contradictions", 1)
        text = head.rstrip("\n") + "\n" + "\n".join(lines) + "\n\n## Resolved contradictions" + tail
    else:
        text = text.rstrip("\n") + "\n" + "\n".join(lines) + "\n"
    memory_path.write_text(text, encoding="utf-8")
