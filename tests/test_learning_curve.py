from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memsre import lessons, store  # noqa: E402


def inc(id, status, affected, name="Kestrel Logistics"):
    return {"id": id, "customer_name": name, "failure_type": "RESOLUTION", "status": status,
            "blast_radius": {"answers_affected": affected, "answer_ids": []}}


def test_curve_reactive_then_prevented(monkeypatch):
    newest_first = [inc("INC-004", "prevented", 0), inc("INC-003", "prevented", 0),
                    inc("INC-002", "prevented", 0), inc("INC-001", "fixed", 2)]
    monkeypatch.setattr(store, "list_incidents", lambda: newest_first)
    curve = lessons.learning_curve()
    assert [p["id"] for p in curve] == ["INC-001", "INC-002", "INC-003", "INC-004"]
    assert [p["wrong_answers"] for p in curve] == [2, 0, 0, 0]
    assert [p["kind"] for p in curve] == ["reactive", "prevented", "prevented", "prevented"]
    assert [p["lesson_learned"] for p in curve] == [True, False, False, False]


def test_watch_catch_counts_the_answer_that_fired_it(monkeypatch):
    watched = {**inc("INC-002", "prevented", 0, name="Monsoon Trails"), "trigger": "watch"}
    monkeypatch.setattr(store, "list_incidents", lambda: [watched, inc("INC-001", "fixed", 2)])
    curve = lessons.learning_curve()
    assert [(p["kind"], p["wrong_answers"]) for p in curve] == [("reactive", 2), ("caught by watch", 1)]


def test_curve_open_incident_is_not_a_lesson(monkeypatch):
    monkeypatch.setattr(store, "list_incidents", lambda: [inc("INC-001", "open", 3)])
    curve = lessons.learning_curve()
    assert curve[0]["wrong_answers"] == 3 and not curve[0]["lesson_learned"]
