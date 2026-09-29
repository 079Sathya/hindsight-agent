from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memsre import diagnose, hs, investigator, store, tools  # noqa: E402
from memsre.agent import AgentAnswer  # noqa: E402
from memsre.hs import Mem  # noqa: E402
from memsre.llm import LLMError  # noqa: E402

CULPRIT = Mem(id="c1", text="Kestrel Logistics signed a 12-month Enterprise plan.", date="2026-06-01",
              tags=["customer:kestrel"], source="crm_notes")
FOREIGN = Mem(id="f1", text="Anvaya Technologies Pvt Ltd changed plan from Enterprise to Growth.", date="2026-08-01",
              tags=["customer:anvaya"], source="billing_system")
SAME = {"foreign_tag": "customer:anvaya", "foreign_name": "Anvaya Technologies Pvt Ltd", "same_customer": True,
        "confidence": 0.95, "linking_evidence": "ravi.k@anvaya.in and accounts@anvaya.in", "reason": "shared domain"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("ALIASES_FILE", "INCIDENTS_FILE", "ANSWERS_FILE", "TAG_NAMES_FILE", "AUDIT_FILE", "POLICY_FILE"):
        monkeypatch.setattr(store, name, tmp_path / getattr(store, name).name)
    store.reset_state()
    store.set_tag_names({"customer:kestrel": "Kestrel Logistics", "customer:anvaya": "Anvaya Technologies Pvt Ltd"})
    monkeypatch.setattr(hs, "recall", lambda *a, **k: [FOREIGN])
    monkeypatch.setattr(hs, "list_tags", lambda *a, **k: ["customer:kestrel", "customer:anvaya"])
    calls = {"identity": 0, "pipeline": 0}

    def identity_check(a, b, lessons_block=""):
        calls["identity"] += 1
        return dict(SAME)

    def pipeline_incident(ans, correction, answer_format=None, save=True):
        calls["pipeline"] += 1
        return {"id": store.next_incident_id(), "status": "open", "failure_type": "UNKNOWN", "customer_key": ans.customer_key}

    monkeypatch.setattr(diagnose, "identity_check", identity_check)
    monkeypatch.setattr(diagnose, "pipeline_incident", pipeline_incident)
    monkeypatch.setattr(investigator.config, "MEMORY_ENABLED", False)
    return calls


def answer() -> AgentAnswer:
    return AgentAnswer(customer_key="kestrel", question="Can Kestrel Logistics export audit logs?",
                       answer="Yes, Kestrel can export audit logs.", short_answer="Yes", used_memory_ids=["c1"],
                       used_memories=[CULPRIT], shown_memories=[CULPRIT], answer_id="ANS-0001")


def script(monkeypatch, replies):
    """Make the investigator's llm_json return (or raise) the scripted replies in order."""
    it = iter(replies)

    def fake(system, user, **kw):
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(investigator, "llm_json", fake)


FINAL = {"culprit_ids": ["c1"], "wrong_claim": "Kestrel can export audit logs.", "culprit_asserts_current_state": True,
         "supporting_ids": ["f1"], "foreign_tag": "customer:anvaya", "failure_type": "RESOLUTION", "confidence": 0.9,
         "used_playbook_id": None, "reason": "the downgrade is filed under the billing name"}


def test_happy_path(env, monkeypatch):
    script(monkeypatch, [
        {"thought": "look for the correction anywhere", "action": {"tool": "recall_whole_bank", "args": {"query": "Growth plan August"}}},
        {"thought": "check the identity", "action": {"tool": "compare_records",
                                                     "args": {"tag_a": "customer:kestrel", "tag_b": "customer:anvaya"}}},
        {"thought": "enough", "final": FINAL},
    ])
    inc = diagnose.create_incident(answer(), "Wrong: they moved to Growth in August.")
    assert inc["failure_type"] == "RESOLUTION" and inc["fallback"] is False
    assert [m["id"] for m in inc["culprits"]] == ["c1"] and [m["id"] for m in inc["supporting"]] == ["f1"]
    assert inc["identity"]["same_customer"] and inc["status"] == "open"
    tr = inc["investigation"]
    assert [s["tool"] for s in tr["steps"]] == ["recall_whole_bank", "compare_records", "final"]
    assert tr["llm_calls"] == 4 and env["identity"] == 1 and env["pipeline"] == 0   # 3 agent turns + 1 identity check
    assert store.get_incident(inc["id"]) is not None                                # saved


def test_invalid_json_then_correction_succeeds(env, monkeypatch):
    script(monkeypatch, [
        LLMError("not JSON"),                                                                # invalid -> corrected
        {"thought": "search", "action": {"tool": "recall_whole_bank", "args": {"query": "Growth"}}},
        {"thought": "missing arg", "action": {"tool": "compare_records", "args": {"tag_a": "kestrel"}}},  # invalid -> corrected
        {"thought": "verify", "action": {"tool": "compare_records", "args": {"tag_a": "kestrel", "tag_b": "anvaya"}}},
        {"thought": "done", "final": FINAL},
    ])
    inc = diagnose.create_incident(answer(), "Wrong: Growth since August.")
    assert inc["fallback"] is False and inc["failure_type"] == "RESOLUTION"   # never 2 failures in a row
    tr = inc["investigation"]
    assert tr["corrections"] == 2
    assert [s["tool"] for s in tr["steps"]] == ["invalid", "recall_whole_bank", "invalid", "compare_records", "final"]


def test_max_steps_falls_back(env, monkeypatch):
    script(monkeypatch, [{"thought": "again", "action": {"tool": "list_customer_tags", "args": {}}}] * 20)
    inc = diagnose.create_incident(answer(), "Wrong.")
    assert inc["fallback"] is True and env["pipeline"] == 1
    tr = inc["investigation"]
    assert len(tr["steps"]) == investigator.MAX_STEPS and "no verdict" in tr["fallback_reason"]


def test_unknown_tool_falls_back_after_two_failures(env, monkeypatch):
    bad = {"thought": "wipe it", "action": {"tool": "delete_bank", "args": {}}}
    script(monkeypatch, [bad, bad, {"thought": "never reached", "final": FINAL}])
    inc = diagnose.create_incident(answer(), "Wrong.")
    assert inc["fallback"] is True and env["pipeline"] == 1
    assert "unknown tool 'delete_bank'" in inc["investigation"]["fallback_reason"]


def test_guardrails_verify_identity_and_classify_wins(env, monkeypatch):
    # The agent claims EXECUTION, cites an id it never saw, and skips compare_records.
    verdict = {**FINAL, "failure_type": "EXECUTION", "supporting_ids": ["f1", "ghost"], "foreign_tag": None}
    script(monkeypatch, [
        {"thought": "search", "action": {"tool": "recall_whole_bank", "args": {"query": "Growth"}}},
        {"thought": "done", "final": verdict},
    ])
    inc = diagnose.create_incident(answer(), "Wrong.")
    assert [m["id"] for m in inc["supporting"]] == ["f1"]                 # unseen id dropped
    assert env["identity"] == 1                                            # guardrail ran the identity check
    assert inc["failure_type"] == "RESOLUTION"                             # classify() on the evidence wins
    assert inc["investigation"]["agent_failure_type"] == "EXECUTION"


def test_premature_verdicts_are_pushed_back_not_counted_as_failures(env, monkeypatch):
    guess = {"thought": "guess", "final": {**FINAL, "supporting_ids": []}}          # no evidence yet
    script(monkeypatch, [
        guess, guess,                                                              # two rejections in a row
        {"thought": "search", "action": {"tool": "recall_whole_bank", "args": {"query": "Growth"}}},
        {"thought": "verify", "action": {"tool": "compare_records", "args": {"tag_a": "kestrel", "tag_b": "anvaya"}}},
        {"thought": "done", "final": FINAL},
    ])
    inc = diagnose.create_incident(answer(), "Wrong: Growth since August.")
    assert inc["fallback"] is False and inc["failure_type"] == "RESOLUTION"
    tools_used = [s["tool"] for s in inc["investigation"]["steps"]]
    assert tools_used == ["verdict_rejected", "verdict_rejected", "recall_whole_bank", "compare_records", "final"]


def test_a_lead_from_find_records_sharing_must_be_followed(env, monkeypatch):
    # Kestrel's own admin uses @anvaya.in; the shared-signal search surfaces customer:anvaya as a lead.
    shared = [{"id": "k9", "fact_type": "world", "text": "Admin ravi.k@anvaya.in for Kestrel.", "tags": ["customer:kestrel"]},
              {"id": "f1", "fact_type": "world", "text": FOREIGN.text + " accounts@anvaya.in", "tags": ["customer:anvaya"]}]
    monkeypatch.setattr(hs, "list_memories", lambda *a, **k: shared)
    missing = {"thought": "nothing about Growth", "final": {**FINAL, "failure_type": "MISSING_KNOWLEDGE", "supporting_ids": []}}
    script(monkeypatch, [
        {"thought": "look", "action": {"tool": "recall_whole_bank", "args": {"query": "Growth"}}},
        {"thought": "domain", "action": {"tool": "find_records_sharing", "args": {"signal_type": "email_domain", "value": "anvaya.in"}}},
        missing,                                                                  # pushed back: open lead
        {"thought": "follow the lead", "action": {"tool": "compare_records", "args": {"tag_a": "kestrel", "tag_b": "anvaya"}}},
        {"thought": "done", "final": FINAL},
    ])
    inc = diagnose.create_incident(answer(), "Wrong: Growth since August.")
    steps = inc["investigation"]["steps"]
    assert steps[2]["tool"] == "verdict_rejected" and "customer:anvaya" in steps[2]["result_summary"]
    assert inc["failure_type"] == "RESOLUTION" and inc["fallback"] is False


def test_case_file_lists_own_identifiers_and_each_turn_shows_open_leads(env, monkeypatch):
    # The agent searches with the customer's real identifiers (not guesses) and sees its unfollowed leads.
    admin = Mem(id="k9", text="Kestrel admin contact is ravi.k@anvaya.in, phone +91 98450 12345.", date="2026-05-01",
                tags=["customer:kestrel"], source="crm_notes")
    monkeypatch.setattr(hs, "recall", lambda bank, query, tags=None, **k: [admin] if tags else [FOREIGN])
    shared = [{"id": "k9", "fact_type": "world", "text": admin.text, "tags": ["customer:kestrel"]},
              {"id": "f1", "fact_type": "world", "text": FOREIGN.text + " accounts@anvaya.in", "tags": ["customer:anvaya"]}]
    monkeypatch.setattr(hs, "list_memories", lambda *a, **k: shared)
    prompts = []
    replies = iter([
        {"thought": "search the domain", "action": {"tool": "find_records_sharing",
                                                    "args": {"signal_type": "email_domain", "value": "anvaya.in"}}},
        {"thought": "follow the lead", "action": {"tool": "compare_records", "args": {"tag_a": "kestrel", "tag_b": "anvaya"}}},
        {"thought": "done", "final": FINAL},
    ])
    monkeypatch.setattr(investigator, "llm_json", lambda system, user, **kw: prompts.append(user) or next(replies))
    inc = diagnose.create_incident(answer(), "Wrong: Growth since August.")
    assert inc["failure_type"] == "RESOLUTION" and inc["fallback"] is False
    assert "- email_domain: anvaya.in" in prompts[0] and "ravi.k@anvaya.in" in prompts[0] and "- phone: 9845012345" in prompts[0]
    assert "TURNS LEFT: 10" in prompts[0] and "OPEN LEADS" not in prompts[0]
    assert "TURNS LEFT: 9" in prompts[1] and "OPEN LEADS" in prompts[1] and "customer:anvaya" in prompts[1].split("OPEN LEADS")[1]
    assert "OPEN LEADS" not in prompts[2]                                          # the lead was followed
    assert inc["investigation"]["identifiers"]["email_domain"] == ["anvaya.in"]


def test_phone_search_matches_any_formatting(env, monkeypatch):
    queries = []
    rows = [{"id": "p1", "fact_type": "world", "text": "Call Kestrel ops on +91 98450 12345.", "tags": ["customer:kestrel"]},
            {"id": "p2", "fact_type": "world", "text": "Anvaya billing: 98450-12345.", "tags": ["customer:anvaya"]},
            {"id": "p3", "fact_type": "world", "text": "Other line 98450 99999, ref 12345.", "tags": ["customer:other"]}]
    monkeypatch.setattr(hs, "list_memories", lambda *a, q=None, **k: queries.append(q) or rows)
    ctx = tools.Ctx(customer_key="kestrel", memory=False)
    out = tools.find_records_sharing(ctx, "phone", "+91-98450-12345")
    assert queries == ["12345"] and "customer:kestrel" in out and "customer:anvaya" in out and "customer:other" not in out
    assert ctx.leads == {"customer:anvaya"}
    with pytest.raises(tools.ToolError):
        tools.find_records_sharing(ctx, "phone", "12-34")


def test_force_pipeline_flag(env, monkeypatch):
    monkeypatch.setattr(diagnose, "FORCE_PIPELINE", True)
    script(monkeypatch, [])
    inc = diagnose.create_incident(answer(), "Wrong.")
    assert env["pipeline"] == 1 and "investigation" not in inc
