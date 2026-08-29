"""Homework 1 driver.

Runs the assignment tasks and writes raw output to reports/hw01/raw/.

TODO: implement per the Homework 1 instructions.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.model_client import ModelClient  # noqa: E402

RAW_DIR = REPO_ROOT / "reports" / "hw01" / "raw"


def main() -> int:
    parser = argparse.ArgumentParser(description="Homework 1 runs")
    parser.add_argument("--n", type=int, default=1, help="Number of runs")
    parser.add_argument("--out", type=Path, default=RAW_DIR)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    client = ModelClient()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    record = {
        "timestamp": stamp,
        "provider": client.provider,
        "model": client.model,
        "runs": args.n,
        "status": "TODO: not implemented",
    }
    (args.out / f"run_{stamp}.json").write_text(json.dumps(record, indent=2))
    print(f"wrote {args.out / f'run_{stamp}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
