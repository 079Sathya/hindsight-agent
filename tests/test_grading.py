from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memsre.grading import grade, normalize  # noqa: E402


def test_thousands_separator_is_removed():
    assert normalize("1,000") == "1000"


def test_exact_match_not_substring():
    assert not grade("10000", ["1000"])
    assert grade("1,000", ["1000"])


def test_hours_unit():
    assert normalize("4 hours") == "4h"


def test_days_unit():
    assert normalize("730 days") == "730"


def test_no_with_explanation():
    assert normalize("No, it isn't included") == "no"


def test_yes_with_trailing_period():
    assert normalize("yes.") == "yes"
