"""Incident creation + diagnosis + classify()."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone

from . import catalog, config, hs, store
from .agent import AgentAnswer, memory_line
from .hs import Mem
from .llm import llm_json, render

SRE_SYSTEM = """You are Memory SRE, a reliability engineer for AI agent memory. You diagnose why an AI agent gave a wrong answer. Be precise and conservative. Return ONLY a JSON object."""

CULPRIT_USER = """The support agent answered a question wrongly.

QUESTION: {question}
AGENT'S ANSWER: {wrong_answer}
CORRECTION FROM THE SUPPORT REP: {correction}

MEMORIES THE AGENT USED:
{used_memory_lines}

Which of these memories support the WRONG answer? A memory supports the wrong answer if the agent's wrong claim follows from it.
Return JSON: {"culprit_ids": ["<id>", "..."], "wrong_claim": "<the wrong claim in one sentence>", "culprit_asserts_current_state": <true if a culprit states a current state that can change over time, such as a plan, region or status>, "reason": "<one sentence>"}
If no memory supports the wrong answer, return an empty culprit_ids list."""

# Prepended to CULPRIT_USER: the agent derived its wrong claim from memory *plus* the catalog ("signed Enterprise"
# -> "can export audit logs"). Without the catalog the model often finds no culprit (0 of 3 on the demo incident),
# so nothing is invalidated and the fix does not change the answer; with it, 3 of 3.
CULPRIT_CATALOG_PREFIX = """PRODUCT CATALOG (what each plan includes):
{catalog_text}

"""

EVIDENCE_USER = """CORRECTION FROM THE SUPPORT REP about the customer '{customer_name}': {correction}

CANDIDATE MEMORIES FROM THE WHOLE MEMORY BANK (they may name customers differently):
{candidate_lines}

Which candidate memories are evidence FOR the correction about this customer — even if they refer to the customer by a different name (for example a legal entity name, a billing account name or an email domain)? Do not select memories about clearly different companies unless something links them to this customer.
Return JSON: {"supporting_ids": ["<id>", "..."], "reason": "<one sentence>"}"""

IDENTITY_USER = """Decide whether two customer records in our memory refer to the SAME real-world customer.

RECORD A — known to the support team as '{name_a}':
{facts_a}

RECORD B — appears in our records as '{name_b}':
{facts_b}

{lessons_block}
Look for concrete linking evidence: shared email domains, shared people, account numbers, or explicit statements. A company email domain that appears in both records (not a free-mail provider such as gmail.com) is sufficient linking evidence on its own. Do not decide from similar-sounding names alone.
Return JSON: {"same_customer": true or false, "confidence": <0.0-1.0>, "linking_evidence": "<exact quote(s) from the records>", "reason": "<one sentence>"}"""

IDENTITY_QUERY = "contact email admin billing plan"
IDENTITY_MIN_CONFIDENCE = 0.7
CONTACT_QUERY = "contact email admin billing"
EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
FREE_MAIL_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com"}

FAILURE_TYPES = ["RESOLUTION", "FRESHNESS", "RECALL_MISS", "EXECUTION", "MISSING_KNOWLEDGE", "UNKNOWN"]
NO_FIX_TYPES = ("EXECUTION", "UNKNOWN")

ROOT_CAUSE_TEMPLATES = {
    "RESOLUTION": "The correct fact was stored under a different name for the same customer ('{foreign_name}'). The two records were never linked, so the agent's recall for '{customer_name}' could not see it. Linking evidence: {linking_evidence}.",
    "FRESHNESS": "A newer fact superseded the memory the agent used, but the outdated memory was recalled and the newer one was not.",
    "RECALL_MISS": "The correct fact exists under this customer but was not retrieved for this question.",
    "EXECUTION": "The correct memory was retrieved, but the agent still answered wrong. This is a model or prompt problem — memory is not at fault.",
    "MISSING_KNOWLEDGE": "Memory never contained the correct fact.",
    "UNKNOWN": "No memory-level cause could be confirmed.",
}


def classify(culprits: list[Mem], supporting: list[Mem], used_ids: list[str],
             customer_tags: list[str], identity_confirmed: bool | None) -> str:
    cust = set(customer_tags)
    def ctags(m): return {t for t in m.tags if t.startswith("customer:")}
    if not supporting:
        return "MISSING_KNOWLEDGE" if culprits else "UNKNOWN"
    foreign = [m for m in supporting if not (ctags(m) & cust)]
    local   = [m for m in supporting if (ctags(m) & cust)]
    if foreign and identity_confirmed:
        return "RESOLUTION"
    if not local:
        return "UNKNOWN"
    if any(m.id in used_ids for m in local):
        return "EXECUTION"
    newest_culprit = max((m.date for m in culprits if m.date), default="")
    if culprits and any(m.date and m.date > newest_culprit for m in local):
        return "FRESHNESS"
    return "RECALL_MISS"


def root_cause_text(failure_type: str, customer_name: str, identity: dict | None) -> str:
    identity = identity or {}
    return render(ROOT_CAUSE_TEMPLATES[failure_type], customer_name=customer_name,
                  foreign_name=identity.get("foreign_name", ""),
                  linking_evidence=str(identity.get("linking_evidence", "")).rstrip("."))


def recommended_fix(failure_type: str, customer_name: str, culprits: list[Mem], supporting: list[Mem],
                    identity: dict | None, asserts_current_state: bool) -> list[str]:
    """Human-readable actions matching what repair.apply_fix will do."""
    invalidations = [f"Invalidate the superseded memory in Hindsight (reversible): \"{m.text}\"" for m in culprits]
    if failure_type == "RESOLUTION":
        fix = [f"Link '{customer_name}' with '{identity['foreign_name']}' as the same customer",
               "Retain an identity-link memory tagged with both customer names"]
        return fix + (invalidations if asserts_current_state else [])
    if failure_type == "FRESHNESS":
        return invalidations
    if failure_type == "RECALL_MISS":
        return [f"Pin a restatement of the correct fact for '{customer_name}': \"{supporting[0].text}\""]
    if failure_type == "MISSING_KNOWLEDGE":
        fix = [f"Retain the verified correction for '{customer_name}'"]
        return fix + (invalidations if asserts_current_state else [])
    return []


def _foreign_customer_tags(supporting: list[Mem], cust_tags: list[str]) -> list[str]:
    """customer:* tags on supporting memories that belong to none of this customer's tags."""
    cust = set(cust_tags)
    out: list[str] = []
    for m in supporting:
        ctags = [t for t in m.tags if t.startswith("customer:")]
        if not set(ctags) & cust:
            out += [t for t in ctags if t not in out]
    return out


