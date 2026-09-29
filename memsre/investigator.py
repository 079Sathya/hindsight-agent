"""The investigator agent: a bounded tool-using loop that diagnoses a wrong answer.

Protocol (JSON actions via llm_json, not native tool calling). Each turn the LLM returns either
    {"thought": str, "action": {"tool": name, "args": {...}}}   or   {"thought": str, "final": {...}}
Guardrails:
- every action is validated against tools.REGISTRY (names + arg schemas);
- an invalid reply gets one corrective message; 2 consecutive invalid replies, or running out of turns,
  falls back to the fixed pipeline (incident["fallback"] = True);
- the verdict may only cite memories the agent was shown; a cross-customer verdict must be backed by a
  compare_records identity check (run automatically if the agent skipped it);
- failure_type is always recomputed by diagnose.classify() from the gathered evidence.
"""
from __future__ import annotations

import json
import time

from . import catalog, config, diagnose, store, tools
from .agent import AgentAnswer, memory_line
from .llm import LLMError, llm_json

MAX_STEPS = 10
MAX_CONSECUTIVE_FAILURES = 2
FULL_RESULTS_KEPT = 3          # older tool results are shortened in the transcript to keep prompts small
STEP_TOKENS = 900

SYSTEM = """You are the Memory SRE investigator: a reliability engineer for an AI support agent whose long-term memory lives in Hindsight. A support rep reported a wrong answer. Work out whether memory caused it, which memory, and what would make the agent right. Act step by step with tools, then give a verdict.

Each turn reply with ONE JSON object, either an action:
{"thought": "<one short sentence>", "action": {"tool": "<tool name>", "args": {<arguments>}}}
or, once the evidence is enough, the verdict:
{"thought": "<one short sentence>", "final": FINAL}

TOOLS:
{tool_catalog}

METHOD (general; adapt it to the case):
1. Culprit: which memory the agent used makes the wrong claim true, given the product catalog.
2. Correct fact: search this customer's memories, then the whole bank. Customers are often recorded under several names (brand, legal entity, billing account), so a memory filed under ANOTHER customer tag can still be about this customer.
3. If the correct fact only appears under another record, suspect an identity split: take concrete signals from this customer's records (email domains, people, phone numbers, account ids), call find_records_sharing to see which other records share them, then confirm with compare_records.
4. Decide the failure type from the evidence, then finish.

FAILURE TYPES: RESOLUTION = the correct fact is stored under another record/name for the same customer; FRESHNESS = a newer fact under this customer superseded the recalled one; RECALL_MISS = the correct fact exists under this customer but was not recalled; EXECUTION = the correct memory was used and the answer is still wrong; MISSING_KNOWLEDGE = memory never had the correct fact; UNKNOWN = no memory-level cause.

GUARDRAILS:
- Gather evidence with tools before the verdict; a verdict the evidence cannot back is rejected.
- Cite only memory ids shown to you by the case file or by tools.
- culprit_ids come from MEMORIES THE AGENT USED: the memories the wrong claim follows from (together with the product catalog).
- supporting_ids are memories that prove the correction; they may be filed under another customer's tag.
- Before a RESOLUTION verdict, confirm the two records are the same customer with compare_records.
- Never treat a REJECTED PATTERN as linking evidence.
- If a proven playbook matches this case, follow its tool path first.
- Be efficient: at most {max_steps} turns in total."""

REACTIVE_FINAL = ('{"culprit_ids": ["<id>"], "wrong_claim": "<one sentence>", "culprit_asserts_current_state": true or false, '
                  '"supporting_ids": ["<id>"], "foreign_tag": "customer:<key>" or null, "failure_type": "<type>", '
                  '"confidence": 0.0-1.0, "used_playbook_id": "<id>" or null, "reason": "<one sentence>"}')


class _Protocol(Exception):
    """The agent's reply broke the protocol (bad JSON, unknown tool, bad args); the message is sent back to it.
    Two in a row end the loop (fallback)."""


class _Pushback(Exception):
    """A well-formed verdict the gathered evidence cannot back. The agent is told why and keeps investigating;
    this uses a turn but is not a protocol failure."""


