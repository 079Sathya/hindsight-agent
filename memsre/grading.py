"""normalize() + grade(): exact-match grading of short answers."""
from __future__ import annotations

import re

_HOURS = re.compile(r"(\d+) ?(?:h|hr|hrs|hour|hours)")
_DAYS = re.compile(r"(\d+) ?(?:day|days)")
_RATE = re.compile(r"(\d+) ?(?:requests/min|requests per minute|req/min|rpm)")


def normalize(s: str) -> str:
    s = (s or "").lower().strip().rstrip(".").replace(",", "")
    s = " ".join(s.split())
    if m := _HOURS.fullmatch(s):
        return f"{m.group(1)}h"
    if m := _DAYS.fullmatch(s):
        return m.group(1)
    if m := _RATE.fullmatch(s):
        return m.group(1)
    if s.startswith("yes"):
        return "yes"
    if s.startswith("no ") or s == "no":
        return "no"
    return s


def grade(short_answer: str, accepted: list[str]) -> bool:
    """EXACT match after normalize(), never substring: "10000" is not "1000"."""
    return normalize(short_answer) in {normalize(a) for a in accepted}