def email_domains(tags: list[str]) -> set[str]:
    """Email domains in the contact memories carrying any of tags (free-mail domains ignored)."""
    mems = hs.recall(config.MAIN_BANK_ID, CONTACT_QUERY, tags=tags, max_tokens=800)
    return {d.lower() for m in mems for d in EMAIL_RE.findall(m.text)} - FREE_MAIL_DOMAINS


def _shared_domain_links(cands: list[Mem], cust_tags: list[str]) -> dict[str, list[str]]:
    """Foreign customer tags among the candidates whose contacts share an email domain with this customer's."""
    own = email_domains(cust_tags)
    if not own:
        return {}
    foreign = dict.fromkeys(t for m in cands for t in m.tags if t.startswith("customer:") and t not in cust_tags)
    return {t: sorted(shared) for t in foreign if (shared := own & email_domains([t]))}


def _candidate_line(m: Mem, customer_name: str, links: dict[str, list[str]]) -> str:
    # The model does not join "our contact uses @x.com" and "X Ltd changed plan" across two lines on its
    # own, so a foreign record sharing an email domain with this customer's contacts says so on its line.
    ctags = [t for t in m.tags if t.startswith("customer:")]
    hint = "".join(f" [linked to {customer_name}: shares email domain {', '.join(links[t])} with "
                   f"{customer_name}'s contacts]" for t in ctags if t in links)
    return f"[{m.id}] ({m.date}) [tags: {', '.join(ctags)}]{hint} {m.text}"


def _fact_lines(mems: list[Mem]) -> str:
    return "\n".join(f"- ({m.date}) [{m.source}] {m.text}" for m in mems) or "(no memories found)"


def identity_check(key_a: str, key_b: str, lessons_block: str = "") -> dict:
    """Ask the LLM whether customer key_a and customer key_b are the same real-world customer."""
    facts_a = hs.recall(config.MAIN_BANK_ID, IDENTITY_QUERY, tags=store.customer_tags(key_a), max_tokens=1000)[:8]
    facts_b = hs.recall(config.MAIN_BANK_ID, IDENTITY_QUERY, tags=[f"customer:{key_b}"], max_tokens=1000)[:8]
    name_a, name_b = catalog.customer_name(key_a), catalog.customer_name(key_b)
    res = llm_json(SRE_SYSTEM, render(IDENTITY_USER, name_a=name_a, facts_a=_fact_lines(facts_a),
                                      name_b=name_b, facts_b=_fact_lines(facts_b), lessons_block=lessons_block))
    try:
        confidence = float(res.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "foreign_tag": f"customer:{key_b}",
        "foreign_name": name_b,
        "same_customer": _truthy(res.get("same_customer")),
        "confidence": confidence,
        "linking_evidence": str(res.get("linking_evidence") or ""),
        "reason": str(res.get("reason") or ""),
    }


