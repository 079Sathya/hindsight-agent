"""Autonomy: Watch and Patrol.

Both derive their checks ONLY from detection rules the post-mortems wrote into Hindsight (lessons.learned_rules),
skip anything a reviewer rejected (lessons.exceptions), confirm each hit with the investigator agent in patrol
mode, and then act per the autonomy policy (repair.apply_policy with kind "prevented"): apply the reversible fix
automatically, or leave an "auto-opened" incident waiting for approval.

- watch(ans): after every live answer. Cheap: signal extraction + a text search per signal value. The LLM is
  called only if a rule fires.
- patrol(): every learned rule across every customer record.
"""
from __future__ import annotations

import time

from . import catalog, config, hs, lessons, repair, store, tools
from .agent import AgentAnswer

PATROL_MAX_STEPS = 5


def investigate_candidate(c: dict, trigger: str = "patrol") -> dict:
    """Patrol-mode investigation of one rule candidate with the investigator's tool loop. Returns a finding."""
    from . import investigator
    t0 = time.monotonic()
    a, b = c["a"], c["b"]
    ctx = tools.Ctx(customer_key=a, memory=config.MEMORY_ENABLED)
    g = lessons.investigation_guidance(f"identity split: records share {c['signal_type']} {c['value']}")
    ctx.lessons_block, ctx.rejected_values = g["lessons_block"], set(g["rejected_values"])
    rule = next((r for r in lessons.learned_rules() if r["id"] == c.get("rule_id")), None)
    case = "\n".join([
        "PATROL CASE (no wrong answer has happened yet)",
        f"Detection rule that fired: [{c.get('rule_id')}] {rule['text'] if rule else ''}",
        f"Record A: customer:{a} ({catalog.customer_name(a)})",
        f"Record B: customer:{b} ({catalog.customer_name(b)})",
        f"They share {c['signal_type']}: {', '.join(c.get('values') or [c['value']])}",
        "Task: decide whether A and B are the SAME real-world customer.",
    ] + ([g["text"]] if g["text"] else []))

    def validate_final(f) -> dict:
        if not isinstance(f, dict):
            raise investigator._Protocol('"final" must be an object')
        if "compare_records" not in ctx.used_tools:
            raise investigator._Pushback("call compare_records on the two records before the verdict")
        return f

    run = investigator.run_loop(case, investigator.PATROL_FINAL, ctx, validate_final,
                                max_steps=PATROL_MAX_STEPS, system_template=investigator.PATROL_SYSTEM)
    final = run["final"]
    fallback = final is None
    if fallback:   # the agent could not finish: use the identity check directly, and say so
        ident = ctx.compares.get((a, b)) or tools.diagnose.identity_check(a, b, lessons_block=ctx.lessons_block)
        final = {"same_customer": ident["same_customer"], "confidence": ident["confidence"],
                 "linking_evidence": ident["linking_evidence"], "reason": ident["reason"]}
    same = final.get("same_customer") is True or str(final.get("same_customer")).lower() == "true"
    try:
        confidence = max(0.0, min(1.0, float(final.get("confidence"))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {"a": a, "b": b, "name_a": catalog.customer_name(a), "name_b": catalog.customer_name(b),
            "signal_type": c["signal_type"], "value": c["value"], "shared_domain": ", ".join(c.get("values") or [c["value"]]),
            "rule_id": c.get("rule_id"), "same_customer": same, "confidence": confidence,
            "linking_evidence": str(final.get("linking_evidence") or ""), "reason": str(final.get("reason") or ""),
            "trigger": trigger,
            "investigation": {"agent": "patrol", "steps": run["steps"], "llm_calls": run["llm_calls"],
                              "corrections": run["corrections"], "duration_s": round(time.monotonic() - t0, 1),
                              "fallback": fallback, "fallback_reason": run["fallback_reason"], "confidence": confidence,
                              "used_rules": [c.get("rule_id")], "memory": ctx.memory}}


def _act(finding: dict, apply: bool) -> dict:
    """Turn a confirmed finding into an incident and apply the autonomy policy."""
    if not finding["same_customer"]:
        finding["status"] = "dismissed"
        store.audit("finding_dismissed", None, pair=lessons.pair_key(finding["a"], finding["b"]),
                    confidence=finding["confidence"], reason=finding["reason"], trigger=finding["trigger"])
        return finding
    inc = lessons.prevented_incident(finding, status="auto-opened")
    store.add_incident(inc)
    store.audit("auto_opened", inc["id"], trigger=finding["trigger"], rule_id=finding["rule_id"],
                confidence=finding["confidence"], pair=lessons.pair_key(finding["a"], finding["b"]))
    inc = repair.apply_policy(inc, "prevented") if apply else inc
    finding.update(status="prevented" if inc["status"] == "prevented" else "pending", incident_id=inc["id"],
                   policy=inc.get("policy"))
    return finding


def patrol(apply: bool = True, trigger: str = "patrol") -> dict:
    """Run every learned rule across the bank and investigate each candidate with the agent.

    apply=True: confirmed findings become incidents and the autonomy policy acts on them; each finding ends
    "prevented" (auto-applied), "pending" (an auto-opened incident waiting for approval) or "dismissed".
    apply=False: nothing is written; confirmed findings are returned with status "proposed" (the UI's scan).
    Returns {"rules", "checks", "candidates", "findings", "duration_s"}."""
    t0 = time.monotonic()
    rules = lessons.learned_rules()
    checks, cands = lessons.rule_candidates(rules)
    findings = []
    for c in cands:
        f = investigate_candidate(c, trigger)
        if apply:
            f = _act(f, apply=True)
        else:
            f["status"] = "proposed" if f["same_customer"] else "dismissed"
        findings.append(f)
    report = {"rules": [r["id"] for r in rules], "checks": checks, "candidates": len(cands), "findings": findings,
              "duration_s": round(time.monotonic() - t0, 1)}
    store.audit("patrol", None, trigger=trigger, rules=report["rules"], checks=checks, candidates=len(cands),
                outcome={s: sum(f["status"] == s for f in findings)
                         for s in ("prevented", "pending", "proposed", "dismissed")})
    return report


def proposals_from(report: dict) -> list[dict]:
    """Confirmed findings in the proposal shape the scan API always returned."""
    keys = ("a", "b", "name_a", "name_b", "confidence", "linking_evidence", "shared_domain", "signal_type", "rule_id",
            "reason", "investigation", "value", "status", "incident_id")
    return [{k: f[k] for k in keys if k in f} for f in report["findings"] if f["status"] != "dismissed"]


def watch(ans: AgentAnswer) -> list[dict]:
    """After a live answer: run the learned rules as cheap checks on the recalled memories. If a rule fires,
    open an investigation (status "auto-opened") and apply the policy. No LLM call unless a rule fires."""
    rules = lessons.learned_rules()
    if not rules:
        return []
    exc = lessons.exceptions()
    bad_values, bad_pairs = {e["value"] for e in exc if e["value"]}, {e["pair"] for e in exc if e["pair"]}
    key = ans.customer_key
    own = set(store.customer_tags(key))
    crm = {c["key"] for c in catalog.load_customers()}
    cands: dict[str, dict] = {}
    for rule in rules:
        values = set().union(*[tools.extract_signals(m.text, rule["signal_type"]) for m in ans.shown_memories] or [set()])
        for value in sorted(values - bad_values):
            for d in hs.list_memories(config.MAIN_BANK_ID, q=value, limit=60):
                if d.get("fact_type") not in ("world", "experience") or value not in tools.extract_signals(
                        d.get("text") or "", rule["signal_type"]):
                    continue
                for t in d.get("tags") or []:
                    other = t.split(":", 1)[1] if t.startswith("customer:") else None
                    if not other or t in own or other in store.get_alias_keys(key):
                        continue
                    a, b = (other, key) if (other in crm and key not in crm) else (key, other)
                    if lessons.pair_key(a, b) in bad_pairs:
                        continue
                    cands.setdefault(lessons.pair_key(a, b), {"a": a, "b": b, "signal_type": rule["signal_type"],
                                                              "value": value, "values": [value], "rule_id": rule["id"]})
    fired = [_act(investigate_candidate(c, "watch"), apply=True) for c in cands.values()]
    if fired:
        store.audit("watch_fired", None, customer_key=key, answer_id=ans.answer_id,
                    findings=[(f["a"], f["b"], f["status"]) for f in fired])
    return fired
