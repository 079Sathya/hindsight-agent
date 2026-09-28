"""SRE lessons bank + proactive identity scan (Tier 3)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import combinations

from . import catalog, config, hs, repair, store
from .diagnose import IDENTITY_MIN_CONFIDENCE, email_domains, identity_check, recommended_fix, root_cause_text

LESSONS = config.LESSONS_BANK_ID
MAIN = config.MAIN_BANK_ID


def record(incident: dict) -> None:
    """Retain the incident's post-mortem in the lessons bank."""
    iid, ftype = incident["id"], incident["failure_type"]
    hs.retain_event(
        LESSONS,
        content=f"Incident {iid} ({ftype}) for '{incident['customer_name']}': {incident['root_cause']} "
                f"Fix applied: {'; '.join(incident['recommended_fix'])}.",
        date_iso=date.today().isoformat(),
        context="Memory SRE incident post-mortem",
        document_id=f"lesson-{iid}",
        tags=["sre:lesson", f"type:{ftype.lower()}"],
        metadata={"source": "memory_sre"},
    )


def learned(limit=10) -> list[dict]:
    """Consolidated lessons as [{"text", "proof_count"}]; raw lesson facts if consolidation hasn't run yet."""
    items = hs.list_memories(LESSONS, type="observation", limit=limit)
    if items:
        return [{"text": i.get("text") or "", "proof_count": i.get("proof_count") or 1} for i in items]
    mems = hs.recall(LESSONS, "What have we learned about memory failures?",
                     types=("world", "experience", "observation"))
    return [{"text": m.text, "proof_count": 1} for m in mems[:limit]]


def has_resolution_lesson() -> bool:
    items = hs.list_memories(LESSONS, q="RESOLUTION")
    if any("resolution" in (i.get("text") or "").lower() for i in items):
        return True
    # Extraction usually paraphrases the post-mortem and drops the word; the tag it was retained with survives.
    return "type:resolution" in hs.list_tags(LESSONS, q="type:resolution")


def _lessons_block() -> str:
    texts = [lesson["text"] for lesson in learned() if lesson["text"]]
    return ("LESSONS FROM PAST INCIDENTS:\n" + "\n".join(f"- {t}" for t in texts)) if texts else ""


def proactive_identity_scan() -> list[dict]:
    """Find unlinked customer tags that share an email domain and that the LLM confirms are one customer."""
    keys = [t.split(":", 1)[1] for t in hs.list_tags(MAIN, q="customer:*")]
    domains = {k: email_domains([f"customer:{k}"]) for k in keys}
    crm = {c["key"] for c in catalog.load_customers()}

    lessons_block = None
    proposals = []
    for x, y in combinations(keys, 2):
        shared = domains[x] & domains[y]
        if not shared or y in store.get_alias_keys(x):
            continue
        a, b = (y, x) if (y in crm and x not in crm) else (x, y)   # a = the name the support team knows
        if lessons_block is None:
            lessons_block = _lessons_block()
        ident = identity_check(a, b, lessons_block)
        if ident["same_customer"] and ident["confidence"] >= IDENTITY_MIN_CONFIDENCE:
            proposals.append({
                "a": a, "b": b,
                "name_a": catalog.customer_name(a), "name_b": catalog.customer_name(b),
                "confidence": ident["confidence"],
                "linking_evidence": ident["linking_evidence"],
                "shared_domain": ", ".join(sorted(shared)),
                "reason": ident["reason"],
            })
    return proposals


def accept_proposal(p) -> dict:
    """Link a proposed identity pair before any wrong answer; returns the 'prevented' incident."""
    if p["b"] in store.get_alias_keys(p["a"]):
        raise ValueError(f"'{p['name_a']}' and '{p['name_b']}' are already linked")
    identity = {"foreign_tag": f"customer:{p['b']}", "foreign_name": p["name_b"], "same_customer": True,
                "confidence": p["confidence"], "linking_evidence": p["linking_evidence"],
                "reason": p.get("reason") or f"Shared email domain {p['shared_domain']}"}
    incident = {
        "id": store.next_incident_id(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "prevented",
        "customer_key": p["a"],
        "customer_name": p["name_a"],
        "question": None,
        "answer_format": None,
        "wrong_answer": None,
        "wrong_short_answer": None,
        "correction": None,
        "used_memories": [],
        "culprits": [],
        "wrong_claim": "",
        "culprit_asserts_current_state": False,
        "culprit_reason": "",
        "supporting": [],
        "evidence_reason": f"Proactive identity scan: shared email domain {p['shared_domain']}",
        "identity": identity,
        "failure_type": "RESOLUTION",
        "root_cause": root_cause_text("RESOLUTION", p["name_a"], identity),
        "blast_radius": {"answers_affected": 0, "answer_ids": []},
        "recommended_fix": recommended_fix("RESOLUTION", p["name_a"], [], [], identity, False),
        "applied_actions": [],
        "reask": None,
    }
    incident["applied_actions"] = repair.link_identities(p["a"], p["b"], p["linking_evidence"], incident["id"])
    store.add_incident(incident)
    repair.wait_until_recall_reflects(p["a"], None)
    try:
        hs.wait_for_idle(MAIN, 30)
        record(incident)
    except Exception as e:  # the link is committed; a lessons-bank hiccup must not report it as failed
        print(f"[lessons] post-link step failed: {e}", flush=True)
    return incident
