"""Agent demo entrypoint.

TODO: implement per the Homework 1 instructions.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.model_client import ModelClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent demo")
    parser.add_argument("--task", help="Task description for the agent")
    args = parser.parse_args()

    client = ModelClient()
    print(f"provider={client.provider} model={client.model} task={args.task!r}")
    print("TODO: agent loop not implemented yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
