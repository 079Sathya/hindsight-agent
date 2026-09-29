"""The lessons bank: memory that drives behaviour.

- record(incident): post-mortem after a verified fix. It retains the lesson plus, for reactive incidents, a
  PLAYBOOK (procedural memory: symptom, tool path, root cause, fix, verified outcome) and a self-written
  DETECTION RULE (signal type + how to check + what confirms it), then refreshes the living playbook model.
- investigation_guidance(): playbooks, rules and rejected patterns the investigator starts from.
- learned_rules() / rule_candidates(): the proactive scan derives its checks ONLY from rules found in Hindsight;
  with an empty lessons bank it runs zero checks.
- reject_proposal(): reviewer feedback retained as a rule exception, consulted by the scan and the investigator.
- playbook() / playbook_history(): the "Memory SRE Playbook" Hindsight mental model.
All of it is off when config.MEMORY_ENABLED is False (the benchmark's memory-OFF arm).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import combinations

from . import catalog, config, hs, repair, store, tools
from .diagnose import SRE_SYSTEM, recommended_fix, root_cause_text
from .llm import llm_json, render

LESSONS = config.LESSONS_BANK_ID
MAIN = config.MAIN_BANK_ID
RULE_SIGNALS = list(tools.SIGNAL_PATTERNS)       # executable signal types ("keyword" is too broad to patrol)
PLAYBOOK_MODEL_ID = "memsre-playbook"
PLAYBOOK_MODEL_NAME = "Memory SRE Playbook"
PLAYBOOK_SOURCE_QUERY = (
    "How does Memory SRE detect, diagnose and fix AI agent memory failures? Summarise the proven investigation "
    "paths (tool sequences), the detection rules with how to check and confirm them, and the rejected patterns "
    "that must not be treated as evidence.")

POSTMORTEM_USER = """A memory incident was diagnosed, fixed and verified. Turn it into reusable knowledge for future incidents.

INCIDENT {id} ({failure_type}) for '{customer_name}'
Question: {question}
Wrong answer: {wrong_answer}
Correction: {correction}
Root cause: {root_cause}
Fix applied: {fix}
Verification: {verification}
Investigation path that worked: {path}
Linking evidence: {linking_evidence}

Return JSON:
{"symptom_signature": "<one general sentence describing the observable symptom, no customer names>",
 "rule": {"name": "<short name>", "signal_type": "<one of: {signals}, or none>",
          "how_to_check": "<general procedure that detects this failure BEFORE it causes a wrong answer, no customer names>",
          "confirmation": "<what evidence confirms it>"}}
