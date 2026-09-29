"""Local JSON state in data/state/: aliases, incidents, answer log, tag names. All writes are atomic."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from . import config

ALIASES_FILE = config.STATE_DIR / "aliases.json"
INCIDENTS_FILE = config.STATE_DIR / "incidents.json"
ANSWERS_FILE = config.STATE_DIR / "answers.jsonl"
TAG_NAMES_FILE = config.STATE_DIR / "tag_names.json"
AUDIT_FILE = config.STATE_DIR / "audit.jsonl"
POLICY_FILE = config.STATE_DIR / "policy.json"

# Autonomy policy. A fix is applied without a human only if its kind is set to "auto", its confidence is at
# least auto_apply_min_confidence, and it is reversible. Demo default: reactive incidents wait for approval,
# prevented ones (patrol / watch) are applied automatically.
DEFAULT_POLICY = {"auto_apply_min_confidence": 0.85, "reactive": "approval", "prevented": "auto",
                  "auto_patrol_after_fix": False}

_lock = threading.RLock()


def _retry_io(fn):
    # On Windows, replacing or reading a file that another handle has open briefly raises PermissionError.
    for attempt in range(20):
        try:
            return fn()
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)


def _write_text(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    _retry_io(lambda: os.replace(tmp, path))


def _read_text(path: Path) -> str:
    with _lock:
        return _retry_io(lambda: path.read_text(encoding="utf-8"))


def _read_json(path: Path, default):
    try:
        return json.loads(_read_text(path))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data) -> None:
    _write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


# --- aliases.json: {"kestrel": ["anvaya"], "anvaya": ["kestrel"]} ---------------------------

def get_alias_keys(key: str) -> list[str]:
    return list(_read_json(ALIASES_FILE, {}).get(key, []))


def link(a: str, b: str) -> None:
    if a == b:
        return
    with _lock:
        data = _read_json(ALIASES_FILE, {})
        for x, y in ((a, b), (b, a)):
            if y not in data.setdefault(x, []):
                data[x].append(y)
        _write_json(ALIASES_FILE, data)


def unlink(a: str, b: str) -> None:
    with _lock:
        data = _read_json(ALIASES_FILE, {})
        for x, y in ((a, b), (b, a)):
            if y in data.get(x, []):
                data[x].remove(y)
            if x in data and not data[x]:
                del data[x]
        _write_json(ALIASES_FILE, data)


def customer_tags(key: str) -> list[str]:
    return [f"customer:{key}"] + [f"customer:{k}" for k in get_alias_keys(key)]


def alias_pairs() -> list[tuple[str, str]]:
    """Every linked identity pair once, e.g. [("anvaya", "kestrel")]."""
    data = _read_json(ALIASES_FILE, {})
    return sorted({tuple(sorted((a, b))) for a, bs in data.items() for b in bs})


# --- incidents.json: list of incident dicts, oldest first on disk ---------------------------

def list_incidents() -> list[dict]:
    """All incidents, newest first."""
    return list(reversed(_read_json(INCIDENTS_FILE, [])))


def get_incident(incident_id: str) -> dict | None:
    return next((i for i in _read_json(INCIDENTS_FILE, []) if i.get("id") == incident_id), None)


def next_incident_id() -> str:
    nums = [int(i["id"].split("-")[1]) for i in _read_json(INCIDENTS_FILE, []) if i.get("id", "").startswith("INC-")]
    return f"INC-{max(nums, default=0) + 1:03d}"


def add_incident(inc: dict) -> None:
    with _lock:
        data = _read_json(INCIDENTS_FILE, [])
        data.append(inc)
        _write_json(INCIDENTS_FILE, data)


def update_incident(inc: dict) -> None:
    with _lock:
        data = _read_json(INCIDENTS_FILE, [])
        for n, existing in enumerate(data):
            if existing.get("id") == inc["id"]:
                data[n] = inc
                break
        else:
            raise ValueError(f"Unknown incident {inc['id']}")
        _write_json(INCIDENTS_FILE, data)


# --- answers.jsonl: one answer record per line -----------------------------------------------

def _read_answers() -> list[dict]:
    try:
        lines = _read_text(ANSWERS_FILE).splitlines()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def list_answers() -> list[dict]:
    """All logged answers, oldest first."""
    return _read_answers()


def log_answer(record: dict) -> str:
    """Append an answer record; returns its id ("ANS-0001", ...)."""
    with _lock:
        rows = _read_answers()
        nums = [int(r["answer_id"].split("-")[1]) for r in rows if r.get("answer_id", "").startswith("ANS-")]
        answer_id = f"ANS-{max(nums, default=0) + 1:04d}"
        rows.append({"answer_id": answer_id, **record})
        _write_text(ANSWERS_FILE, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        return answer_id


def answers_using(memory_ids, exclude_runs=("eval-after",)) -> list[dict]:
    """Logged answers that relied on any of memory_ids (excluding the given runs)."""
    wanted = set(memory_ids)
    return [r for r in _read_answers()
            if r.get("run") not in exclude_runs and wanted & set(r.get("used_memory_ids") or [])]


# --- tag_names.json: {"customer:anvaya": "Anvaya Technologies Pvt Ltd", ...} ----------------

def get_tag_names() -> dict[str, str]:
    return dict(_read_json(TAG_NAMES_FILE, {}))


def set_tag_names(names: dict[str, str]) -> None:
    with _lock:
        _write_json(TAG_NAMES_FILE, dict(names))


# --- audit.jsonl: every write, rollback, verification and policy decision -----------------------

def audit(event: str, incident_id: str | None = None, **details) -> None:
    """Append one audit record. Never raises: auditing must not break a repair."""
    from datetime import datetime, timezone
    try:
        rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event,
               "incident_id": incident_id, **details}
        with _lock:
            existing = _read_text(AUDIT_FILE) if AUDIT_FILE.exists() else ""
            _write_text(AUDIT_FILE, existing + json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        print(f"[audit] could not record {event}: {e}", flush=True)


def list_audit(incident_id: str | None = None) -> list[dict]:
    """Audit records, oldest first (optionally for one incident)."""
    try:
        rows = [json.loads(line) for line in _read_text(AUDIT_FILE).splitlines() if line.strip()]
    except FileNotFoundError:
        return []
    return [r for r in rows if incident_id is None or r.get("incident_id") == incident_id]


# --- policy.json -----------------------------------------------------------------------------

def get_policy() -> dict:
    return {**DEFAULT_POLICY, **_read_json(POLICY_FILE, {})}


def set_policy(**changes) -> dict:
    unknown = set(changes) - set(DEFAULT_POLICY)
    if unknown:
        raise ValueError(f"unknown policy setting(s): {', '.join(sorted(unknown))}")
    with _lock:
        policy = {**get_policy(), **changes}
        _write_json(POLICY_FILE, policy)
    audit("policy_changed", None, policy=policy)
    return policy


def load_eval_results() -> dict | None:
    """data/results/eval_latest.json written by scripts/eval.py, or None if it has not run yet."""
    return _read_json(config.RESULTS_DIR / "eval_latest.json", None)


def reset_state() -> None:
    """Empty the four state files (and the audit log). The autonomy policy is kept."""
    with _lock:
        _write_json(ALIASES_FILE, {})
        _write_json(INCIDENTS_FILE, [])
        _write_text(ANSWERS_FILE, "")
        _write_json(TAG_NAMES_FILE, {})
        _write_text(AUDIT_FILE, "")
