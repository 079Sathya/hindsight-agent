from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memsre import config  # noqa: E402
from ui import data  # noqa: E402

AUDIT = [
    {"ts": "2026-09-29T08:53:32+00:00", "event": "investigated", "incident_id": "INC-001", "failure_type": "RESOLUTION",
     "fallback": False, "steps": 6, "llm_calls": 7},
    {"ts": "2026-09-29T08:53:33+00:00", "event": "policy_decision", "incident_id": "INC-001", "decision": "approval",
     "kind": "reactive", "confidence": 0.96, "reason": "needs approval"},
    {"ts": "2026-09-29T08:54:01+00:00", "event": "fix_applied", "incident_id": "INC-001", "attempt": 1,
     "failure_type": "RESOLUTION", "actions": [{}, {}, {}]},
    {"ts": "2026-09-29T08:54:05+00:00", "event": "verification", "incident_id": "INC-001", "passed": True,
     "reason": "2 of 2 re-asked answers consistent", "checks": [{"consistent": True}]},
    {"ts": "2026-09-29T08:54:06+00:00", "event": "verification", "incident_id": "INC-002", "passed": True,
     "reason": "no question to re-ask (prevented incident)", "checks": []},
    {"ts": "2026-09-29T08:54:07+00:00", "event": "verification", "incident_id": "INC-003", "passed": False, "reason": "1 of 2",
     "checks": [{"consistent": False}]},
    {"ts": "2026-09-29T08:54:08+00:00", "event": "rolled_back", "incident_id": "INC-003", "attempt": 1},
    {"ts": "2026-09-29T08:54:14+00:00", "event": "postmortem", "incident_id": "INC-001", "rule_signal": "email_domain",
     "rule_name": "link"},
    {"ts": "2026-09-29T08:55:03+00:00", "event": "auto_opened", "incident_id": "INC-002", "trigger": "patrol",
     "rule_id": "rule-INC-001", "confidence": 0.95, "pair": "mehta-bros+saffron"},
    {"ts": "2026-09-29T08:57:14+00:00", "event": "patrol", "incident_id": None, "trigger": "patrol", "checks": 12,
     "candidates": 3, "outcome": {"prevented": 0, "pending": 3, "dismissed": 0}},
    {"ts": "2026-09-29T08:58:00+00:00", "event": "policy_changed", "incident_id": None,
     "policy": {"prevented": "auto", "reactive": "approval", "auto_patrol_after_fix": False}},
    {"ts": "2026-09-29T08:59:20+00:00", "event": "proposal_rejected", "incident_id": None, "pair": "pinecrest+vanadium",
     "value": "nimbusit.in", "reason": "vendor"},
    {"ts": "2026-09-29T09:00:00+00:00", "event": "something_new", "incident_id": None},
]


def test_activity_maps_every_event_newest_first():
    items = data.activity(AUDIT)
    assert [i["kind"] for i in items] == [a["event"] for a in reversed(AUDIT)]
    by = {(i["kind"], i["incident_id"]): i for i in items}
    assert by[("investigated", "INC-001")]["title"] == "Investigated by the agent" and "7 LLM calls" in by[("investigated", "INC-001")]["detail"]
    assert by[("policy_decision", "INC-001")]["tone"] == "warning"
    assert by[("verification", "INC-001")]["title"] == "Verified by re-asking"
    assert by[("verification", "INC-002")]["title"] == "Linked before any wrong answer"      # skipped: no question
    assert by[("verification", "INC-003")]["tone"] == "warning"
    assert by[("rolled_back", "INC-003")]["icon"] == "undo"
    assert "Mehta Brothers" in by[("auto_opened", "INC-002")]["title"] and "Saffron Retail" in by[("auto_opened", "INC-002")]["title"]
    assert "3 awaiting approval" in by[("patrol", None)]["detail"]
    assert by[("proposal_rejected", None)]["title"] == "Pattern rejected: nimbusit.in"
    assert by[("something_new", None)]["title"] == "Something new"
    assert len(data.activity(AUDIT, limit=3)) == 3


def test_counts_and_rule_confirmations():
    incs = [{"status": "open"}, {"status": "auto-opened", "rule_id": "r1"}, {"status": "fixed"},
            {"status": "prevented", "rule_id": "r1"}, {"status": "prevented", "rule_id": "r1"}, {"status": "rejected", "rule_id": "r1"}]
    c = data.counts(incs)
    assert (c["open"], c["pending"], c["fixed"], c["prevented"], c["rejected"], c["total"]) == (2, 1, 1, 2, 1, 6)
    assert data.rule_confirmations(incs) == {"r1": 2}          # pending and rejected findings don't confirm a rule


def test_benchmark_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RESULTS_DIR", tmp_path)
    assert data.benchmark() is None
    (tmp_path / "learning_benchmark.json").write_text(json.dumps({"on": {}, "off": {}}), encoding="utf-8")
    assert data.benchmark() == {"on": {}, "off": {}}


def test_status_reports_hindsight_errors_without_calling_again():
    s = data.status([{"status": "open"}], {"prevented": "auto"}, None, "RuntimeError: HTTP 503")
    assert s["bank_ok"] is False and "HTTP 503" in s["bank_error"] and s["auto_mode"] and s["open_incidents"] == 1
    assert s["rules"] is None                                     # unavailable, not zero
    ok = data.status([], {"prevented": "approval"}, [{"id": "r"}])
    assert ok["bank_ok"] and ok["rules"] == 1 and not ok["auto_mode"]


def test_playbook_versions_snapshots_dedupe_and_reset(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    assert data.playbook_versions({"content": "v1 text", "last_refreshed_at": "t1"}, []) == [
        {"label": "v1", "at": "t1", "content": "v1 text"}]
    assert len(data.playbook_versions({"content": "v1 text", "last_refreshed_at": "t1"}, [])) == 1   # unchanged: no new version
    vs = data.playbook_versions({"content": "v2 text", "last_refreshed_at": "t2"}, [])
    assert [v["label"] for v in vs] == ["v1", "v2"] and vs[-1]["content"] == "v2 text"
    kept = data.playbook_versions(None, [])                                                   # transient error: keep them
    assert [v["content"] for v in kept] == ["v1 text", "v2 text"] and len(data._read_snaps()) == 2
    assert data.playbook_versions(None, [], fresh=True) == [] and data._read_snaps() == []   # reseed: cleared
    hist = [{"previous_content": "older", "changed_at": "t0"}, {"previous_content": "oldest", "changed_at": "t-1"}]
    vs = data.playbook_versions({"content": "now", "last_refreshed_at": "t9"}, hist)
    assert [v["content"] for v in vs] == ["oldest", "older", "now"]                          # Hindsight history wins
