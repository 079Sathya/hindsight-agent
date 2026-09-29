from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memsre import autonomy, diagnose, investigator, tools  # noqa: E402
from ui import live  # noqa: E402


class _Recorder:
    def __init__(self):
        self.htmls = []

    def html(self, body):
        self.htmls.append(body)


class _Parent:
    def __init__(self):
        self.placeholders = []

    def empty(self):
        r = _Recorder()
        self.placeholders.append(r)
        return r


class _Listener:
    def __init__(self):
        self.events = []

    def __getattr__(self, name):
        if name.startswith("on_"):
            return lambda *a: self.events.append((name, a))
        raise AttributeError(name)


def _module(fn):
    return types.SimpleNamespace(fn=fn)


def prompt(*turns: str) -> str:
    """An agent-turn prompt shaped like investigator.run_loop's (case, transcript, working memory)."""
    body = "\n\n".join(turns) if turns else "(none yet)"
    return f"CASE\n...\n\nSTEPS SO FAR:\n{body}\n\nTURNS LEFT: 7\n\nYour next JSON object:"


TOOL_TURN = "TURN {n}\nthought: search\naction: recall_whole_bank {{}}\nresult:\nRESULT"
PUSHBACK = "TURN {n}: VERDICT REJECTED — a RESOLUTION verdict needs a compare_records check first. Continue the investigation with a tool call."
INVALID = "TURN {n}: INVALID REPLY — unknown tool 'nope'. Reply with exactly one JSON object in the required format."


def test_wrap_is_an_exact_pass_through():
    calls = []

    def fn(a, b=2, *, c=3):
        calls.append((a, b, c))
        return {"sum": a + b + c}
    m = _module(fn)
    live._wrap(m, "fn", before=lambda *a, **k: live._notify("on_think"), after=lambda r, *a, **k: live._notify("on_reply", r))
    out = m.fn(1, b=5, c=7)
    assert out == {"sum": 13} and calls == [(1, 5, 7)] and m.fn.__ms_live__ and m.fn.__wrapped__ is fn


def test_wrap_reraises_the_same_exception_and_reports_it():
    class Boom(Exception):
        pass

    def fn():
        raise Boom("x")
    m = _module(fn)
    listener = _Listener()
    live._wrap(m, "fn", error=lambda e: live._notify("on_reply_error", e))
    live._local.listener = listener
    try:
        with pytest.raises(Boom):
            m.fn()
    finally:
        live._local.listener = None
    assert listener.events and listener.events[0][0] == "on_reply_error"


def test_wrap_is_idempotent():
    m = _module(lambda: 1)
    live._wrap(m, "fn")
    first = m.fn
    live._wrap(m, "fn")
    assert m.fn is first


def test_no_listener_means_no_calls_and_other_threads_are_isolated():
    m = _module(lambda: "ok")
    live._wrap(m, "fn", before=lambda *a, **k: live._notify("on_think"))
    mine = _Listener()
    live._local.listener = mine
    seen_in_thread = []
    try:
        t = threading.Thread(target=lambda: seen_in_thread.append((m.fn(), live._listener())))
        t.start()
        t.join()
    finally:
        live._local.listener = None
    assert seen_in_thread == [("ok", None)] and mine.events == []
    assert m.fn() == "ok"


def test_install_wraps_the_five_seams_and_rewraps_after_a_restore(monkeypatch):
    live.install()
    for mod, name in ((investigator, "llm_json"), (tools, "run_tool"), (diagnose, "pipeline_incident"),
                      (autonomy, "investigate_candidate"), (autonomy, "_act")):
        assert getattr(getattr(mod, name), "__ms_live__", False), (mod.__name__, name)
    original = investigator.llm_json.__wrapped__
    monkeypatch.setattr(investigator, "llm_json", original)
    live.install()
    assert investigator.llm_json.__ms_live__ and investigator.llm_json.__wrapped__ is original


