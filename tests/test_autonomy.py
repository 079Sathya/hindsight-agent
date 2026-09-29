from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memsre import autonomy, config, hs, lessons, store  # noqa: E402
from memsre.agent import AgentAnswer  # noqa: E402
from memsre.hs import Mem  # noqa: E402

RULE = {"id": "rule-INC-001", "signal_type": "email_domain", "text": "records sharing an email domain"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("ALIASES_FILE", "INCIDENTS_FILE", "ANSWERS_FILE", "TAG_NAMES_FILE", "AUDIT_FILE", "POLICY_FILE"):
        monkeypatch.setattr(store, name, tmp_path / getattr(store, name).name)
    store.reset_state()
    store.set_tag_names({"customer:saffron": "Saffron Retail", "customer:mehta-bros": "Mehta Brothers Trading LLP",
                         "customer:monsoon": "Monsoon Trails", "customer:ruparel": "Ruparel Holidays Pvt Ltd",
                         "customer:pinecrest": "Pinecrest Hospitals", "customer:vanadium": "Vanadium Energy"})
    monkeypatch.setattr(config, "MEMORY_ENABLED", True)
    calls = {"search": 0, "writes": []}

    def list_memories(bank_id, type=None, q=None, state=None, limit=100, tags=None):
        calls["search"] += 1
        return [{"id": "m1", "fact_type": "world", "text": "Mehta Brothers billing contact accounts@mehtabros.co.in.",
                 "tags": ["customer:mehta-bros"]}] if q == "mehtabros.co.in" else []
    monkeypatch.setattr(hs, "list_memories", list_memories)
    monkeypatch.setattr(hs, "retain_event", lambda *a, **k: calls["writes"].append(k["document_id"]))
    monkeypatch.setattr(hs, "wait_for_idle", lambda *a, **k: True)
    monkeypatch.setattr(hs, "wait_for_consistent_recall", lambda *a, **k: True)
    monkeypatch.setattr(lessons, "record", lambda inc: None)
    monkeypatch.setattr(lessons, "exceptions", lambda: [])
    return calls


def finding(c, same=True, confidence=0.95):
    return {"a": c["a"], "b": c["b"], "name_a": store.get_tag_names()[f"customer:{c['a']}"],
            "name_b": store.get_tag_names()[f"customer:{c['b']}"], "signal_type": "email_domain", "value": c["value"],
            "shared_domain": c["value"], "rule_id": RULE["id"], "same_customer": same, "confidence": confidence,
            "linking_evidence": "shared domain", "reason": "r", "trigger": "patrol",
            "investigation": {"agent": "patrol", "steps": [{"tool": "compare_records"}], "llm_calls": 2,
                              "confidence": confidence}}


def test_no_rules_means_no_checks_no_llm(env, monkeypatch):
    monkeypatch.setattr(lessons, "learned_rules", lambda: [])
    monkeypatch.setattr(autonomy, "investigate_candidate", lambda *a, **k: pytest.fail("no LLM without a rule"))
    report = autonomy.patrol()
    assert report["checks"] == 0 and report["candidates"] == 0 and report["findings"] == []
    ans = AgentAnswer("saffron", "q", "a", "s", [], [], [Mem("x", "it-desk@mehtabros.co.in", "", ["customer:saffron"], "")], "A1")
    assert autonomy.watch(ans) == [] and env["search"] == 0


def test_patrol_applies_the_policy(env, monkeypatch):
    cands = [{"a": "saffron", "b": "mehta-bros", "value": "mehtabros.co.in"},
             {"a": "monsoon", "b": "ruparel", "value": "ruparelholidays.in"},
             {"a": "pinecrest", "b": "vanadium", "value": "nimbusit.in"}]
    monkeypatch.setattr(lessons, "learned_rules", lambda: [RULE])
    monkeypatch.setattr(lessons, "rule_candidates", lambda rules=None: (6, [{**c, "values": [c["value"]],
                                                                              "signal_type": "email_domain",
                                                                              "rule_id": RULE["id"]} for c in cands]))
    verdicts = {"saffron": (True, 0.95), "monsoon": (True, 0.6), "pinecrest": (False, 0.9)}
    monkeypatch.setattr(autonomy, "investigate_candidate", lambda c, trigger="patrol": finding(c, *verdicts[c["a"]]))

    report = autonomy.patrol(apply=True)
    status = {f["a"]: f["status"] for f in report["findings"]}
    assert status == {"saffron": "prevented", "monsoon": "pending", "pinecrest": "dismissed"}
    incs = {i["customer_key"]: i for i in store.list_incidents()}
    assert incs["saffron"]["status"] == "prevented" and incs["saffron"]["policy"]["decision"] == "auto"
    assert incs["monsoon"]["status"] == "auto-opened" and incs["monsoon"]["policy"]["decision"] == "approval"
    assert "pinecrest" not in incs                                      # dismissed findings write nothing
    assert ("mehta-bros", "saffron") in store.alias_pairs() and ("monsoon", "ruparel") not in store.alias_pairs()
    assert "sre-alias-saffron-mehta-bros" in env["writes"]


def test_scan_wrapper_writes_nothing(env, monkeypatch):
    monkeypatch.setattr(lessons, "learned_rules", lambda: [RULE])
    monkeypatch.setattr(lessons, "rule_candidates", lambda rules=None: (
        6, [{"a": "saffron", "b": "mehta-bros", "value": "mehtabros.co.in", "values": ["mehtabros.co.in"],
             "signal_type": "email_domain", "rule_id": RULE["id"]}]))
    monkeypatch.setattr(autonomy, "investigate_candidate", lambda c, trigger="patrol": finding(c))
    props = lessons.proactive_identity_scan()
    assert [(p["a"], p["b"], p["shared_domain"]) for p in props] == [("saffron", "mehta-bros", "mehtabros.co.in")]
    assert store.list_incidents() == [] and store.alias_pairs() == []


def test_watch_fires_on_a_learned_rule_and_acts(env, monkeypatch):
    monkeypatch.setattr(lessons, "learned_rules", lambda: [RULE])
    seen = []
    monkeypatch.setattr(autonomy, "investigate_candidate",
                        lambda c, trigger="patrol": seen.append((c["a"], c["b"], trigger)) or finding(c))
    ans = AgentAnswer("saffron", "Can Saffron Retail enable SSO?", "No.", "no", [], [],
                      [Mem("x", "Workspace admin contact: it-desk@mehtabros.co.in.", "", ["customer:saffron"], "")], "A1")
    fired = autonomy.watch(ans)
    assert seen == [("saffron", "mehta-bros", "watch")]
    assert [f["status"] for f in fired] == ["prevented"] and ("mehta-bros", "saffron") in store.alias_pairs()
