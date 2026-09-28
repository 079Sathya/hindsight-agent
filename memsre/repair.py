"""apply_fix / undo_fix / reask: reversible memory repairs through Hindsight's curation API."""
from __future__ import annotations

from datetime import date

from . import agent, catalog, config, hs, store
from .diagnose import NO_FIX_TYPES
from .hs import Mem

MAIN = config.MAIN_BANK_ID


def _get(incident_id: str) -> dict:
    inc = store.get_incident(incident_id)
    if inc is None:
        raise ValueError(f"Unknown incident {incident_id}")
    return inc


def _invalidate(memory_id: str, reason: str) -> dict:
    hs.invalidate(MAIN, memory_id, reason=reason)
    return {"kind": "invalidate", "bank": MAIN, "memory_id": memory_id}


def _retain_doc(content: str, document_id: str, tags: list[str], context: str) -> dict:
    hs.retain_event(MAIN, content=content, date_iso=date.today().isoformat(), context=context,
                    document_id=document_id, tags=tags, metadata={"source": "memory_sre"})
    return {"kind": "retain_doc", "bank": MAIN, "document_id": document_id}


def link_identities(key_a, key_b, evidence, incident_id) -> list[dict]:
    """Link two customer keys locally and record the link in Hindsight. Returns the actions taken."""
    name_a, name_b = catalog.customer_name(key_a), catalog.customer_name(key_b)
    store.link(key_a, key_b)
    try:
        doc = _retain_doc(
            f"Identity link verified by Memory SRE ({incident_id}): '{name_a}' and '{name_b}' are the same "
            f"customer. Evidence: {str(evidence).rstrip('.')}.",
            f"sre-alias-{key_a}-{key_b}",
            [f"customer:{key_a}", f"customer:{key_b}", "sre:alias-link"],
            "Memory SRE identity link",
        )
    except Exception:
        store.unlink(key_a, key_b)
        raise
    return [{"kind": "alias", "a": key_a, "b": key_b}, doc]


def apply_fix(incident_id: str) -> dict:
    """Apply the automatic repair for the incident's failure type. Returns the updated incident."""
    inc = _get(incident_id)
    if inc["failure_type"] in NO_FIX_TYPES:
        raise ValueError("No automatic memory fix for this failure type")
    if inc["status"] == "fixed":
        return inc
    if inc["status"] not in ("open", "reverted"):
        raise ValueError(f"Incident {incident_id} is '{inc['status']}'; only open or reverted incidents can be fixed")

    key, name, iid = inc["customer_key"], inc["customer_name"], inc["id"]
    culprits = [Mem.from_dict(m) for m in inc["culprits"]]
    actions: list[dict] = []
    ftype = inc["failure_type"]

    try:
        if ftype == "RESOLUTION":
            foreign_key = inc["identity"]["foreign_tag"].split(":", 1)[1]
            actions += link_identities(key, foreign_key, inc["identity"]["linking_evidence"], iid)
            if inc["culprit_asserts_current_state"]:
                for m in culprits:
                    actions.append(_invalidate(m.id, f"Memory SRE {iid}: superseded by newer evidence under linked identity"))
        elif ftype == "FRESHNESS":
            for m in culprits:
                actions.append(_invalidate(m.id, f"Memory SRE {iid}: superseded by newer evidence"))
        elif ftype == "RECALL_MISS":
            actions.append(_retain_doc(f"{name}: {inc['supporting'][0]['text']}", f"sre-pin-{iid}",
                                       [f"customer:{key}", "sre:pin"], "Memory SRE pinned fact"))
        elif ftype == "MISSING_KNOWLEDGE":
            actions.append(_retain_doc(f"Verified correction for {name}: {inc['correction']}", f"sre-correction-{iid}",
                                       [f"customer:{key}", "sre:correction"], "Memory SRE verified correction"))
            if inc["culprit_asserts_current_state"]:
                for m in culprits:
                    actions.append(_invalidate(m.id, f"Memory SRE {iid}: superseded by newer evidence"))
    except Exception:
        inc["applied_actions"] = actions   # keep what did happen, so it can still be undone
        store.update_incident(inc)
        raise

    hs.wait_for_idle(MAIN, 30)
    inc["applied_actions"] = actions
    inc["status"] = "fixed"
    inc["reask"] = None   # any earlier re-ask predates this fix
    try:
        from . import lessons
        lessons.record(inc)
    except Exception as e:  # the lesson is a bonus; never fail the fix over it
        print(f"[repair] lesson not recorded: {e}", flush=True)
    store.update_incident(inc)
    return inc


def undo_fix(incident_id: str) -> dict:
    """Reverse applied_actions in reverse order. Returns the updated incident."""
    inc = _get(incident_id)
    if inc["status"] != "fixed":
        raise ValueError(f"Incident {incident_id} is '{inc['status']}'; only a fixed incident can be undone")
    for action in reversed(inc["applied_actions"]):
        if action["kind"] == "invalidate":
            hs.restore(action["bank"], action["memory_id"])
        elif action["kind"] == "alias":
            store.unlink(action["a"], action["b"])
        elif action["kind"] == "retain_doc":
            hs.delete_document(action["bank"], action["document_id"])
    inc["applied_actions"] = []
    inc["status"] = "reverted"
    inc["reask"] = None
    store.update_incident(inc)
    return inc


def reask(incident_id: str) -> dict:
    """Ask the incident's question again and store the new answer in incident["reask"]."""
    inc = _get(incident_id)
    if not inc.get("question"):
        raise ValueError(f"Incident {incident_id} has no question to re-ask")
    ans = agent.answer(inc["customer_key"], inc["question"], inc.get("answer_format"), run="reask")
    inc["reask"] = {
        "answer": ans.answer,
        "short_answer": ans.short_answer,
        "used_memory_ids": ans.used_memory_ids,
        "used_memories": [m.to_dict() for m in ans.used_memories],
    }
    store.update_incident(inc)
    return inc
