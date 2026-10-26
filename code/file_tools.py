"""
HW7 Part 6 - file tools and a bash safety gate (pure Python, no model).

Six tools. Every path is resolved inside SANDBOX; anything that escapes it
(../, an absolute path elsewhere, a symlink out) is refused.

    read_file(path, max_lines=None)               -> {"path", "content", "lines", "truncated"}
    write_file(path, content)                     -> {"path", "bytes"}
    edit_file(path, old, new)                     -> {"path", "diff"}   (short unified diff)
    glob_files(pattern)                           -> {"matches": [...]}
    search_in_files(pattern, file_pattern="*")    -> {"hits": [{"path","line","text"}]}
    bash(command, auto_approve=False)             -> {"allowed", "reason", "stdout", "stderr", "returncode"}

Safety gate, two independent checks:
    SAFE_PREFIXES      allow-list: commands that may run without asking
    is_destructive()   deny-list: recursive deletion, privilege escalation,
                       permission/ownership changes, raw-device writes,
                       filesystem creation, redirection to root paths
    confirm_bash()     destructive -> blocked unless auto_approve=True
                       every segment on the allow-list -> allowed
                       anything else -> blocked unless auto_approve=True
The deny-list is checked first, so a command that starts with a safe prefix
(echo ... > /etc/hosts, ls && rm -rf x) is still blocked.
"""
from __future__ import annotations

import difflib
import fnmatch
import re
import subprocess
import tempfile
from pathlib import Path

SANDBOX = Path(tempfile.gettempdir()) / "s9275_sandbox"

# ---- sandbox ---------------------------------------------------------------


def set_sandbox(path: str | Path) -> Path:
    """Point the tools at a (temporary) course sandbox directory."""
    global SANDBOX
    SANDBOX = Path(path).resolve()
    SANDBOX.mkdir(parents=True, exist_ok=True)
    return SANDBOX


def _inside(path: str | Path) -> Path:
    p = (SANDBOX / path).resolve()
    if p != SANDBOX and SANDBOX not in p.parents:
        raise PermissionError(f"path escapes the sandbox: {path}")
    return p


def _rel(p: Path) -> str:
    return str(p.relative_to(SANDBOX))


# ---- file tools ------------------------------------------------------------


def read_file(path: str, max_lines: int | None = None) -> dict:
    lines = _inside(path).read_text(encoding="utf-8").splitlines()
    shown = lines if max_lines is None else lines[:max_lines]
    return {"path": path, "content": "\n".join(shown), "lines": len(shown),
            "truncated": len(shown) < len(lines)}


def write_file(path: str, content: str) -> dict:
    p = _inside(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"path": path, "bytes": len(content.encode("utf-8"))}


def edit_file(path: str, old: str, new: str) -> dict:
    """Replace exactly one occurrence of `old`; return a short unified diff."""
    p = _inside(path)
    before = p.read_text(encoding="utf-8")
    count = before.count(old)
    if count != 1:
        raise ValueError(f"'old' must match exactly once, matched {count} times")
    after = before.replace(old, new, 1)
    p.write_text(after, encoding="utf-8")
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(),
                                fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="", n=1)
    return {"path": path, "diff": "\n".join(diff)}


def glob_files(pattern: str) -> dict:
    matches = sorted(_rel(p) for p in SANDBOX.glob(pattern) if p.is_file())
    return {"pattern": pattern, "matches": matches}


def search_in_files(pattern: str, file_pattern: str = "*") -> dict:
    """Regex search over files whose name matches file_pattern (e.g. '*.py')."""
    rx = re.compile(pattern)
    hits = []
    for p in sorted(SANDBOX.rglob("*")):
        if not p.is_file() or not fnmatch.fnmatch(p.name, file_pattern):
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if rx.search(line):
                hits.append({"path": _rel(p), "line": n, "text": line.strip()})
    return {"pattern": pattern, "file_pattern": file_pattern, "hits": hits}


# ---- safety gate -----------------------------------------------------------

# Allow-list, matched against the start of each command segment
# (segments are split on ; && || |), on a word boundary.
# Fix after the first test run: plain "python3" was a FALSE ALLOW, because
# `python3 -c "__import__('shutil').rmtree('data')"` runs arbitrary code that the
# shell-text deny-list cannot see. Only the exact read-only form stays allowed.
# "find" removed for the same reason: `find . -exec rm {} +` deletes and -exec runs
# any program; glob_files covers the read-only use.
SAFE_PREFIXES = (
    "ls", "pwd", "cat", "head", "tail", "wc", "grep", "echo", "python3 --version",
)

_DENY = [
    ("recursive deletion", re.compile(r"\brm\b[^;&|]*\s(-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b"
                                      r"|\bfind\b[^;&|]*\s-delete\b")),
    ("privilege escalation", re.compile(r"(^|[;&|]\s*|\s)(sudo|doas|su)(\s|$)")),
    ("permission/ownership change", re.compile(r"\b(chmod|chown|chgrp)\b")),
    ("raw-device write", re.compile(r"\bdd\b[^;&|]*\bof=/dev/|>\s*/dev/(sd|disk|nvme|hd|rdisk)")),
    ("filesystem creation", re.compile(r"\b(mkfs(\.\w+)?|mke2fs|newfs)\b|\bdiskutil\s+erase")),
    ("redirection to root path", re.compile(r"(>{1,2}|\btee\b(\s+-a)?)\s*/(?!dev/null\b)")),
]


def destructive_reason(command: str) -> str | None:
    for label, rx in _DENY:
        if rx.search(command):
            return label
    return None


def is_destructive(command: str) -> bool:
    return destructive_reason(command) is not None


def _segments(command: str) -> list[str]:
    return [s.strip() for s in re.split(r"&&|\|\||;|\|", command) if s.strip()]


def _is_safe(command: str) -> bool:
    if "$(" in command or "`" in command:        # command substitution hides what runs
        return False
    for seg in _segments(command):
        if not any(seg == p or seg.startswith(p + " ") for p in SAFE_PREFIXES):
            return False
    return True


def confirm_bash(command: str, auto_approve: bool = False) -> dict:
    """Allow/block decision with a short reason. Never runs anything."""
    reason = destructive_reason(command)
    if reason:
        if auto_approve:
            return {"allow": True, "reason": f"destructive ({reason}) - explicitly confirmed"}
        return {"allow": False, "reason": f"blocked: destructive ({reason}) needs confirmation"}
    if _is_safe(command):
        return {"allow": True, "reason": "allowed: every segment matches SAFE_PREFIXES"}
    if auto_approve:
        return {"allow": True, "reason": "not on allow-list - explicitly confirmed"}
    return {"allow": False, "reason": "blocked: not on allow-list, needs confirmation"}


def bash(command: str, auto_approve: bool = False, timeout: int = 10) -> dict:
    decision = confirm_bash(command, auto_approve)
    if not decision["allow"]:
        return {"allowed": False, "reason": decision["reason"]}
    proc = subprocess.run(command, shell=True, cwd=SANDBOX, capture_output=True,
                          text=True, timeout=timeout)
    return {"allowed": True, "reason": decision["reason"], "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:], "returncode": proc.returncode}
