"""Live agent trace: watch the investigator (and the patrol) work, step by step, without changing memsre/.

The agent loop already calls these through module attributes, so the UI can observe them:
  - ``investigator.run_loop`` calls ``investigator.llm_json`` and ``tools.run_tool`` on every turn;
  - ``investigator._investigate_core`` calls ``diagnose.pipeline_incident`` when the agent falls back;
  - ``autonomy.patrol`` / ``autonomy.watch`` call ``investigate_candidate`` and ``_act`` per candidate.
``install()`` wraps those five attributes once. Each wrapper returns exactly what the original returns and re-raises
exactly what it raises; it only notifies the listener registered for the *current thread* (every Streamlit session runs
its script in its own thread), so other sessions, the CLI scripts and the tests see no difference.

Step outcomes are not guessed: every agent turn's prompt carries the transcript so far, whose last entry says whether the
previous turn ran a tool, was an invalid reply or had its verdict pushed back (with the reason). After a candidate, the
finding's stored trace is the authority. A click during a long run cannot abort it: Streamlit's rerun request surfaces as
a ScriptControlException inside a render call; the listener stashes it, the backend call finishes, and ``resume()``
re-raises it afterwards.
"""
from __future__ import annotations

import functools
import re
import threading

from memsre import autonomy, diagnose, investigator, tools

from . import components as C

try:  # Streamlit's rerun/stop signal (a BaseException)
    from streamlit.runtime.scriptrunner_utils.exceptions import ScriptControlException as _Control
except ImportError:  # pragma: no cover - other Streamlit versions
    class _Control(BaseException):
        pass

_local = threading.local()
LIVE_STEPS = 5                      # the live view shows the newest steps; finish() renders the full trace
_TURN = re.compile(r"TURN (\d+)(: (INVALID REPLY|VERDICT REJECTED) — (.*?)\. (?:Reply with exactly|Continue the investigation))?",
                   re.S)


def _listener():
    return getattr(_local, "listener", None)


def _notify(method: str, *args) -> None:
    listener = _listener()
    if listener is None:
        return
    try:
        getattr(listener, method)(*args)
    except _Control as e:            # a click asked for a rerun: let the backend call finish first
        if getattr(listener, "pending", None) is None:
            listener.pending = e
    except Exception:  # noqa: BLE001 - rendering must never break the backend call
        pass


def _wrap(module, name: str, *, before=None, after=None, error=None) -> None:
    original = getattr(module, name)
    if getattr(original, "__ms_live__", False):
        return

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        if before is not None:
            before(*args, **kwargs)
        try:
            result = original(*args, **kwargs)
        except BaseException as e:
            if error is not None:
                error(e)
            raise
        if after is not None:
            after(result, *args, **kwargs)
        return result

    wrapper.__ms_live__ = True
    setattr(module, name, wrapper)


def _tool_name(args) -> str:
    tool = args[1] if len(args) > 1 else None
    return getattr(tool, "name", str(tool))


def _prompt(a, k):
    return a[1] if len(a) > 1 else k.get("user", "")


def install() -> None:
    """Wrap the five seams (idempotent per attribute: a wrapper carries ``__ms_live__``)."""
    _wrap(investigator, "llm_json",
          before=lambda *a, **k: _notify("on_think", _prompt(a, k)),
          after=lambda reply, *a, **k: _notify("on_reply", reply),
          error=lambda e: _notify("on_reply_error", e))
    _wrap(tools, "run_tool",
          before=lambda *a, **k: _notify("on_tool_start", _tool_name(a), (a[2] if len(a) > 2 else k.get("args")) or {}),
          after=lambda result, *a, **k: _notify("on_tool_end", _tool_name(a), (a[2] if len(a) > 2 else k.get("args")) or {},
                                                result))
    _wrap(diagnose, "pipeline_incident", before=lambda *a, **k: _notify("on_fallback"),
          error=lambda e: _notify("on_fallback_error", e))
    _wrap(autonomy, "investigate_candidate",
          before=lambda *a, **k: _notify("on_candidate_start", a[0] if a else k.get("c")),
          after=lambda finding, *a, **k: _notify("on_candidate_end", finding))
    _wrap(autonomy, "_act", after=lambda finding, *a, **k: _notify("on_finding", finding))