def test_last_turn_reads_the_transcript():
    assert live.last_turn(prompt()) == (0, None, "")
    assert live.last_turn(prompt(TOOL_TURN.format(n=1))) == (1, None, "")
    n, kind, msg = live.last_turn(prompt(TOOL_TURN.format(n=1), PUSHBACK.format(n=2)))
    assert (n, kind) == (2, "rejected") and msg.startswith("a RESOLUTION verdict needs a compare_records check")
    n, kind, msg = live.last_turn(prompt(TOOL_TURN.format(n=1), INVALID.format(n=2)))
    assert (n, kind, msg) == (2, "invalid", "unknown tool 'nope'")


def test_live_trace_settles_steps_from_the_transcript():
    parent = _Parent()
    with live.LiveTrace(parent, title="Investigating") as lt:
        assert live._listener() is lt
        lt.on_think(prompt())
        lt.on_reply({"thought": "search", "action": {"tool": "recall_whole_bank", "args": {"query": "Growth"}}})
        assert lt._cur().state == "running"
        lt.on_tool_start("recall_whole_bank", {"query": "Growth"})
        lt.on_tool_end("recall_whole_bank", {"query": "Growth"}, "RESULT TEXT")
        assert lt._cur().state == "done"
        lt.on_think(prompt(TOOL_TURN.format(n=1)))
        lt.on_reply({"thought": "guess", "final": {"failure_type": "RESOLUTION"}})
        assert lt._cur().state == "verdict"
        lt.on_think(prompt(TOOL_TURN.format(n=1), PUSHBACK.format(n=2)))       # the verdict was pushed back
        steps = lt.groups[0]["steps"]
        assert steps[1].state == "rejected" and "compare_records check" in steps[1].step["result_summary"]
        lt.on_reply({"thought": "bad", "action": {"tool": "nope", "args": {}}})
        lt.on_think(prompt(TOOL_TURN.format(n=1), PUSHBACK.format(n=2), INVALID.format(n=3)))
        assert steps[2].state == "invalid" and steps[2].step["result_summary"] == "unknown tool 'nope'"
        lt.on_reply_error(ValueError("the reply was not valid JSON"))
        assert steps[3].state == "invalid"
    assert live._listener() is None
    ph = parent.placeholders[0]
    assert ph.htmls and "ms-trace live" in ph.htmls[-1] and "RESULT TEXT" in "".join(ph.htmls)
    lt.finish({"id": "INC-009", "customer_name": "K", "investigation": {"steps": [{"tool": "final", "thought": "t"}],
                                                                           "agent_failure_type": "RESOLUTION", "confidence": 0.9}})
    assert "Investigation complete" in ph.htmls[-1] and "ms-trace live" not in ph.htmls[-1]
    n = len(ph.htmls)
    lt.on_think(prompt())
    assert len(ph.htmls) == n                                       # after finish nothing re-renders


def test_steps_animate_only_on_first_render():
    parent = _Parent()
    with live.LiveTrace(parent, title="Investigating") as lt:
        lt.on_think(prompt())
        lt.on_reply({"thought": "s", "action": {"tool": "recall_whole_bank", "args": {}}})
        lt.on_tool_start("recall_whole_bank", {})
    htmls = parent.placeholders[0].htmls
    assert "anim" in htmls[1] and "ms-step running anim" not in htmls[-1]


def test_a_new_agent_loop_starts_a_next_hypothesis_group():
    parent = _Parent()
    with live.LiveTrace(parent, title="Investigating") as lt:
        lt.on_think(prompt())
        lt.on_reply({"thought": "done", "final": {"failure_type": "RESOLUTION"}})
        lt.on_think(prompt())                                        # a fresh run_loop: next hypothesis
    assert lt.groups[0]["steps"][0].state == "accepted"
    assert len(lt.groups) == 2 and lt.groups[1]["label"].startswith("Next hypothesis")


