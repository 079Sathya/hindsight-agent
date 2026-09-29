from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memsre import config, hs, lessons, store  # noqa: E402

MAIN_TEXTS = {
    "customer:saffron": ["Workspace admin contact for Saffron Retail is it-desk@mehtabros.co.in."],
    "customer:mehta-bros": ["Mehta Brothers Trading LLP upgraded to Enterprise; billing contact accounts@mehtabros.co.in."],
    "customer:pinecrest": ["Ticket #4231 from helpdesk@nimbusit.in (Pinecrest Hospitals)."],
    "customer:vanadium": ["Ticket #4372 from helpdesk@nimbusit.in (Vanadium Energy)."],
    "customer:quartz": ["Contact vikram@quartzmobility.in."],
}
RULE_UNIT = {"document_id": "rule-INC-001", "fact_type": "world", "text": "Detection rule: records sharing an email domain.",
             "tags": ["sre:rule", "rule:email_domain", "type:resolution"], "mentioned_at": "2026-09-29"}


def exception_unit(value, pair):
    return {"document_id": f"exception-{pair}", "fact_type": "world", "text": f"Rejected: shared email_domain '{value}'.",
            "tags": ["sre:exception", "signal:email_domain", f"value:{value}", f"pair:{pair}"], "mentioned_at": "2026-09-29"}


@pytest.fixture
def bank(tmp_path, monkeypatch):
    for name in ("ALIASES_FILE", "INCIDENTS_FILE", "ANSWERS_FILE", "TAG_NAMES_FILE", "AUDIT_FILE", "POLICY_FILE"):
        monkeypatch.setattr(store, name, tmp_path / getattr(store, name).name)
    store.reset_state()
    store.set_tag_names({"customer:saffron": "Saffron Retail", "customer:mehta-bros": "Mehta Brothers Trading LLP",
                         "customer:pinecrest": "Pinecrest Hospitals", "customer:vanadium": "Vanadium Energy",
                         "customer:quartz": "Quartz Mobility"})
    state = {"lessons": [], "list_calls": 0, "identity": 0}

    def list_memories(bank_id, type=None, q=None, state_=None, limit=100, tags=None, **kw):
        if bank_id == config.LESSONS_BANK_ID:
            return [u for u in state["lessons"] if not tags or set(tags) & set(u["tags"])]
        state["list_calls"] += 1
        return [{"id": f"{t}-{n}", "fact_type": "world", "text": x, "tags": [t]}
                for t in (tags or []) for n, x in enumerate(MAIN_TEXTS.get(t, []))]

    monkeypatch.setattr(hs, "list_memories", list_memories)
    monkeypatch.setattr(hs, "recall", lambda *a, **k: [])   # no network in tests
    monkeypatch.setattr(hs, "list_tags", lambda bank_id, q: list(MAIN_TEXTS) if bank_id == config.MAIN_BANK_ID else [])

    def identity_check(a, b, lessons_block=""):
        state["identity"] += 1
        return {"foreign_tag": f"customer:{b}", "foreign_name": b, "same_customer": True, "confidence": 0.95,
                "linking_evidence": "shared domain", "reason": "shared company domain"}
    monkeypatch.setattr(lessons, "identity_check", identity_check)
    monkeypatch.setattr(config, "MEMORY_ENABLED", True)
    return state


def pairs(items):
    return {frozenset((c["a"], c["b"])) for c in items}


def test_empty_lessons_bank_runs_zero_checks_and_makes_zero_proposals(bank):
    assert lessons.learned_rules() == []
    assert lessons.rule_candidates() == (0, [])
    assert lessons.proactive_identity_scan() == []
    assert bank["list_calls"] == 0 and bank["identity"] == 0      # nothing hard-coded runs without a learned rule


def test_learned_rule_drives_the_checks(bank):
    bank["lessons"] = [RULE_UNIT]
    checks, cands = lessons.rule_candidates()
    assert checks == len(MAIN_TEXTS)                               # one check per customer record, for the one rule
    assert pairs(cands) == {frozenset(("saffron", "mehta-bros")), frozenset(("pinecrest", "vanadium"))}
    saffron = next(c for c in cands if "saffron" in (c["a"], c["b"]))
    assert saffron["value"] == "mehtabros.co.in" and saffron["rule_id"] == "rule-INC-001"
    assert pairs(lessons.proactive_identity_scan()) == pairs(cands)


def test_rejected_pattern_is_not_proposed_again(bank):
    bank["lessons"] = [RULE_UNIT]
    assert frozenset(("pinecrest", "vanadium")) in pairs(lessons.proactive_identity_scan())
    bank["lessons"].append(exception_unit("nimbusit.in", "pinecrest+vanadium"))   # what reject_proposal retains
    proposals = lessons.proactive_identity_scan()
    assert pairs(proposals) == {frozenset(("saffron", "mehta-bros"))}
    guidance = lessons.investigation_guidance("any symptom")
    assert "nimbusit.in" in guidance["rejected_values"] and "REJECTED PATTERNS" in guidance["text"]


def test_reject_proposal_retains_an_exception(bank, monkeypatch):
    retained = []
    monkeypatch.setattr(hs, "retain_event", lambda bank_id, **k: retained.append((bank_id, k["document_id"], k["tags"])))
    monkeypatch.setattr(lessons, "refresh_playbook_model", lambda: None)
    out = lessons.reject_proposal({"a": "pinecrest", "b": "vanadium", "signal_type": "email_domain",
                                   "shared_domain": "nimbusit.in"}, "shared IT vendor, not the customer's domain")
    assert out["value"] == "nimbusit.in"
    bank_id, doc, tags = retained[0]
    assert bank_id == config.LESSONS_BANK_ID and doc == "exception-pinecrest+vanadium"
    assert {"sre:exception", "value:nimbusit.in", "pair:pinecrest+vanadium"} <= set(tags)


def test_memory_off_disables_rules_and_guidance(bank, monkeypatch):
    bank["lessons"] = [RULE_UNIT]
    monkeypatch.setattr(config, "MEMORY_ENABLED", False)
    assert lessons.learned_rules() == [] and lessons.rule_candidates() == (0, [])
    assert lessons.investigation_guidance("x")["text"] == "" and lessons.playbook() is None