def _render_transcript(transcript: list[dict]) -> str:
    out, n_results = [], sum(1 for t in transcript if "result" in t)
    seen_results = 0
    for i, t in enumerate(transcript, 1):
        if "invalid" in t:
            out.append(f"TURN {i}: INVALID REPLY — {t['invalid']}. Reply with exactly one JSON object in the required format.")
            continue
        if "pushback" in t:
            out.append(f"TURN {i}: VERDICT REJECTED — {t['pushback']}. Continue the investigation with a tool call.")
            continue
        seen_results += 1
        result = t["result"]
        if n_results - seen_results >= FULL_RESULTS_KEPT:
            lines = result.splitlines()
            result = "\n".join(lines[:2]) + ("\n…" if len(lines) > 2 else "")
        out.append(f"TURN {i}\nthought: {t['thought']}\naction: {t['tool']} {json.dumps(t['args'], ensure_ascii=False)}\n"
                   f"result:\n{result}")
    return "\n\n".join(out)


def run_loop(case: str, final_schema: str, ctx: tools.Ctx, validate_final, *, max_steps: int = MAX_STEPS) -> dict:
    """Drive the JSON-action loop. Returns {final | None, steps, llm_calls, corrections, fallback_reason}."""
    system = (SYSTEM.replace("{tool_catalog}", tools.tool_catalog()).replace("{max_steps}", str(max_steps))
              .replace("FINAL", final_schema))
    transcript: list[dict] = []
    steps, llm_calls, corrections, failures = [], 0, 0, 0
    final, fallback_reason = None, None
    for _turn in range(max_steps):
        user = case + "\n\nSTEPS SO FAR:\n" + (_render_transcript(transcript) or "(none yet)") + "\n\nYour next JSON object:"
        try:
            llm_calls += 1
            reply = llm_json(system, user, max_completion_tokens=STEP_TOKENS)
            if not isinstance(reply, dict):
                raise _Protocol("the reply must be a JSON object")
            if "final" in reply:
                final = validate_final(reply["final"])
                steps.append({"thought": str(reply.get("thought") or ""), "tool": "final", "args": {},
                              "result_summary": "verdict"})
                break
            if "action" not in reply:
                raise _Protocol('the object needs either "action" or "final"')
            try:
                tool, args = tools.validate_action(reply["action"])
            except ValueError as e:
                raise _Protocol(str(e)) from None
            result = tools.run_tool(ctx, tool, args)
            ctx.used_tools.append(tool.name)
            failures = 0
            thought = str(reply.get("thought") or "")
            transcript.append({"thought": thought, "tool": tool.name, "args": args, "result": result})
            steps.append({"thought": thought, "tool": tool.name, "args": args, "result_summary": result[:600]})
        except _Pushback as e:
            failures = 0
            transcript.append({"pushback": str(e)})
            steps.append({"thought": str(reply.get("thought") or ""), "tool": "verdict_rejected", "args": {},
                          "result_summary": str(e)[:300]})
        except (_Protocol, LLMError) as e:
            msg = str(e) if isinstance(e, _Protocol) else "the reply was not valid JSON"
            failures += 1
            corrections += 1
            transcript.append({"invalid": msg})
            steps.append({"thought": "", "tool": "invalid", "args": {}, "result_summary": msg[:300]})
            if failures >= MAX_CONSECUTIVE_FAILURES:
                fallback_reason = f"{failures} consecutive invalid replies ({msg})"
                break
    else:
        fallback_reason = f"no verdict within {max_steps} turns"
    return {"final": final, "steps": steps, "llm_calls": llm_calls + ctx.llm_calls, "corrections": corrections,
            "fallback_reason": None if final is not None else fallback_reason}


def _as_ids(value) -> list[str]:
    if not isinstance(value, list):
        value = [value] if value else []
    return [str(v).strip().strip("[]") for v in value if str(v).strip()]


def _guidance(ctx: tools.Ctx, symptom: str) -> tuple[str, list[str], list[str]]:
    """Playbooks, learned rules and rejected patterns from the lessons bank (memory ON only)."""
    if not ctx.memory:
        return "", [], []
    from . import lessons
    try:
        g = lessons.investigation_guidance(symptom)
    except Exception as e:  # lessons are a bonus; never block an investigation on them
        print(f"[investigator] no guidance: {e}", flush=True)
        return "", [], []
    ctx.lessons_block = g.get("lessons_block", "")
    ctx.rejected_values = set(g.get("rejected_values", []))
    return g.get("text", ""), g.get("playbook_ids", []), g.get("rule_ids", [])


