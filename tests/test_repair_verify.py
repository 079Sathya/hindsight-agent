from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memsre import hs, investigator, lessons, repair, store  # noqa: E402
from memsre.agent import AgentAnswer  # noqa: E402

C1 = {"id": "c1", "text": "Kestrel signed Enterprise.", "date": "2026-06-01", "tags": ["customer:kestrel"], "source": "crm"}
C2 = {"id": "c2", "text": "Kestrel is on Enterprise (old note).", "date": "2026-05-01", "tags": ["customer:kestrel"], "source": "crm"}


def incident(**over) -> dict:
    inc = {"id": "INC-001", "status": "open", "customer_key": "kestrel", "customer_name": "Kestrel Logistics",
           "question": "Can Kestrel Logistics export audit logs?", "answer_format": None,
           "wrong_answer": "Yes.", "wrong_short_answer": "Yes", "correction": "Wrong: Growth since August.",
           "used_memories": [C1], "culprits": [C1], "wrong_claim": "can export", "culprit_asserts_current_state": True,
           "culprit_reason": "", "supporting": [], "evidence_reason": "", "failure_type": "RESOLUTION",
           "identity": {"foreign_tag": "customer:anvaya", "foreign_name": "Anvaya Technologies Pvt Ltd",
                        "same_customer": True, "confidence": 0.95, "linking_evidence": "anvaya.in", "reason": ""},
           "root_cause": "", "blast_radius": {"answers_affected": 0, "answer_ids": []}, "recommended_fix": [],
           "applied_actions": [], "reask": None, "fallback": False, "investigation": {"confidence": 0.9, "steps": []}}
    inc.update(over)
    return inc


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("ALIASES_FILE", "INCIDENTS_FILE", "ANSWERS_FILE", "TAG_NAMES_FILE", "AUDIT_FILE", "POLICY_FILE"):
        monkeypatch.setattr(store, name, tmp_path / getattr(store, name).name)
    store.reset_state()
    store.set_tag_names({"customer:kestrel": "Kestrel Logistics", "customer:anvaya": "Anvaya Technologies Pvt Ltd"})
    calls = []
    monkeypatch.setattr(hs, "invalidate", lambda bank, mid, reason: calls.append(("invalidate", mid)))
    monkeypatch.setattr(hs, "restore", lambda bank, mid: calls.append(("restore", mid)))
    monkeypatch.setattr(hs, "retain_event", lambda *a, **k: calls.append(("retain", k["document_id"])))
    monkeypatch.setattr(hs, "delete_document", lambda bank, doc: calls.append(("delete_doc", doc)))
    monkeypatch.setattr(hs, "wait_for_idle", lambda *a, **k: True)
    monkeypatch.setattr(hs, "wait_for_consistent_recall", lambda *a, **k: True)
    monkeypatch.setattr(lessons, "record", lambda inc: calls.append(("lesson", inc["id"])))
    monkeypatch.setattr(repair.agent, "answer", lambda key, q, fmt=None, run="live": AgentAnswer(
        customer_key=key, question=q, answer="some answer", short_answer="x", used_memory_ids=[], used_memories=[],
        shown_memories=[], answer_id="ANS-9"))
    return calls


def judge_script(monkeypatch, verdicts):
    it = iter(verdicts)
    monkeypatch.setattr(repair, "judge_answer", lambda *a, **k: {"consistent": next(it), "reason": "judged"})


def test_failed_verification_rolls_back_and_next_hypothesis_is_verified(env, monkeypatch):
    store.add_incident(incident())
    judge_script(monkeypatch, [False, True])
    second = incident(failure_type="FRESHNESS", culprits=[C2], identity=None, investigation={"confidence": 0.8})
    monkeypatch.setattr(investigator, "next_hypothesis", lambda inc: second)

    inc = repair.apply_fix("INC-001")

    assert inc["status"] == "fixed" and inc["needs_human"] is False
    assert len(inc["hypotheses"]) == 1 and inc["hypotheses"][0]["failure_type"] == "RESOLUTION"
    assert inc["hypotheses"][0]["failed_checks"][0]["consistent"] is False
    assert inc["failure_type"] == "FRESHNESS" and inc["verification"]["passed"] and inc["verification"]["attempt"] == 2
    # attempt 1 applied, then fully rolled back in reverse order; attempt 2 applied
    assert env == [("retain", "sre-alias-kestrel-anvaya"), ("invalidate", "c1"),
                   ("restore", "c1"), ("delete_doc", "sre-alias-kestrel-anvaya"),
                   ("invalidate", "c2"), ("lesson", "INC-001")]
    assert store.alias_pairs() == []                                   # the link from attempt 1 was undone
    assert [a["kind"] for a in inc["applied_actions"]] == ["invalidate"]
    events = [r["event"] for r in store.list_audit("INC-001")]
    assert events == ["fix_applied", "verification", "rolled_back", "new_hypothesis", "fix_applied", "verification"]


def test_two_failed_hypotheses_hand_over_to_a_human_with_nothing_applied(env, monkeypatch):
    store.add_incident(incident())
    judge_script(monkeypatch, [False, False])
    monkeypatch.setattr(investigator, "next_hypothesis",
                        lambda inc: incident(failure_type="FRESHNESS", culprits=[C2], identity=None))
    inc = repair.apply_fix("INC-001")
    assert inc["status"] == "open" and inc["needs_human"] is True
    assert len(inc["hypotheses"]) == 2 and inc["applied_actions"] == []
    assert store.alias_pairs() == [] and ("lesson", "INC-001") not in env
    invalidated = [c[1] for c in env if c[0] == "invalidate"]
    restored = [c[1] for c in env if c[0] == "restore"]
    assert sorted(invalidated) == sorted(restored) == ["c1", "c2"]     # every write reversed


def test_verification_checks_every_answer_that_used_the_culprit(env, monkeypatch):
    store.add_incident(incident())
    store.log_answer({"run": "live", "customer_key": "kestrel", "question": "What is Kestrel's API rate limit?",
                      "answer_format": None, "used_memory_ids": ["c1"]})
    store.log_answer({"run": "live", "customer_key": "kestrel", "question": "Can Kestrel Logistics export audit logs?",
                      "answer_format": None, "used_memory_ids": ["c1"]})
    judge_script(monkeypatch, [True, True])
    inc = repair.apply_fix("INC-001")
    qs = [c["question"] for c in inc["verification"]["checks"]]
    assert qs == ["Can Kestrel Logistics export audit logs?", "What is Kestrel's API rate limit?"]   # deduplicated
    assert inc["status"] == "fixed" and inc["reask"]["answer"] == "some answer"


def test_policy_decisions(env):
    reactive = incident()
    assert repair.policy_decision(reactive, "reactive")["decision"] == "approval"          # demo default
    assert repair.policy_decision(incident(investigation={"confidence": 0.9}), "prevented")["decision"] == "auto"
    assert repair.policy_decision(incident(investigation={"confidence": 0.7}), "prevented")["decision"] == "approval"
    assert repair.policy_decision(incident(failure_type="EXECUTION"), "prevented")["decision"] == "approval"
    store.set_policy(reactive="auto")
    assert repair.policy_decision(reactive, "reactive")["decision"] == "auto"
    with pytest.raises(ValueError):
        store.set_policy(bogus=1)