Use signal_type "none" if no concrete, checkable signal generalises from this incident."""


def pair_key(a: str, b: str) -> str:
    return "+".join(sorted((a, b)))


def _retain(content: str, document_id: str, tags: list[str], context: str) -> None:
    hs.retain_event(LESSONS, content=content, date_iso=date.today().isoformat(), context=context,
                    document_id=document_id, tags=tags, metadata={"source": "memory_sre"})


def _docs(tag: str, limit: int = 100) -> list[dict]:
    """Lessons-bank documents carrying `tag`, from the (consistent) list endpoint: [{id, text, tags}], newest first."""
    docs: dict[str, dict] = {}
    for i in hs.list_memories(LESSONS, tags=[tag], limit=limit):
        if i.get("fact_type") not in ("world", "experience") or not i.get("document_id"):
            continue
        d = docs.setdefault(i["document_id"], {"id": i["document_id"], "texts": [], "tags": set(),
                                                "created": i.get("mentioned_at") or ""})
        if i.get("text") and i["text"] not in d["texts"]:
            d["texts"].append(i["text"])
        d["tags"] |= set(i.get("tags") or [])
    out = [{"id": d["id"], "text": " ".join(d["texts"]), "tags": sorted(d["tags"]), "created": d["created"]}
           for d in docs.values()]
    return sorted(out, key=lambda d: d["created"], reverse=True)


# --- post-mortem ------------------------------------------------------------------------------------

def _tool_path(incident: dict) -> str:
    steps = (incident.get("investigation") or {}).get("steps") or []
    path = [f"{s['tool']}({', '.join(f'{k}={v}' for k, v in s['args'].items())})" for s in steps
            if s["tool"] not in ("invalid", "final")]
    return " -> ".join(path) or "fixed pipeline (culprit -> whole-bank evidence -> identity check -> classify)"


def record(incident: dict) -> None:
    """Post-mortem into the lessons bank (after a verified fix or an accepted prevention)."""
    if not config.MEMORY_ENABLED:
        return
    iid, ftype = incident["id"], incident["failure_type"]
    _retain(f"Incident {iid} ({ftype}) for '{incident['customer_name']}': {incident['root_cause']} "
            f"Fix applied: {'; '.join(incident['recommended_fix'])}.",
            f"lesson-{iid}", ["sre:lesson", f"type:{ftype.lower()}"], "Memory SRE incident post-mortem")
    if incident.get("status") == "prevented":
        if incident.get("rule_id"):   # a confirmed prevention is another proof for the rule that found it
            _retain(f"Detection rule {incident['rule_id']} was confirmed again by {iid}: "
                    f"{incident.get('evidence_reason', '')}.", f"confirm-{iid}",
                    ["sre:rule-confirmation", f"rule:{incident.get('signal_type') or 'email_domain'}"],
                    "Memory SRE rule confirmation")
    else:
        _postmortem(incident)
    refresh_playbook_model()


def _postmortem(incident: dict) -> None:
    iid, ftype = incident["id"], incident["failure_type"]
    ver = incident.get("verification") or {}
    pm = llm_json(SRE_SYSTEM, render(
        POSTMORTEM_USER, id=iid, failure_type=ftype, customer_name=incident["customer_name"],
        question=incident.get("question") or "-", wrong_answer=incident.get("wrong_answer") or "-",
        correction=incident.get("correction") or "-", root_cause=incident["root_cause"],
        fix="; ".join(incident["recommended_fix"]), verification=ver.get("reason") or "verified",
        path=_tool_path(incident), linking_evidence=(incident.get("identity") or {}).get("linking_evidence") or "-",
        signals=", ".join(RULE_SIGNALS)), max_completion_tokens=900)
    signature = str(pm.get("symptom_signature") or incident.get("wrong_claim") or "")
    _retain(f"Playbook {iid} ({ftype}). Symptom: {signature} Proven tool path: {_tool_path(incident)}. "
            f"Root cause: {incident['root_cause']} Fix: {'; '.join(incident['recommended_fix'])}. "
            f"Verified outcome: {ver.get('reason') or 'verified'}.",
            f"playbook-{iid}", ["sre:playbook", f"type:{ftype.lower()}"], "Memory SRE playbook")
    rule = pm.get("rule") if isinstance(pm.get("rule"), dict) else {}
    signal = str(rule.get("signal_type") or "none").strip().lower()
    if signal in RULE_SIGNALS:
        _retain(f"Detection rule rule-{iid} ({rule.get('name') or ftype}), learned from {iid}. Signal type: {signal}. "
                f"How to check: {rule.get('how_to_check') or '-'} Confirmation: {rule.get('confirmation') or '-'}",
                f"rule-{iid}", ["sre:rule", f"rule:{signal}", f"type:{ftype.lower()}"], "Memory SRE detection rule")
    store.audit("postmortem", iid, symptom_signature=signature, rule_signal=signal, rule_name=rule.get("name"))


# --- what the investigator and the scan read back ------------------------------------------------------

def playbooks(symptom: str = "", limit: int = 2) -> list[dict]:
    """Playbooks most similar to the symptom (recall), falling back to the newest ones (list)."""
    if not config.MEMORY_ENABLED:
        return []
    found = []
    if symptom:
        try:
            for m in hs.recall(LESSONS, symptom, tags=["sre:playbook"], types=("world", "experience")):
                if m.document_id and m.document_id not in [p["id"] for p in found]:
                    found.append({"id": m.document_id, "text": m.text})
        except Exception:
            found = []
    docs = {d["id"]: d for d in _docs("sre:playbook")}
    if found:   # recall gives similarity order; the list gives the complete, consistent text
        return [docs.get(p["id"], p) for p in found][:limit]
    return list(docs.values())[:limit]


def learned_rules() -> list[dict]:
    """Detection rules the post-mortems wrote, from Hindsight: [{id, signal_type, text}]."""
    if not config.MEMORY_ENABLED:
        return []
    rules = []
    for d in _docs("sre:rule"):
        signal = next((t.split(":", 1)[1] for t in d["tags"] if t.startswith("rule:")), None)
        if signal in RULE_SIGNALS:
            rules.append({"id": d["id"], "signal_type": signal, "text": d["text"]})
    return rules


def exceptions() -> list[dict]:
    """Reviewer feedback retained as rule exceptions: [{id, signal_type, value, pair, text}]."""
    if not config.MEMORY_ENABLED:
        return []
    out = []
    for d in _docs("sre:exception"):
        def tag(prefix):
            return next((t.split(":", 1)[1] for t in d["tags"] if t.startswith(prefix)), None)
        out.append({"id": d["id"], "signal_type": tag("signal:"), "value": tag("value:"), "pair": tag("pair:"),
                    "text": d["text"]})
    return out


def investigation_guidance(symptom: str) -> dict:
    """What the investigator starts from: similar playbooks, learned rules and rejected patterns."""
    empty = {"text": "", "lessons_block": "", "playbook_ids": [], "rule_ids": [], "rejected_values": []}
    if not config.MEMORY_ENABLED:
        return empty
    pbs, rules, exc = playbooks(symptom), learned_rules(), exceptions()
    parts = []
    if pbs:
        parts.append("PROVEN PLAYBOOKS FROM PAST INCIDENTS (if one matches this case, follow its tool path first and "
                     "set used_playbook_id to its id):\n" + "\n".join(f"- [{p['id']}] {p['text']}" for p in pbs))
    if rules:
        parts.append("LEARNED DETECTION RULES:\n" + "\n".join(f"- [{r['id']}] {r['text']}" for r in rules))
    if exc:
        parts.append("REJECTED PATTERNS (a human reviewer said these are NOT linking evidence):\n"
                     + "\n".join(f"- {e['text']}" for e in exc))
    lessons_lines = [f"- {r['text']}" for r in rules] + [f"- REJECTED: {e['text']}" for e in exc]
    return {"text": "\n\n".join(parts),
            "lessons_block": ("LESSONS FROM PAST INCIDENTS:\n" + "\n".join(lessons_lines)) if lessons_lines else "",
            "playbook_ids": [p["id"] for p in pbs], "rule_ids": [r["id"] for r in rules],
            "rejected_values": [e["value"] for e in exc if e["value"]]}


def rule_candidates(rules: list[dict] | None = None) -> tuple[int, list[dict]]:
    """Run the learned rules as cheap deterministic checks over every customer record.

    Returns (checks_run, candidates). A candidate is two unlinked customer records that share a value of a rule's
    signal type, minus anything a reviewer rejected. No rules -> (0, [])."""
    rules = learned_rules() if rules is None else rules
    if not rules:
        return 0, []
    exc = exceptions()
    bad_values = {e["value"] for e in exc if e["value"]}
    bad_pairs = {e["pair"] for e in exc if e["pair"]}
    crm = {c["key"] for c in catalog.load_customers()}
    tags = hs.list_tags(MAIN, "customer:*")
    texts: dict[str, list[str]] = {}
    checks, candidates = 0, {}
    for rule in rules:
        owners: dict[str, set[str]] = {}
        for tag in tags:
            if tag not in texts:
                texts[tag] = [i.get("text") or "" for i in hs.list_memories(MAIN, tags=[tag], limit=100)
                              if i.get("fact_type") in ("world", "experience")]
            checks += 1
            for t in texts[tag]:
                for v in tools.extract_signals(t, rule["signal_type"]):
                    owners.setdefault(v, set()).add(tag)
        for value, owner_tags in owners.items():
            if value in bad_values:
                continue
            for x, y in combinations(sorted(owner_tags), 2):
                kx, ky = x.split(":", 1)[1], y.split(":", 1)[1]
                if ky in store.get_alias_keys(kx):
                    continue
                a, b = (ky, kx) if (ky in crm and kx not in crm) else (kx, ky)   # a = the name support knows
                if pair_key(a, b) in bad_pairs:
                    continue
                c = candidates.setdefault(pair_key(a, b), {"a": a, "b": b, "signal_type": rule["signal_type"],
                                                           "value": value, "rule_id": rule["id"], "values": []})
                if value not in c["values"]:
                    c["values"].append(value)
    return checks, list(candidates.values())


# --- living playbook (Hindsight mental model) ----------------------------------------------------------

def _as_dict(obj) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    return obj.to_dict() if hasattr(obj, "to_dict") else dict(vars(obj))


def ensure_playbook_model() -> None:
    try:
        hs.client().get_mental_model(LESSONS, PLAYBOOK_MODEL_ID, detail="metadata")
    except Exception:
        hs.client().create_mental_model(bank_id=LESSONS, name=PLAYBOOK_MODEL_NAME, source_query=PLAYBOOK_SOURCE_QUERY,
                                        trigger={"refresh_after_consolidation": True}, id=PLAYBOOK_MODEL_ID)


def refresh_playbook_model() -> None:
    """Create the mental model if needed and ask Hindsight to refresh it (runs server-side, asynchronously)."""
    if not config.MEMORY_ENABLED:
        return
    try:
        ensure_playbook_model()
        hs.client().refresh_mental_model(LESSONS, PLAYBOOK_MODEL_ID)
    except Exception as e:  # the living playbook is a bonus; never fail a post-mortem over it
        print(f"[lessons] playbook model refresh failed: {e}", flush=True)


def reset_playbook_model() -> None:
    try:
        hs.client().delete_mental_model(LESSONS, PLAYBOOK_MODEL_ID)
    except Exception:
        pass


def playbook() -> dict | None:
    """The living 'Memory SRE Playbook': {id, name, content, last_refreshed_at, is_stale}, or None."""
    if not config.MEMORY_ENABLED:
        return None
    try:
        d = _as_dict(hs.client().get_mental_model(LESSONS, PLAYBOOK_MODEL_ID, detail="content"))
    except Exception:
        return None
    return {k: d.get(k) for k in ("id", "name", "content", "last_refreshed_at", "is_stale")}


def playbook_history() -> list[dict]:
    """Earlier versions of the living playbook, as Hindsight returns them (newest first)."""
    if not config.MEMORY_ENABLED:
        return []
    try:
        h = hs.client().get_mental_model_history(LESSONS, PLAYBOOK_MODEL_ID)
    except Exception:
        return []
    h = _as_dict(h) if not isinstance(h, list) else h
    items = h if isinstance(h, list) else (h.get("history") or h.get("items") or h.get("versions") or [])
    return [_as_dict(x) for x in items]


# --- observations, lessons, scan, feedback --------------------------------------------------------------

def learned(limit=10) -> list[dict]:
    """Consolidated lessons (Hindsight observations) as [{"text", "proof_count"}]; raw lesson facts if
    consolidation hasn't run yet."""
    if not config.MEMORY_ENABLED:
        return []
    items = hs.list_memories(LESSONS, type="observation", limit=limit)
    if items:
        return [{"text": i.get("text") or "", "proof_count": i.get("proof_count") or 1} for i in items]
    mems = hs.recall(LESSONS, "What have we learned about memory failures?",
                     types=("world", "experience", "observation"))
    return [{"text": m.text, "proof_count": 1} for m in mems[:limit]]