def investigate(ans: AgentAnswer, correction: str, answer_format: str | None = None) -> dict:
    """Investigate a reported wrong answer with the tool loop, save the incident, then apply the autonomy policy
    (repair.apply_policy: auto-apply + verify only if the policy and the agent's confidence allow it)."""
    incident = _investigate_core(ans, correction, answer_format)
    store.add_incident(incident)
    store.audit("investigated", incident["id"], failure_type=incident["failure_type"], fallback=incident["fallback"],
                steps=len(incident["investigation"]["steps"]), llm_calls=incident["investigation"]["llm_calls"])
    from . import repair   # lazy: repair imports agent/diagnose
    return repair.apply_policy(incident, "reactive")


def answer_from_incident(inc: dict) -> AgentAnswer:
    """Rebuild the reported AgentAnswer from an incident (for re-investigation)."""
    from .hs import Mem
    used = [Mem.from_dict(m) for m in inc["used_memories"]]
    return AgentAnswer(customer_key=inc["customer_key"], question=inc["question"], answer=inc["wrong_answer"] or "",
                       short_answer=inc["wrong_short_answer"] or "", used_memory_ids=[m.id for m in used],
                       used_memories=used, shown_memories=used, answer_id="")


def next_hypothesis(inc: dict) -> dict | None:
    """Self-correction: re-investigate with every failed hypothesis in the case file and return a new, unsaved
    incident dict with a different explanation, or None if the agent reproduces a failed one."""
    failed = inc.get("hypotheses") or []
    lines = ["PREVIOUS HYPOTHESES THAT FAILED VERIFICATION (the fix was applied, the re-asked answers were still "
             "wrong, and the fix was rolled back). Find a DIFFERENT explanation: other culprit memories, other "
             "evidence, or another failure type."]
    for h in failed:
        lines.append(f"- attempt {h['attempt']}: {h['failure_type']}, culprits {h['culprit_ids']}, "
                     f"foreign record {h.get('foreign_tag') or '-'}; still wrong: "
                     + "; ".join(f"'{c['question']}' -> '{c['short_answer']}' ({c['reason']})" for c in h["failed_checks"]))
    new = _investigate_core(answer_from_incident(inc), inc["correction"], inc.get("answer_format"),
                            extra_context="\n".join(lines))
    same = lambda h: (h["failure_type"] == new["failure_type"] and h["culprit_ids"] == [m["id"] for m in new["culprits"]]
                      and h.get("foreign_tag") == (new["identity"] or {}).get("foreign_tag"))
    return None if any(same(h) for h in failed) else new


def _investigate_core(ans: AgentAnswer, correction: str, answer_format: str | None = None,
                      extra_context: str = "") -> dict:
    """One investigation: the tool loop, then an (unsaved) incident dict with the full trace."""
    t0 = time.monotonic()
    key = ans.customer_key
    ctx = tools.Ctx(customer_key=key, memory=config.MEMORY_ENABLED)
    for m in ans.used_memories:
        ctx.seen[m.id] = m
    guidance, playbook_ids, rule_ids = _guidance(ctx, f"{ans.question} {correction}")
    case = "\n".join([
        "CASE",
        f"Customer: {catalog.customer_name(key)} (tags: {', '.join(store.customer_tags(key))})",
        f"Question: {ans.question}",
        f"Agent's wrong answer: {ans.answer}",
        f"Correction from the support rep: {correction}",
        "MEMORIES THE AGENT USED:",
        "\n".join(memory_line(m) for m in ans.used_memories) or "(none)",
        "PRODUCT CATALOG:",
        catalog.catalog_text(),
    ] + ([guidance] if guidance else []) + ([extra_context] if extra_context else []))

    def validate_final(f) -> dict:
        """Reject verdicts the gathered evidence cannot back; the agent is told why and keeps investigating."""
        if not isinstance(f, dict):
            raise _Protocol('"final" must be an object')
        ftype = str(f.get("failure_type") or "").strip().upper()
        if ftype not in diagnose.FAILURE_TYPES:
            raise _Protocol(f"final.failure_type must be one of {', '.join(diagnose.FAILURE_TYPES)}")
        supporting = [i for i in _as_ids(f.get("supporting_ids")) if i in ctx.seen and i not in ans.used_memory_ids]
        searched_bank = any(t in ctx.used_tools for t in ("recall_whole_bank", "find_records_sharing"))
        if ftype in ("RESOLUTION", "FRESHNESS", "RECALL_MISS", "EXECUTION") and not supporting:
            raise _Pushback(f"a {ftype} verdict needs supporting_ids: memories you were shown that prove the "
                            "correction. Find them first (they may be filed under another customer tag)")
        if ftype == "RESOLUTION" and "compare_records" not in ctx.used_tools:
            raise _Pushback("a RESOLUTION verdict needs a compare_records check of the two customer records first")
        if ftype in ("MISSING_KNOWLEDGE", "UNKNOWN") and not searched_bank:
            raise _Pushback(f"before concluding {ftype}, search the whole bank for the correct fact "
                            "(recall_whole_bank), since it may be filed under another customer name")
        own = set(store.customer_tags(key))
        foreign_seen = sorted({t for m in ctx.seen.values() for t in m.tags if t.startswith("customer:")} - own)
        checked = any(t in ctx.used_tools for t in ("compare_records", "find_records_sharing"))
        if ftype in ("MISSING_KNOWLEDGE", "UNKNOWN") and foreign_seen and not checked:
            raise _Pushback(f"your searches returned records filed under other customer tags ({', '.join(foreign_seen[:5])}). "
                            "Before concluding the fact is missing, rule out that the record stating the corrected fact "
                            "is this same customer under another name (find_records_sharing / compare_records)")
        return {**f, "failure_type": ftype}

    run = run_loop(case, REACTIVE_FINAL, ctx, validate_final)
    final = run["final"]
    if final is None:
        incident = diagnose.pipeline_incident(ans, correction, answer_format, save=False)
        incident["fallback"] = True
    else:
        incident = _incident_from_verdict(ans, correction, answer_format, final, ctx, run)
        incident["fallback"] = False
    claimed = (final or {}).get("used_playbook_id")
    incident["investigation"] = {
        "agent": "investigator",
        "steps": run["steps"],
        "llm_calls": run["llm_calls"] + incident.pop("_guardrail_calls", 0),
        "corrections": run["corrections"],
        "duration_s": round(time.monotonic() - t0, 1),
        "used_playbook_id": claimed if claimed in playbook_ids else None,
        "playbooks_shown": playbook_ids,
        "used_rules": rule_ids,
        "agent_failure_type": (final or {}).get("failure_type"),
        "confidence": _confidence((final or {}).get("confidence")),
        "fallback": final is None,
        "fallback_reason": run["fallback_reason"],
        "memory": ctx.memory,
    }
    return incident


