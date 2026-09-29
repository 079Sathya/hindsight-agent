"""Cached reads and view models for the UI. No rendering here.

Hindsight reads (lessons bank) are cached briefly with st.cache_data so reruns stay fast; ``invalidate()`` clears them
and must be called after every action that writes. Everything else is derived from the local state files."""
from __future__ import annotations

import json

import streamlit as st

from memsre import catalog, config, lessons

VERSIONS_FILE = "ui_playbook_versions.json"   # UI-observed versions of the living playbook (in the gitignored state dir)


@st.cache_data(ttl=120, show_spinner=False)
def learned_rules() -> list[dict]:
    return lessons.learned_rules()


@st.cache_data(ttl=120, show_spinner=False)
def exceptions() -> list[dict]:
    return lessons.exceptions()


@st.cache_data(ttl=120, show_spinner=False)
def learned() -> list[dict]:
    return lessons.learned()


@st.cache_data(ttl=120, show_spinner=False)
def has_lesson() -> bool:
    return lessons.has_resolution_lesson()


@st.cache_data(ttl=10, show_spinner=False)
def playbook() -> dict | None:
    return lessons.playbook()


@st.cache_data(ttl=10, show_spinner=False)
def playbook_history() -> list[dict]:
    return lessons.playbook_history()


def invalidate() -> None:
    """Drop every cached read. Call after each action that writes (answer, diagnose, fix, patrol, reject, policy)."""
    st.cache_data.clear()


def bank_status() -> tuple[bool, str | None]:
    """(reachable, error) for the hero pill, from the cached rules read (a real Hindsight call)."""
    try:
        learned_rules()
        return True, None
    except Exception as e:  # noqa: BLE001 - the pill *is* the error display
        return False, f"{type(e).__name__}: {e}"[:240]


def counts(incidents: list[dict]) -> dict:
    by = {}
    for i in incidents or []:
        by[i.get("status")] = by.get(i.get("status"), 0) + 1
    return {"open": by.get("open", 0) + by.get("auto-opened", 0), "pending": by.get("auto-opened", 0),
            "fixed": by.get("fixed", 0), "prevented": by.get("prevented", 0), "reverted": by.get("reverted", 0),
            "rejected": by.get("rejected", 0), "total": len(incidents or [])}


def status(incidents: list[dict], policy: dict | None, rules: list[dict] | None, error: str | None = None) -> dict:
    """Hero status. ``rules``/``error`` come from the one rules read the app makes per run (rules None = unavailable)."""
    ok = error is None
    return {"bank_ok": ok, "bank_id": config.MAIN_BANK_ID, "bank_error": error,
            "auto_mode": (policy or {}).get("prevented") == "auto", "open_incidents": counts(incidents)["open"],
            "rules": None if rules is None else len(rules)}


def benchmark() -> dict | None:
    path = config.RESULTS_DIR / "learning_benchmark.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def rule_confirmations(incidents: list[dict]) -> dict[str, int]:
    """rule id -> how many applied (prevented/fixed) incidents that rule found."""
    out: dict[str, int] = {}
    for i in incidents or []:
        if i.get("rule_id") and i.get("status") in ("prevented", "fixed"):
            out[i["rule_id"]] = out.get(i["rule_id"], 0) + 1
    return out


def _pair_names(pair: str | None) -> str:
    keys = [k for k in str(pair or "").split("+") if k]
    names = []
    for k in keys:
        try:
            names.append(catalog.customer_name(k))
        except Exception:  # noqa: BLE001
            names.append(k)
    return " ≡ ".join(names)


def _pct(x) -> str:
    try:
        return f"{round(float(x) * 100)}%"
    except (TypeError, ValueError):
        return "—"