def has_resolution_lesson() -> bool:
    """True once a detection rule (or a RESOLUTION lesson) exists, i.e. the scan has something to run."""
    if not config.MEMORY_ENABLED:
        return False
    if learned_rules():
        return True
    return "type:resolution" in hs.list_tags(LESSONS, q="type:resolution")


def proactive_identity_scan() -> list[dict]:
    """The UI's scan: a patrol that writes nothing (autonomy.patrol(apply=False)). Every candidate a learned rule
    finds is investigated by the agent; the confirmed ones come back as proposals for accept/accept_all/reject."""
    from . import autonomy   # lazy: autonomy imports this module
    return autonomy.proposals_from(autonomy.patrol(apply=False, trigger="scan"))


def reject_proposal(p: dict, reason: str) -> dict:
    """Reviewer feedback: the proposed pair is NOT one customer. Undo it if it was applied, and retain the rejection
    as a rule exception so neither the scan nor the investigator proposes this pattern again."""
    reason = (reason or "").strip() or "rejected by a reviewer"
    a, b = p["a"], p["b"]
    signal = p.get("signal_type") or "email_domain"
    value = str(p.get("value") or p.get("shared_domain") or "").split(",")[0].strip().lower()
    for inc in store.list_incidents():
        other = ((inc.get("identity") or {}).get("foreign_tag") or ":").split(":", 1)[1]
        if inc["status"] not in ("prevented", "auto-opened") or {inc["customer_key"], other} != {a, b}:
            continue
        if inc.get("applied_actions"):
            inc = repair.undo_fix(inc["id"])
        inc["status"] = "rejected"
        inc["rejection"] = {"reason": reason}
        store.update_incident(inc)
        store.audit("incident_rejected", inc["id"], reason=reason)
    doc_id = f"exception-{pair_key(a, b)}"
    if config.MEMORY_ENABLED:
        _retain(f"Rejected identity proposal: '{catalog.customer_name(a)}' and '{catalog.customer_name(b)}' are NOT the "
                f"same customer. The shared {signal} '{value}' is not linking evidence. Reviewer's reason: {reason}.",
                doc_id, ["sre:exception", f"signal:{signal}", f"value:{value}", f"pair:{pair_key(a, b)}"],
                "Memory SRE reviewer feedback")
        refresh_playbook_model()
    store.audit("proposal_rejected", None, pair=pair_key(a, b), signal_type=signal, value=value, reason=reason)
    return {"pair": pair_key(a, b), "signal_type": signal, "value": value, "reason": reason, "exception_id": doc_id}