def last_turn(prompt: str) -> tuple[int, str | None, str]:
    """From an agent-turn prompt: (turns recorded so far, outcome of the last one, message).
    outcome: None (a tool ran), 'invalid' or 'rejected'."""
    text = str(prompt or "")
    if "STEPS SO FAR:" in text:
        text = text.split("STEPS SO FAR:", 1)[1].split("\n\nTURNS LEFT", 1)[0]
    turns = list(_TURN.finditer(text))
    if not turns:
        return 0, None, ""
    m = turns[-1]
    kind = {"INVALID REPLY": "invalid", "VERDICT REJECTED": "rejected"}.get(m.group(3) or "")
    return len(turns), kind, (m.group(4) or "").strip()


class _Step:
    __slots__ = ("step", "state", "tool_ran", "shown")

    def __init__(self, step: dict | None = None, state: str = "thinking"):
        self.step = step or {"tool": "", "thought": "", "args": {}, "result_summary": ""}
        self.state = state
        self.tool_ran = False
        self.shown = False


def _group(candidate=None, label: str | None = None) -> dict:
    return {"candidate": candidate, "label": label, "steps": [], "outcome": None}


class LiveTrace:
    """Context manager that renders the agent's steps live into one placeholder.

    mode "investigation": a reported wrong answer; "patrol"/"scan": rule candidates; "watch": quiet until a rule fires.
    After the backend call: ``finish*()`` renders the final state, then ``resume()`` re-raises a deferred rerun.
    """

    def __init__(self, parent, *, title: str, subtitle: str = "", mode: str = "investigation"):
        self.parent, self.title, self.subtitle, self.mode = parent, title, subtitle, mode
        self.groups: list[dict] = []
        self.ph = None
        self.done = False
        self.pending = None               # a deferred ScriptControlException (a click during the run)
        self._prev = None

    # ---- context
    def __enter__(self) -> "LiveTrace":
        self._prev = _listener()
        _local.listener = self
        if self.mode != "watch":
            self.groups.append(_group())
            self._placeholder()
            self._render()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        _local.listener = self._prev
        if exc_type is not None and not issubclass(exc_type, _Control) and self.ph is not None:
            cur = self._cur()
            if cur is not None and cur.state in ("thinking", "running", "verdict", "fallback"):
                cur.state = "error"
                cur.step["result_summary"] = f"{exc_type.__name__}: {exc}"
            self._safe_html(self._html(final=True))
        return False

    def resume(self) -> None:
        """Re-raise a rerun that a click requested while the backend call was running."""
        if self.pending is not None:
            e, self.pending = self.pending, None
            raise e

    # ---- rendering
    def _placeholder(self):
        if self.ph is None:
            self.ph = self.parent.empty()
        return self.ph

    def _cur(self) -> _Step | None:
        for g in reversed(self.groups):
            if g["steps"]:
                return g["steps"][-1]
        return None

    def _safe_html(self, body: str) -> None:
        try:
            self.ph.html(body)
        except _Control as e:
            if self.pending is None:
                self.pending = e

    def _row(self, s: _Step, k: int, last: bool, final: bool) -> str:
        html = C.trace_step(s.step, k, s.state, animate=(not final and not s.shown), last=last, stagger=False)
        s.shown = True
        return html

    def _html(self, final: bool = False) -> str:
        n_steps = sum(len(g["steps"]) for g in self.groups)
        stats = [C.plural(n_steps, "step")]
        if self.mode != "investigation":
            stats.append(C.plural(sum(1 for g in self.groups if g["candidate"]), "candidate"))
        live = not final
        head = C.trace_header(self.title, self.subtitle, live=live, stats=stats,
                              icon_name="radar" if self.mode != "investigation" else "bot")
        body, k = [], 0
        for gi, g in enumerate(self.groups):
            last_group = gi == len(self.groups) - 1
            if g["label"]:
                body.append(C.trace_divider(g["label"]))
            if g["candidate"]:
                body.append(C.patrol_candidate_header(g["candidate"]))
            steps = g["steps"]
            compact = live and not last_group and g["candidate"] is not None   # finished candidates fold up
            if steps and compact:
                body.append(C.trace_folded(len(steps)))
                k += len(steps)
            elif steps:
                hidden = max(0, len(steps) - LIVE_STEPS) if live else 0
                if hidden:
                    body.append(C.trace_folded(hidden, earlier=True))
                rows = [self._row(s, k + j, j == len(steps) - 1, final) for j, s in enumerate(steps) if j >= hidden]
                k += len(steps)
                body.append(f'<ol class="ms-steps">{"".join(rows)}</ol>')
            if g["outcome"]:
                body.append(C.patrol_outcome(g["outcome"]))
        if not body:
            if final:
                body.append(C.trace_note("No candidates — every rule check came back clean." if self.mode != "investigation"
                                         else "No agent steps were recorded."))
            elif self.mode in ("patrol", "scan"):
                body.append(C.trace_note("Running every learned rule as a cheap check across every customer record…",
                                         shimmer=True))
            else:
                body.append('<ol class="ms-steps">' + C.trace_step({}, 0, "thinking", animate=False, last=True) + "</ol>")
        return f'<section class="ms-trace{" live" if live else ""}">{head}{"".join(body)}</section>'

    def _render(self) -> None:
        if self.ph is not None and not self.done:
            self._safe_html(self._html())

    def final_html(self) -> str:
        return self._html(final=True)

    # ---- listener callbacks (called by the wrappers, in the script thread)
    def _settle(self, outcome: str | None, message: str) -> None:
        cur = self._cur()
        if cur is None or cur.state in ("done", "rejected", "invalid", "error", "accepted", "fallback"):
            return
        if outcome == "rejected":
            cur.state = "rejected"
            cur.step["tool"] = cur.step.get("tool") or "final"
            cur.step["result_summary"] = message or "the evidence gathered so far cannot back this verdict yet"
        elif outcome == "invalid":
            cur.state = "invalid"
            cur.step["result_summary"] = message or "invalid reply; the agent was sent a correction"
        elif cur.state == "verdict":
            cur.state = "accepted"
        elif cur.state == "running" and cur.tool_ran:
            cur.state = "done"

    def on_think(self, prompt: str = "") -> None:
        if not self.groups:
            self.groups.append(_group())
        turns, outcome, message = last_turn(prompt)
        g = self.groups[-1]
        if turns == 0 and g["steps"]:
            # a new agent loop in the same run (next hypothesis after a failed fix, or another candidate)
            self._settle(None, "")
            cur = self._cur()
            if cur is not None and cur.state == "verdict":
                cur.state = "accepted"
            if g["candidate"] is None:
                self.groups.append(_group(label="Next hypothesis · the fix did not verify, so the agent re-opened the case"))
        else:
            self._settle(outcome, message)
        self.groups[-1]["steps"].append(_Step())
        self._render()

    def on_reply(self, reply) -> None:
        cur = self._cur()
        if cur is None:
            return
        if isinstance(reply, dict) and "final" in reply:
            cur.step.update(tool="final", thought=str(reply.get("thought") or ""))
            cur.state = "verdict"
        elif isinstance(reply, dict) and isinstance(reply.get("action"), dict):
            action = reply["action"]
            cur.step.update(tool=str(action.get("tool") or "?"), thought=str(reply.get("thought") or ""),
                            args=action.get("args") if isinstance(action.get("args"), dict) else {})
            cur.state = "running"
        else:
            cur.state = "invalid"
            cur.step["result_summary"] = "the reply had neither an action nor a verdict"
        self._render()

    def on_reply_error(self, err) -> None:
        cur = self._cur()
        if cur is not None and not isinstance(err, _Control):
            cur.state = "invalid"
            msg = str(err or "")
            cur.step["result_summary"] = (msg[:240] if msg and "not valid JSON" not in msg
                                          else "the reply was not valid JSON; the agent was sent a correction")
            self._render()

    def on_tool_start(self, name, args) -> None:
        cur = self._cur()
        if cur is not None:
            cur.step.update(tool=name, args=args if isinstance(args, dict) else {})
            cur.state, cur.tool_ran = "running", True
            self._render()

    def on_tool_end(self, name, args, result) -> None:
        cur = self._cur()
        if cur is not None:
            cur.step["result_summary"] = str(result or "")[:600]
            cur.state = "done"
            self._render()

    def on_fallback(self) -> None:
        cur = self._cur()
        if cur is not None and cur.state in ("thinking", "running", "verdict"):
            cur.state = "invalid"
            cur.step["result_summary"] = cur.step.get("result_summary") or "invalid reply"
        if not self.groups:
            self.groups.append(_group())
        forced = not any(g["steps"] for g in self.groups)
        s = _Step({"tool": "fallback", "thought": "", "args": {}, "forced": forced,
                   "result_summary": "" if not forced else "the investigator agent is switched off (fixed pipeline forced)"},
                  "fallback")
        self.groups[-1]["steps"].append(s)
        self._render()

    def on_fallback_error(self, err) -> None:
        cur = self._cur()
        if cur is not None and cur.state == "fallback" and not isinstance(err, _Control):
            cur.state = "error"
            cur.step["result_summary"] = f"the fixed pipeline failed too: {str(err)[:200]}"
            self._render()

    def on_candidate_start(self, c) -> None:
        if self.mode == "watch" and self.ph is None:
            self._placeholder()
        cur = self._cur()
        if cur is not None and cur.state == "verdict":
            cur.state = "accepted"
        if self.groups and not self.groups[-1]["candidate"] and not self.groups[-1]["steps"]:
            self.groups[-1]["candidate"] = c or {}
        else:
            self.groups.append(_group(c or {}))
        self._render()

    def on_candidate_end(self, finding) -> None:
        if not self.groups or not isinstance(finding, dict):
            return
        g = self.groups[-1]
        inv = finding.get("investigation") or {}
        stored = inv.get("steps")
        if stored is not None:        # the finding's own trace is the authority
            g["steps"] = [_Step(dict(s), C.step_state(s.get("tool"))) for s in stored]
            for s in g["steps"]:
                s.shown = True
            if inv.get("fallback"):
                g["steps"].append(_Step({"tool": "fallback", "thought": "", "args": {},
                                         "result_summary": "the agent could not finish; the identity check decided"},
                                        "fallback"))
        if g["outcome"] is None:
            if not finding.get("same_customer"):
                g["outcome"] = {**finding, "status": "dismissed"}
            elif self.mode == "scan":
                g["outcome"] = {**finding, "status": "proposed"}
        self._render()

    def on_finding(self, finding) -> None:
        if self.groups and isinstance(finding, dict):
            self.groups[-1]["outcome"] = finding
        self._render()

    # ---- completion
    def finish(self, incident: dict | None) -> None:
        """Replace the live view with the authoritative trace stored on the incident, or a failure state."""
        if self.ph is None:
            return
        if incident is None:
            self.title = "Investigation failed"
            self._fail_open_steps("the investigation failed — see the error below")
            self._safe_html(self._html(final=True))
        else:
            inv = incident.get("investigation") or {}
            self._safe_html(C.trace_timeline(inv, animate=False, title="Investigation complete",
                                             subtitle=f"{incident.get('id')} · {incident.get('customer_name')}")
                            if inv else C.trace_pipeline_summary(incident))
        self.done = True

    def finish_patrol(self, report: dict | None, *, ok: bool | None = None, kind: str = "Patrol") -> None:
        if self.ph is None:
            return
        success = (report is not None) if ok is None else ok
        cur = self._cur()
        if cur is not None and cur.state == "verdict":
            cur.state = "accepted"
        if success:
            self.title = f"{kind} complete"
            if report is not None:
                self.subtitle = (f"{report.get('checks')} rule checks → {report.get('candidates')} candidates · "
                                 f"{report.get('duration_s')}s")
        else:
            self.title = f"{kind} failed"
            self._fail_open_steps("stopped — see the error below")
        self._safe_html(self._html(final=True))
        self.done = True

    def finish_watch(self) -> None:
        if self.ph is None:            # no rule fired: nothing was shown
            return
        for g in self.groups:
            if g["candidate"] and g["outcome"] is None:
                g["outcome"] = {"status": "dismissed", "confidence": None,
                                "reason": "Watch could not finish this check (see the activity feed)"}
        self.title = "Watch · a learned rule fired on this answer"
        self._fail_open_steps("Watch could not finish this step")
        self._safe_html(self._html(final=True))
        self.done = True

    def _fail_open_steps(self, message: str) -> None:
        for g in self.groups:
            for s in g["steps"]:
                if s.state in ("thinking", "running", "verdict", "fallback"):
                    s.state = "error"
                    s.step["result_summary"] = s.step.get("result_summary") or message
