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


def _reverse(actions: list[dict]) -> list[dict]:
    """Undo actions in reverse order. Returns (in original order) any that could not be undone."""
    failed = []
    for action in reversed(actions):
        try:
            if action["kind"] == "invalidate":
                hs.restore(action["bank"], action["memory_id"])
            elif action["kind"] == "alias":
                store.unlink(action["a"], action["b"])
            elif action["kind"] == "retain_doc":
                hs.delete_document(action["bank"], action["document_id"])
        except Exception as e:
            print(f"[repair] could not undo {action}: {e}", flush=True)
            failed.insert(0, action)
    return failed


def wait_until_recall_reflects(customer_key: str, question: str | None, expect_ids=()) -> None:
    """Best-effort: after a repair, wait (up to 90 s) until this customer's recall no longer returns stale data,
    so an immediate re-ask sees the change. Some Hindsight servers lag behind writes for a minute or two."""
    query = f"{catalog.customer_name(customer_key)}: {question or 'plan'}"
    try:
        if not hs.wait_for_consistent_recall(MAIN, 90, probes=3, query=query,
                                             tags=store.customer_tags(customer_key), expect_ids=expect_ids):
            print("[repair] recall still stale after 90 s; continuing", flush=True)
    except Exception as e:
        print(f"[repair] recall check failed, continuing: {e}", flush=True)


def link_identities(key_a, key_b, evidence, incident_id) -> list[dict]:
    """Link two customer keys locally and record the link in Hindsight. Returns the actions taken
    ([] if the pair is already linked, so undoing this incident cannot break the existing link)."""
    if key_b in store.get_alias_keys(key_a):
        return []
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


MAX_ATTEMPTS = 2           # hypotheses tried before handing the incident to a human
MAX_VERIFY_QUESTIONS = 4   # re-asks per verification (the incident question + logged answers that used the culprit)

JUDGE_SYSTEM = ("You are Memory SRE's verification judge. You check whether an AI support agent's answer is "
                "consistent with facts a human confirmed. Be strict and literal. Return ONLY a JSON object.")
JUDGE_USER = """A support rep corrected an AI support agent about the customer '{customer_name}'.
CORRECTION: {correction}

PRODUCT CATALOG:
{catalog_text}

After a memory fix, the agent was asked again:
QUESTION: {question}
NEW ANSWER: {answer}

Is the NEW ANSWER consistent with the corrected facts? Use the catalog to derive what the correction implies (for example, a plan determines features and limits). If the correction does not bear on this question, return true unless the answer contradicts it.
Return JSON: {"consistent": true or false, "reason": "<one sentence>"}"""


def judge_answer(correction: str, customer_name: str, question: str, answer: str) -> dict:
    """Small LLM judge: is a re-asked answer consistent with the incident's correction?"""
    from .llm import llm_json, render
    res = llm_json(JUDGE_SYSTEM, render(JUDGE_USER, customer_name=customer_name, correction=correction,
                                        catalog_text=catalog.catalog_text(), question=question, answer=answer),
                   max_completion_tokens=500)
    consistent = res.get("consistent")
    return {"consistent": consistent is True or str(consistent).strip().lower() == "true",
            "reason": str(res.get("reason") or "")}


def verify_fix(inc: dict) -> dict:
    """Re-ask the incident question and every logged question whose answer used the culprit memories, and judge
    each new answer against the correction. Sets inc["reask"] from the incident question."""
    if not inc.get("question"):
        return {"passed": True, "skipped": True, "checks": [], "reason": "no question to re-ask (prevented incident)"}
    targets = [(inc["customer_key"], inc["question"], inc.get("answer_format"))]
    culprit_ids = [m["id"] for m in inc["culprits"]]
    for r in (store.answers_using(culprit_ids, exclude_runs=("eval-after", "verify")) if culprit_ids else []):
        t = (r["customer_key"], r["question"], r.get("answer_format"))
        if t not in targets:
            targets.append(t)
    checks = []
    for key, question, fmt in targets[:MAX_VERIFY_QUESTIONS]:
        ans = agent.answer(key, question, fmt, run="verify")
        verdict = judge_answer(inc["correction"], catalog.customer_name(key), question, ans.answer)
        checks.append({"customer_key": key, "question": question, "answer": ans.answer, "short_answer": ans.short_answer,
                       "answer_id": ans.answer_id, **verdict})
        if (key, question) == (inc["customer_key"], inc["question"]):
            inc["reask"] = {"answer": ans.answer, "short_answer": ans.short_answer,
                            "used_memory_ids": ans.used_memory_ids,
                            "used_memories": [m.to_dict() for m in ans.used_memories]}
    return {"passed": all(c["consistent"] for c in checks), "skipped": False, "checks": checks,
            "reason": f"{sum(c['consistent'] for c in checks)} of {len(checks)} re-asked answers consistent"}