def _item(a: dict) -> dict:
    ev, d = a.get("event") or "", a
    t = {"ts": a.get("ts"), "kind": ev, "incident_id": a.get("incident_id"), "icon": "activity", "tone": "neutral",
         "title": ev.replace("_", " ").capitalize(), "detail": ""}
    if ev == "investigated":
        t.update(icon="bot", tone="accent", title="Investigated by the agent",
                 detail=f"{d.get('failure_type')} · {d.get('steps')} steps · {d.get('llm_calls')} LLM calls"
                        + (" · fell back to the fixed pipeline" if d.get("fallback") else ""))
    elif ev == "policy_decision":
        auto = d.get("decision") == "auto"
        t.update(icon="zap" if auto else "shield", tone="success" if auto else "warning",
                 title="Policy: auto-apply" if auto else "Policy: waiting for approval",
                 detail=f"{d.get('kind')} · confidence {_pct(d.get('confidence'))} · {d.get('reason') or ''}")
    elif ev == "fix_applied":
        t.update(icon="wrench", tone="accent", title=f"Fix applied (attempt {d.get('attempt', 1)})",
                 detail=f"{d.get('failure_type') or ''} · {len(d.get('actions') or [])} reversible actions in Hindsight")
    elif ev == "verification":
        if d.get("skipped") or (d.get("passed") and not d.get("checks")):
            t.update(icon="check-circle", tone="success", title="Linked before any wrong answer",
                     detail=d.get("reason") or "no question to re-ask")
        elif d.get("passed"):
            t.update(icon="shield-check", tone="success", title="Verified by re-asking", detail=d.get("reason") or "")
        else:
            t.update(icon="alert", tone="warning", title="Verification failed", detail=d.get("reason") or "")
    elif ev == "rolled_back":
        t.update(icon="undo", tone="warning", title=f"Rolled back attempt {d.get('attempt', '')}".strip(),
                 detail="the re-asked answers were still wrong, so the fix was reversed")
    elif ev == "new_hypothesis":
        t.update(icon="branch", tone="warning", title="Next hypothesis", detail=str(d.get("failure_type") or ""))
    elif ev == "undo":
        t.update(icon="undo", tone="neutral", title="Fix undone", detail="every applied action was reversed")
    elif ev == "postmortem":
        t.update(icon="sparkles", tone="accent", title="Post-mortem: playbook and detection rule written",
                 detail=f"signal {d.get('rule_signal') or '—'} · {d.get('rule_name') or ''}")
    elif ev == "auto_opened":
        watch = d.get("trigger") == "watch"
        t.update(icon="eye" if watch else "radar", tone="warning",
                 title=f"{'Watch' if watch else 'Patrol'} found {_pair_names(d.get('pair'))}",
                 detail=f"rule {d.get('rule_id')} · confidence {_pct(d.get('confidence'))}")
    elif ev == "patrol":
        o = d.get("outcome") or {}
        t.update(icon="radar", tone="accent", title=f"Patrol run ({d.get('trigger') or 'patrol'})",
                 detail=f"{d.get('checks')} rule checks · {d.get('candidates')} candidates · {o.get('prevented', 0)} prevented · "
                        f"{o.get('pending', 0)} awaiting approval · {o.get('dismissed', 0)} dismissed")
    elif ev == "policy_changed":
        p = d.get("policy") or {}
        t.update(icon="sliders", tone="neutral", title="Autonomy policy changed",
                 detail=f"prevented: {p.get('prevented')} · reactive: {p.get('reactive')} · "
                        f"patrol after fix: {'on' if p.get('auto_patrol_after_fix') else 'off'}")
    elif ev == "proposal_rejected":
        t.update(icon="ban", tone="danger", title=f"Pattern rejected: {d.get('value') or ''}".strip(),
                 detail=f"{_pair_names(d.get('pair'))} · {d.get('reason') or ''}")
    elif ev == "incident_rejected":
        t.update(icon="ban", tone="danger", title="Link rejected by a reviewer", detail=d.get("reason") or "")
    elif ev == "finding_dismissed":
        t.update(icon="x-circle", tone="neutral", title=f"Patrol dismissed {_pair_names(d.get('pair'))}",
                 detail=f"confidence {_pct(d.get('confidence'))} · {d.get('reason') or ''}")
    return t


def activity(audit: list[dict], limit: int = 40) -> list[dict]:
    """The audit log as feed items, newest first."""
    return [_item(a) for a in reversed(audit or [])][:limit]


def _versions_path():
    return config.STATE_DIR / VERSIONS_FILE


def _read_snaps() -> list[dict]:
    try:
        data = json.loads(_versions_path().read_text(encoding="utf-8"))
        return [s for s in data if isinstance(s, dict) and s.get("content")]
    except (OSError, ValueError):
        return []


def _write_snaps(snaps: list[dict]) -> None:
    try:
        path = _versions_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snaps, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def playbook_versions(pb: dict | None, history: list[dict] | None, fresh: bool = False) -> list[dict]:
    """Versions of the living playbook, oldest first: [{"label": "v1", "at", "content"}]; the last one is current.

    Hindsight's history entries ({"previous_content", "changed_at"}, newest first) are used when there are any.
    Hindsight Cloud currently records none for refreshes, so the UI also snapshots every new version it observes.
    pb None means "no playbook right now": lessons.playbook() also returns None on a transient error, so the
    snapshots are only cleared when the state is fresh (no incidents: a reseed or reset). Otherwise the stored
    versions are returned unchanged."""
    if pb is None:
        if fresh:
            if _read_snaps():
                _write_snaps([])
            return []
        return [{"label": f"v{k + 1}", **v} for k, v in enumerate(_read_snaps())]
    content = pb.get("content") or ""
    if not content:
        return []
    cur = {"at": pb.get("last_refreshed_at") or "", "content": content}
    snaps = _read_snaps()
    if not snaps or snaps[-1]["content"] != content:
        snaps = [s for s in snaps if s["content"] != content] + [cur]
        _write_snaps(snaps)
    hist = [{"at": h.get("changed_at") or "", "content": h.get("previous_content")}
            for h in reversed(history or []) if isinstance(h, dict) and h.get("previous_content")]
    versions = (hist + [cur]) if hist else snaps
    return [{"label": f"v{k + 1}", **v} for k, v in enumerate(versions)]