def _truthy(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _ids(value) -> list[str]:
    if not isinstance(value, list):
        value = [value] if value else []
    return [str(v).strip().strip("[]") for v in value]


def build_incident(ans: AgentAnswer, correction: str, answer_format: str | None, *, culprits: list[Mem],
                   wrong_claim: str, asserts_current: bool, culprit_reason: str, supporting: list[Mem],
                   evidence_reason: str, identity: dict | None) -> dict:
    """The incident dict (BUILD_PLAN §9.3 schema) from gathered evidence. failure_type always comes from classify()."""
    key = ans.customer_key
    name = catalog.customer_name(key)
    cust_tags = store.customer_tags(key)
    identity_confirmed = (identity["same_customer"] and identity["confidence"] >= IDENTITY_MIN_CONFIDENCE
                          if identity else None)
    failure_type = classify(culprits, supporting, ans.used_memory_ids, cust_tags, identity_confirmed)
    culprit_ids = [m.id for m in culprits]
    affected = store.answers_using(culprit_ids) if culprit_ids else []
    asserts_current = bool(asserts_current and culprits)
    return {
        "id": store.next_incident_id(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "no_fix" if failure_type in NO_FIX_TYPES else "open",
        "customer_key": key,
        "customer_name": name,
        "question": ans.question,
        "answer_format": answer_format,
        "wrong_answer": ans.answer,
        "wrong_short_answer": ans.short_answer,
        "correction": correction,
        "used_memories": [m.to_dict() for m in ans.used_memories],
        "culprits": [m.to_dict() for m in culprits],
        "wrong_claim": wrong_claim,
        "culprit_asserts_current_state": asserts_current,
        "culprit_reason": culprit_reason,
        "supporting": [m.to_dict() for m in supporting],
        "evidence_reason": evidence_reason,
        "identity": identity,
        "failure_type": failure_type,
        "root_cause": root_cause_text(failure_type, name, identity),
        "blast_radius": {"answers_affected": len(affected), "answer_ids": [r["answer_id"] for r in affected]},
        "recommended_fix": recommended_fix(failure_type, name, culprits, supporting, identity, asserts_current),
        "applied_actions": [],
        "reask": None,
    }


# Set True (or MEMSRE_FORCE_PIPELINE=1) to diagnose with the original fixed pipeline instead of the investigator.
FORCE_PIPELINE = config.FORCE_PIPELINE


def create_incident(ans: AgentAnswer, correction: str, answer_format: str | None = None) -> dict:
    """Diagnose a wrong answer and save the incident. Routed through the investigator agent
    (memsre/investigator.py), which falls back to the fixed pipeline if it cannot finish."""
    if FORCE_PIPELINE:
        return pipeline_incident(ans, correction, answer_format)
    from .investigator import investigate   # lazy: the investigator imports this module
    return investigate(ans, correction, answer_format)


def pipeline_incident(ans: AgentAnswer, correction: str, answer_format: str | None = None, save: bool = True) -> dict:
    """The original fixed pipeline: culprit -> evidence -> identity -> classify -> blast radius."""
    key = ans.customer_key
    name = catalog.customer_name(key)
    cust_tags = store.customer_tags(key)

    # 1. Culprit: which used memories support the wrong answer.
    if ans.used_memories:
        c = llm_json(SRE_SYSTEM, render(
            CULPRIT_CATALOG_PREFIX + CULPRIT_USER, catalog_text=catalog.catalog_text(), question=ans.question,
            wrong_answer=ans.answer, correction=correction,
            used_memory_lines="\n".join(memory_line(m) for m in ans.used_memories)))
    else:
        c = {"culprit_ids": [], "wrong_claim": ans.answer, "culprit_asserts_current_state": False,
             "reason": "The agent used no memories."}
    culprit_ids = [i for i in _ids(c.get("culprit_ids")) if i in ans.used_memory_ids]
    culprits = [m for m in ans.used_memories if m.id in culprit_ids]
    asserts_current = _truthy(c.get("culprit_asserts_current_state")) and bool(culprits)

    # 2. Evidence: whole-bank recall (no tag filter) for the correction.
    cands = [m for m in hs.recall(config.MAIN_BANK_ID, query=correction, tags=None, max_tokens=2048)
             if m.id not in culprit_ids][:15]
    if cands:
        links = _shared_domain_links(cands, cust_tags)
        e = llm_json(SRE_SYSTEM, render(EVIDENCE_USER, customer_name=name, correction=correction,
                                        candidate_lines="\n".join(_candidate_line(m, name, links) for m in cands)))
    else:
        e = {"supporting_ids": [], "reason": "The whole-bank recall returned no candidates."}
    selected = set(_ids(e.get("supporting_ids")))
    supporting = [m for m in cands if m.id in selected]

    # 3. Identity check, only if some supporting memory is filed under another customer.
    identity = None
    foreign_tags = _foreign_customer_tags(supporting, cust_tags)
    if foreign_tags:
        identity = identity_check(key, foreign_tags[0].split(":", 1)[1])

    # 4-5. Classify + blast radius happen in build_incident.
    incident = build_incident(
        ans, correction, answer_format, culprits=culprits, wrong_claim=str(c.get("wrong_claim") or ""),
        asserts_current=asserts_current, culprit_reason=str(c.get("reason") or ""), supporting=supporting,
        evidence_reason=str(e.get("reason") or ""), identity=identity)
    if save:
        store.add_incident(incident)
    return incident


def _main() -> None:
    from . import agent

    config.check()
    q01 = next(q for q in catalog.load_questions() if q["id"] == "Q01")
    ans = agent.answer("kestrel", "Can Kestrel Logistics export audit logs?")
    print(f"Agent said: {ans.short_answer!r} -- {ans.answer}\n")
    print(json.dumps(create_incident(ans, q01["correction"]), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    _main()