def _confidence(v) -> float | None:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return None


def _incident_from_verdict(ans, correction, answer_format, final: dict, ctx: tools.Ctx, run: dict) -> dict:
    key = ans.customer_key
    cust_tags = store.customer_tags(key)
    culprit_ids = [i for i in _as_ids(final.get("culprit_ids")) if i in ans.used_memory_ids]
    culprits = [m for m in ans.used_memories if m.id in culprit_ids]
    supporting = [ctx.seen[i] for i in dict.fromkeys(_as_ids(final.get("supporting_ids"))) if i in ctx.seen]

    # Identity: must come from a compare_records check. If the evidence is filed under another customer and the
    # agent skipped the check, run it now (guardrail) rather than trusting an unverified claim.
    identity, guardrail_calls = None, 0
    foreign = str(final.get("foreign_tag") or "").strip()
    foreign_tags = [foreign] if foreign.startswith("customer:") and foreign not in cust_tags else []
    foreign_tags += [t for m in supporting for t in m.tags
                     if t.startswith("customer:") and t not in cust_tags and t not in foreign_tags]
    if foreign_tags:
        fkey = foreign_tags[0].split(":", 1)[1]
        identity = ctx.compares.get((key, fkey))
        if identity is None and ctx.compares.get((fkey, key)):
            identity = {**ctx.compares[(fkey, key)], "foreign_tag": f"customer:{fkey}",
                        "foreign_name": catalog.customer_name(fkey)}
        if identity is None:
            identity = diagnose.identity_check(key, fkey, lessons_block=ctx.lessons_block)
            guardrail_calls = 1
            run["steps"].append({"thought": "guardrail: verify the cross-customer evidence", "tool": "compare_records",
                                 "args": {"tag_a": f"customer:{key}", "tag_b": f"customer:{fkey}"},
                                 "result_summary": f"same_customer={identity['same_customer']} "
                                                   f"confidence={identity['confidence']:.2f}"})
    incident = diagnose.build_incident(
        ans, correction, answer_format, culprits=culprits, wrong_claim=str(final.get("wrong_claim") or ""),
        asserts_current=diagnose._truthy(final.get("culprit_asserts_current_state")),
        culprit_reason=str(final.get("reason") or ""), supporting=supporting,
        evidence_reason=str(final.get("reason") or ""), identity=identity)
    incident["_guardrail_calls"] = guardrail_calls
    return incident