def policy_decision(inc: dict, kind: str) -> dict:
    """Should this fix be applied without a human? kind is "reactive" or "prevented"."""
    policy = store.get_policy()
    confidence = (inc.get("investigation") or {}).get("confidence")
    if confidence is None and inc.get("identity"):
        confidence = inc["identity"].get("confidence")
    reversible = inc["failure_type"] not in NO_FIX_TYPES   # every automatic fix is undoable
    auto = (policy.get(kind) == "auto" and reversible and confidence is not None
            and confidence >= policy["auto_apply_min_confidence"])
    if not reversible:
        reason = "no automatic, reversible fix for this failure type"
    elif policy.get(kind) != "auto":
        reason = f"policy requires approval for {kind} incidents"
    elif confidence is None or confidence < policy["auto_apply_min_confidence"]:
        reason = f"confidence {confidence} is below {policy['auto_apply_min_confidence']}"
    else:
        reason = f"auto-apply: {kind}, confidence {confidence:.2f} >= {policy['auto_apply_min_confidence']}, reversible"
    return {"decision": "auto" if auto else "approval", "kind": kind, "confidence": confidence, "reason": reason}


def apply_policy(inc: dict, kind: str = "reactive") -> dict:
    """Record the policy decision on the incident and, if it allows, apply (and verify) the fix."""
    decision = policy_decision(inc, kind)
    inc["policy"] = decision
    store.update_incident(inc)
    store.audit("policy_decision", inc["id"], **decision)
    if decision["decision"] == "auto" and inc["status"] in ("open", "auto-opened"):
        return apply_fix(inc["id"])
    return inc


def _execute(inc: dict) -> list[dict]:
    """Perform the reversible actions for the incident's current hypothesis. On a failure, roll back what did
    happen and re-raise."""
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
    except Exception as e:
        # Roll back what did happen; anything that could not be rolled back stays recorded for undo_fix.
        inc["applied_actions"] = _reverse(actions)
        store.update_incident(inc)
        store.audit("fix_failed_rolled_back", iid, error=str(e)[:300], actions=actions)
        raise
    return actions


def _settle(inc: dict) -> None:
    try:
        hs.wait_for_idle(MAIN, 30)
    except Exception as e:  # T7: waiting is best-effort
        print(f"[repair] wait_for_idle failed, continuing: {e}", flush=True)
    wait_until_recall_reflects(inc["customer_key"], inc.get("question"))


def _adopt(inc: dict, new: dict) -> None:
    """Replace the incident's hypothesis with the investigator's next one (the incident keeps its id)."""
    for k in ("culprits", "wrong_claim", "culprit_asserts_current_state", "culprit_reason", "supporting",
              "evidence_reason", "identity", "failure_type", "root_cause", "recommended_fix", "blast_radius", "fallback"):
        inc[k] = new[k]
    inc.setdefault("investigation", {}).setdefault("attempts", []).append(new.get("investigation"))