def test_a_click_during_the_run_is_deferred_until_resume():
    from streamlit.runtime.scriptrunner_utils.exceptions import RerunException

    class ClickingPlaceholder(_Recorder):
        def html(self, body):
            super().html(body)
            if len(self.htmls) == 2:
                raise RerunException(None)                          # a widget click surfaced at this yield point

    parent = _Parent()
    parent.empty = lambda: parent.placeholders.append(ClickingPlaceholder()) or parent.placeholders[-1]
    m = _module(lambda: "incident")
    live._wrap(m, "fn", before=lambda *a, **k: live._notify("on_think", prompt()))
    with live.LiveTrace(parent, title="Investigating") as lt:
        result = m.fn()                                               # the backend call is NOT aborted
    assert result == "incident" and lt.pending is not None
    with pytest.raises(RerunException):
        lt.resume()
    lt.resume()                                                       # re-raised once only


def test_watch_mode_stays_quiet_until_a_rule_fires_and_is_finalized():
    parent = _Parent()
    with live.LiveTrace(parent, title="Watch", mode="watch") as lt:
        assert parent.placeholders == []
        lt.on_candidate_start({"a": "saffron", "b": "mehta-bros", "value": "mehtabros.co.in", "rule_id": "r"})
        lt.on_think(prompt())
        lt.on_reply({"thought": "same", "final": {"same_customer": True}})
        lt.on_candidate_end({"same_customer": True, "confidence": 0.95,
                             "investigation": {"steps": [{"tool": "compare_records"}, {"tool": "final"}]}})
        lt.on_finding({"status": "prevented", "confidence": 0.95, "incident_id": "INC-005"})
    lt.finish_watch()
    html = parent.placeholders[0].htmls[-1]
    assert "Prevented" in html and "ms-trace live" not in html
    assert [s.state for s in lt.groups[0]["steps"]] == ["done", "accepted"]      # rebuilt from the finding's trace


def test_quiet_watch_renders_nothing():
    parent = _Parent()
    with live.LiveTrace(parent, title="Watch", mode="watch") as lt:
        pass
    lt.finish_watch()
    assert parent.placeholders == []


def test_scan_marks_confirmed_candidates_as_proposed():
    parent = _Parent()
    with live.LiveTrace(parent, title="Scan", mode="scan") as lt:
        lt.on_candidate_start({"a": "a", "b": "b", "value": "x.in", "rule_id": "r"})
        lt.on_candidate_end({"same_customer": True, "confidence": 0.95, "investigation": {"steps": []}})
    assert lt.groups[-1]["outcome"]["status"] == "proposed"


def test_failures_finalize_instead_of_looking_frozen():
    parent = _Parent()
    with live.LiveTrace(parent, title="Patrol running", mode="patrol") as lt:
        lt.on_candidate_start({"a": "a", "b": "b", "value": "x.in", "rule_id": "r"})
        lt.on_think(prompt())
    lt.finish_patrol(None)
    html = parent.placeholders[0].htmls[-1]
    assert "Patrol failed" in html and "ms-step error" in html and "Thinking about the next step" not in html
    parent = _Parent()
    with live.LiveTrace(parent, title="Investigating") as lt:
        lt.on_think(prompt())
    lt.finish(None)
    assert "Investigation failed" in parent.placeholders[0].htmls[-1]


def test_fallback_and_its_failure_are_shown():
    parent = _Parent()
    with live.LiveTrace(parent, title="Investigating") as lt:
        lt.on_fallback()                                             # no agent steps: the pipeline was forced
        assert lt._cur().step["forced"] is True
        lt.on_fallback_error(RuntimeError("TPD limit"))
    assert lt._cur().state == "error" and "TPD limit" in lt._cur().step["result_summary"]


def test_listener_errors_never_break_the_backend_call():
    class Broken:
        def on_think(self, *a):
            raise RuntimeError("render bug")
    m = _module(lambda: 42)
    live._wrap(m, "fn", before=lambda *a, **k: live._notify("on_think"))
    live._local.listener = Broken()
    try:
        assert m.fn() == 42
    finally:
        live._local.listener = None