def accept_all(proposals) -> list[dict]:
    """Accept every proposal whose pair is not linked yet. Returns the new 'prevented' incidents."""
    return [accept_proposal(p) for p in proposals if p["b"] not in store.get_alias_keys(p["a"])]


def learning_curve() -> list[dict]:
    """One point per incident, oldest first, from incidents.json (no LLM or Hindsight calls).

    wrong_answers is how many answers customers saw before the fix (the blast radius; 0 for prevented incidents).
    lesson_learned marks the first incident that was fixed reactively, which is when the first lesson was recorded."""
    points, learned_yet = [], False
    for inc in reversed(store.list_incidents()):
        if inc["status"] == "rejected":
            continue
        prevented = inc["status"] == "prevented"
        watched = prevented and inc.get("trigger") == "watch"   # caught right after the answer that fired the rule
        point = {"id": inc["id"], "customer_name": inc["customer_name"], "failure_type": inc["failure_type"],
                 "status": inc["status"],
                 "kind": "caught by watch" if watched else ("prevented" if prevented else "reactive"),
                 # a watch catch counts the answer that fired it, conservatively, as one wrong answer
                 "wrong_answers": 1 if watched else (0 if prevented else inc["blast_radius"]["answers_affected"]),
                 "lesson_learned": False}
        if not learned_yet and not prevented and inc["status"] in ("fixed", "reverted"):
            point["lesson_learned"] = learned_yet = True
        points.append(point)
    return points


