"""
DATA 260 - Homework 1, Part 4: model client and token accounting.

A small command-line chat that imports the shared adapter from
src/model_client.py. Every model call goes through that adapter; this file
contains no direct model API calls of its own.

The system prompt is AGENT.md, read from disk at startup. It demands
bullet-only replies, and after every turn this client checks whether the model
actually complied.

Commands:
    /stats    turn count, cumulative tokens, serialized history length
    /history  print the conversation as it will be sent on the next turn
    /quit     exit and print the cumulative summary

Usage:
    python hw1_client.py                 interactive
    python hw1_client.py --script        run the recorded five-turn session
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from model_client import ModelClient, DEFAULT_MODEL  # noqa: E402

AGENT_MD = REPO_ROOT / "AGENT.md"

RULE = "=" * 78


# ---------------------------------------------------------------------------
# AGENT.md compliance check
# ---------------------------------------------------------------------------


def check_bullet_only(reply: str) -> Dict[str, Any]:
    """Verify the model obeyed the bullet-only contract in AGENT.md.

    Asking for a format is not the same as getting it. This turns the
    instruction into something measurable instead of assumed.
    """
    lines = [ln.strip() for ln in reply.strip().splitlines() if ln.strip()]
    violations: List[str] = []

    if not lines:
        violations.append("empty reply")

    non_bullet = [ln for ln in lines if not ln.startswith(("- ", "* "))]
    if non_bullet:
        violations.append(f"{len(non_bullet)} line(s) do not start with a bullet")

    if len(lines) > 6:
        violations.append(f"{len(lines)} bullets, limit is 6")

    if "```" in reply:
        violations.append("contains a code fence")

    over_long = [
        ln for ln in lines
        if ln.startswith(("- ", "* ")) and len(ln.split()) - 1 > 25
    ]
    if over_long:
        violations.append(f"{len(over_long)} bullet(s) exceed 25 words")

    return {
        "compliant": not violations,
        "violations": violations,
        "bullet_count": len(lines) - len(non_bullet),
        "line_count": len(lines),
    }


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


class ReviewClient:
    def __init__(self, model: str = DEFAULT_MODEL, temperature: float = 0.0) -> None:
        if not AGENT_MD.exists():
            raise SystemExit(f"AGENT.md not found at {AGENT_MD}")
        self.system_prompt = AGENT_MD.read_text(encoding="utf-8")
        self.client = ModelClient(model=model, temperature=temperature)

        # The full conversation, exactly as it is sent to the model each turn.
        self.history: List[Dict[str, str]] = [
            {"role": "system", "content": self.system_prompt}
        ]

    # -- accounting --------------------------------------------------------

    def history_length(self) -> Dict[str, int]:
        """Serialized size of the conversation. Read-only: history is untouched."""
        serialized = json.dumps(self.history, ensure_ascii=False)
        return {
            "messages": len(self.history),
            "chars": len(serialized),
            "bytes": len(serialized.encode("utf-8")),
        }

    def print_stats(self, label: str = "") -> None:
        s = self.client.stats()
        h = self.history_length()
        suffix = f"  {label}" if label else ""
        print()
        print(RULE)
        print(f"/stats{suffix}")
        print(RULE)
        print(f"  turn count                        : {s['turn_count']}")
        print(f"  cumulative input tokens           : {s['cumulative_input_tokens']}")
        print(f"  cumulative output tokens          : {s['cumulative_output_tokens']}")
        print(f"  cumulative total tokens           : {s['cumulative_total_tokens']}")
        print(f"  conversation messages             : {h['messages']}")
        print(f"  serialized history length (chars) : {h['chars']}")
        print(f"  serialized history length (bytes) : {h['bytes']}")
        print(RULE)
        print()

    # -- one turn ----------------------------------------------------------

    def ask(self, user_text: str) -> None:
        self.history.append({"role": "user", "content": user_text})

        response = self.client.complete(messages=self.history)
        reply = response.text.strip()

        self.history.append({"role": "assistant", "content": reply})

        compliance = check_bullet_only(reply)

        print(reply)
        print()
        print(
            f"[turn {self.client.turn_count}] "
            f"input tokens = {response.input_tokens}  "
            f"output tokens = {response.output_tokens}  "
            f"total tokens = {response.total_tokens}  "
            f"({response.latency_ms:.0f} ms)"
        )
        if compliance["compliant"]:
            print(f"[AGENT.md bullet-only check] PASS "
                  f"({compliance['bullet_count']} bullets)")
        else:
            print(f"[AGENT.md bullet-only check] FAIL "
                  f"-> {'; '.join(compliance['violations'])}")
        print()

    # -- exit --------------------------------------------------------------

    def print_exit_summary(self) -> None:
        s = self.client.stats()
        h = self.history_length()
        print()
        print(RULE)
        print("SESSION TOTALS")
        print(RULE)
        print(f"  turns                             : {s['turn_count']}")
        print(f"  cumulative input tokens           : {s['cumulative_input_tokens']}")
        print(f"  cumulative output tokens          : {s['cumulative_output_tokens']}")
        print(f"  cumulative total tokens           : {s['cumulative_total_tokens']}")
        print(f"  serialized history length (chars) : {h['chars']}")
        print(RULE)


# ---------------------------------------------------------------------------
# The recorded five-turn session
# ---------------------------------------------------------------------------

SCRIPT_TURNS = [
    # 1
    """Review this JavaScript:

const createSubmissionCounter = () => {
  let count = 0;
  return () => {
    count = count + 1;
    return count;
  };
};""",
    # 2
    """Review this validation function:

const validateRecallNotice = (description, agreedToTerms) => {
  if (description.trim().length <= 25) {
    alert("Recall Details must be longer than 25 characters.");
    return false;
  }
  if (!agreedToTerms) {
    alert("Please agree to the terms and conditions.");
    return false;
  }
  return true;
};""",
    # 3
    """Review this Python:

def clamp_summary(summary, limit=25):
    words = str(summary).split()
    if len(words) <= limit:
        return " ".join(words), False
    return " ".join(words[:limit]), True""",
    # 4  - depends on earlier turns
    "Of the three functions I have shown you so far, which one is most likely to fail on unexpected input, and why?",
    # 5  - depends on the whole conversation
    "List the distinct defects you have reported across this entire conversation, without repeating any.",
]


def run_script(client: ReviewClient) -> None:
    for i, text in enumerate(SCRIPT_TURNS, start=1):
        print(RULE)
        print(f"USER (turn {i})")
        print(RULE)
        print(text)
        print()
        print(f"--- ASSISTANT (turn {i}) ---")
        client.ask(text)

        if i in (3, 5):
            client.print_stats(label=f"after turn {i}")

    client.print_exit_summary()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run_interactive(client: ReviewClient) -> None:
    print("Code review client. Paste code, then a blank line to send.")
    print("Commands: /stats  /history  /quit")
    print()
    buffer: List[str] = []
    while True:
        try:
            line = input("> " if not buffer else "  ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        stripped = line.strip()

        if not buffer and stripped in ("/quit", "/exit"):
            break
        if not buffer and stripped == "/stats":
            client.print_stats()
            continue
        if not buffer and stripped == "/history":
            print(json.dumps(client.history, indent=2, ensure_ascii=False))
            continue

        if stripped == "" and buffer:
            client.ask("\n".join(buffer))
            buffer = []
            continue
        if stripped == "":
            continue

        buffer.append(line)

    client.print_exit_summary()


def main() -> int:
    parser = argparse.ArgumentParser(description="HW1 model client")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--script", action="store_true",
        help="run the recorded five-turn session with /stats after turns 3 and 5",
    )
    args = parser.parse_args()

    client = ReviewClient(model=args.model, temperature=args.temperature)
    print(f"model: {args.model}   temperature: {args.temperature}")
    print(f"system prompt: AGENT.md ({len(client.system_prompt)} chars)")
    print()

    if args.script:
        run_script(client)
    else:
        run_interactive(client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
