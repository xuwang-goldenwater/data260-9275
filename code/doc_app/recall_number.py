"""HW6 Part 4-4: one function written to follow AGENT.md (checked in the report)."""
import re
from typing import Tuple

import config


def parse_recall_number(value: str) -> Tuple[int, int]:
    """Split an FDA recall number like "F-0123-2026" into (sequence, year).

    Returns (123, 2026) for "F-0123-2026". Surrounding spaces are ignored.
    Raises ValueError when the value does not match config.RECALL_NUMBER_PATTERN
    or the year is outside 2000-2099.
    """
    text = value.strip()
    if not re.fullmatch(config.RECALL_NUMBER_PATTERN, text):
        raise ValueError(f"invalid recall number {value!r}: expected F-NNNN-YYYY")
    _, sequence, year = text.split("-")
    if not 2000 <= int(year) <= 2099:
        raise ValueError(f"invalid recall number {value!r}: year {year} out of range")
    return int(sequence), int(year)