def prevented_incident(p: dict, status: str = "prevented") -> dict:
    """An (unsaved) incident for an identity split found before any wrong answer (scan, patrol or watch)."""
    signal = p.get("signal_type") or "email_domain"
    identity = {"foreign_tag": f"customer:{p['b']}", "foreign_name": p["name_b"], "same_customer": True,
                "confidence": p["confidence"], "linking_evidence": p["linking_evidence"],
                "reason": p.get("reason") or f"Shared {signal} {p['shared_domain']}"}
    incident = {
        "id": store.next_incident_id(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
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
        "evidence_reason": f"Proactive identity scan ({p.get('rule_id') or 'rule'}): shared {signal} {p['shared_domain']}",
        "identity": identity,
        "failure_type": "RESOLUTION",
        "root_cause": root_cause_text("RESOLUTION", p["name_a"], identity),
        "blast_radius": {"answers_affected": 0, "answer_ids": []},
        "recommended_fix": recommended_fix("RESOLUTION", p["name_a"], [], [], identity, False),
        "applied_actions": [],
        "reask": None,
        "rule_id": p.get("rule_id"),
        "signal_type": signal,
        "shared_value": p["shared_domain"],
    }
    if p.get("investigation"):
        incident["investigation"] = p["investigation"]
    if p.get("trigger"):
        incident["trigger"] = p["trigger"]
    return incident


def accept_proposal(p) -> dict:
    """Link a proposed identity pair before any wrong answer; returns the 'prevented' incident."""
    if p["b"] in store.get_alias_keys(p["a"]):
        raise ValueError(f"'{p['name_a']}' and '{p['name_b']}' are already linked")
    incident = prevented_incident(p)
    incident["applied_actions"] = repair.link_identities(p["a"], p["b"], p["linking_evidence"], incident["id"])
    store.add_incident(incident)
    store.audit("prevented", incident["id"], pair=pair_key(p["a"], p["b"]), actions=incident["applied_actions"],
                rule_id=p.get("rule_id"), confidence=p["confidence"])
    repair.wait_until_recall_reflects(p["a"], None)
    try:
        hs.wait_for_idle(MAIN, 30)
        record(incident)
    except Exception as e:  # the link is committed; a lessons-bank hiccup must not report it as failed
        print(f"[lessons] post-link step failed: {e}", flush=True)
    return incident