def apply_fix(incident_id: str) -> dict:
    """Act, verify, self-correct: apply the reversible repair, re-ask every affected question and judge the new
    answers against the correction. If any is still wrong, roll the fix back, record the failed hypothesis, and
    let the investigator try its next hypothesis (at most MAX_ATTEMPTS). Returns the updated incident: status
    "fixed" when verified, otherwise "open" with needs_human=True and nothing left applied."""
    inc = _get(incident_id)
    if inc["failure_type"] in NO_FIX_TYPES:
        raise ValueError("No automatic memory fix for this failure type")
    if inc["status"] == "fixed":
        return inc
    if inc["status"] not in ("open", "reverted", "auto-opened"):
        raise ValueError(f"Incident {incident_id} is '{inc['status']}'; only open or reverted incidents can be fixed")

    iid = inc["id"]
    inc.setdefault("hypotheses", [])
    for attempt in range(1, MAX_ATTEMPTS + 1):
        actions = _execute(inc)
        _settle(inc)
        inc["applied_actions"], inc["reask"] = actions, None
        store.audit("fix_applied", iid, attempt=attempt, failure_type=inc["failure_type"], actions=actions)
        verification = {**verify_fix(inc), "attempt": attempt}
        inc["verification"] = verification
        store.audit("verification", iid, attempt=attempt, passed=verification["passed"], reason=verification["reason"],
                    checks=[{k: c[k] for k in ("question", "short_answer", "consistent", "reason")}
                            for c in verification["checks"]])
        if verification["passed"]:
            # An incident without a question was found before any wrong answer (patrol / watch): it is "prevented".
            inc["status"], inc["needs_human"] = ("fixed" if inc.get("question") else "prevented"), False
            store.update_incident(inc)
            try:
                from . import lessons
                lessons.record(inc)
            except Exception as e:  # the lesson is a bonus; never fail the fix over it
                print(f"[repair] lesson not recorded: {e}", flush=True)
            store.update_incident(inc)
            if inc["status"] == "fixed" and store.get_policy().get("auto_patrol_after_fix"):
                try:   # autonomy: apply what was just learned across the whole bank
                    from . import autonomy
                    autonomy.patrol(apply=True, trigger="after_fix")
                except Exception as e:
                    print(f"[repair] auto-patrol failed: {e}", flush=True)
            return inc

        # Self-correct: the fix did not make the agent right. Roll it back and try the next hypothesis.
        leftover = _reverse(actions)
        inc["applied_actions"] = leftover
        store.audit("rolled_back", iid, attempt=attempt, actions=actions, not_reversed=leftover)
        inc["hypotheses"].append({
            "attempt": attempt, "failure_type": inc["failure_type"], "culprit_ids": [m["id"] for m in inc["culprits"]],
            "foreign_tag": (inc.get("identity") or {}).get("foreign_tag"), "actions": [a["kind"] for a in actions],
            "failed_checks": [c for c in verification["checks"] if not c["consistent"]]})
        store.update_incident(inc)
        if leftover or attempt == MAX_ATTEMPTS:
            break
        from . import investigator   # lazy: the investigator imports diagnose/agent
        new = investigator.next_hypothesis(inc)
        if new is None or new["failure_type"] in NO_FIX_TYPES:
            store.audit("no_new_hypothesis", iid, attempt=attempt)
            break
        _adopt(inc, new)
        store.audit("new_hypothesis", iid, attempt=attempt + 1, failure_type=inc["failure_type"])

    inc["status"], inc["needs_human"] = "open", True
    store.update_incident(inc)
    return inc


def undo_fix(incident_id: str) -> dict:
    """Reverse applied_actions in reverse order. Returns the updated incident."""
    inc = _get(incident_id)
    if inc["status"] != "fixed" and not inc["applied_actions"]:
        raise ValueError(f"Incident {incident_id} is '{inc['status']}'; only a fixed incident can be undone")
    failed = _reverse(inc["applied_actions"])
    if failed:
        inc["applied_actions"] = failed
        store.update_incident(inc)
        raise RuntimeError(f"Undo incomplete for {incident_id}: {len(failed)} action(s) could not be reversed; try again")
    restored = [a["memory_id"] for a in inc["applied_actions"] if a["kind"] == "invalidate"]
    wait_until_recall_reflects(inc["customer_key"], inc.get("question"), expect_ids=restored)
    store.audit("undo", inc["id"], actions=inc["applied_actions"])
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
