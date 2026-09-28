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


def load_eval_results() -> dict | None:
    """data/results/eval_latest.json written by scripts/eval.py, or None if it has not run yet."""
    return _read_json(config.RESULTS_DIR / "eval_latest.json", None)


def reset_state() -> None:
    """Empty all four state files."""
    with _lock:
        _write_json(ALIASES_FILE, {})
        _write_json(INCIDENTS_FILE, [])
        _write_text(ANSWERS_FILE, "")
        _write_json(TAG_NAMES_FILE, {})
