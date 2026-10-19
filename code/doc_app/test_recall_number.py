"""Offline tests for parse_recall_number (AGENT.md: one valid and one invalid case at least).

Run:  python code/doc_app/test_recall_number.py
"""
from recall_number import parse_recall_number


def test_valid() -> None:
    assert parse_recall_number("F-0123-2026") == (123, 2026)
    assert parse_recall_number("  F-0001-2025 ") == (1, 2025)


def test_invalid() -> None:
    for bad in ["ABC-12", "F-123-2026", "F-0123-1999", ""]:
        try:
            parse_recall_number(bad)
        except ValueError as exc:
            assert repr(bad) in str(exc)          # the message names the bad value
        else:
            raise AssertionError(f"{bad!r} was accepted")


if __name__ == "__main__":
    test_valid()
    test_invalid()
    print("Xu Wang | test_recall_number: 2 tests passed")
