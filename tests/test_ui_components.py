from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memsre.hs import Mem  # noqa: E402
from ui import components as C  # noqa: E402
from ui import theme  # noqa: E402

VOID = {"br", "img", "input", "hr", "meta", "link", "source", "wbr", "col", "area", "base", "embed", "track"}
EVIL = "<script>alert(1)</script>"
MEM = {"id": "1e7247a7-523e-47f4-b9b1-164d265bbd43", "text": "Kestrel Logistics signed a 12-month Enterprise plan. | When: "
       "2026-06-01 | Involving: Kestrel Logistics", "date": "2026-06-01", "tags": ["customer:kestrel", "source:crm_notes"],
       "source": "crm_notes"}
FOREIGN = {"id": "dfc75dd8-9a2b", "text": "Anvaya changed plan from Enterprise to Growth.", "date": "2026-08-01",
           "tags": ["customer:anvaya"], "source": "billing_system"}
INV = {"agent": "investigator", "steps": [
    {"thought": "search", "tool": "recall_whole_bank", "args": {"query": "Growth"}, "result_summary": "THIS CUSTOMER'S RECORDS:\n…"},
    {"thought": "guess", "tool": "verdict_rejected", "args": {}, "result_summary": "a RESOLUTION verdict needs compare_records"},
    {"thought": "", "tool": "invalid", "args": {}, "result_summary": "the reply was not valid JSON"},
    {"thought": "compare", "tool": "compare_records", "args": {"tag_a": "customer:kestrel", "tag_b": "customer:anvaya"},
     "result_summary": "same_customer=True confidence=0.95"},
    {"thought": "done", "tool": "final", "args": {}, "result_summary": "verdict"}],
    "llm_calls": 7, "corrections": 1, "duration_s": 70.7, "used_playbook_id": "playbook-INC-001", "playbooks_shown": [],
    "used_rules": ["rule-INC-001"], "agent_failure_type": "RESOLUTION", "confidence": 0.96, "fallback": False,
    "fallback_reason": None, "memory": True}
INC = {"id": "INC-001", "created_at": "2026-09-29T08:53:32+00:00", "status": "fixed", "customer_key": "kestrel",
       "customer_name": "Kestrel Logistics", "question": "Can Kestrel export audit logs?", "wrong_answer": "Yes.",
       "wrong_short_answer": "Yes", "correction": "Wrong — Growth since August.", "culprits": [MEM], "supporting": [FOREIGN],
       "wrong_claim": "Kestrel can export audit logs", "identity": {"foreign_tag": "customer:anvaya", "foreign_name": "Anvaya",
       "same_customer": True, "confidence": 0.95, "linking_evidence": "ravi.k@anvaya.in and accounts@anvaya.in",
       "reason": "shared domain"}, "failure_type": "RESOLUTION", "root_cause": "Stored under another name.",
       "blast_radius": {"answers_affected": 2, "answer_ids": ["ANS-0001", "ANS-0002"]},
       "recommended_fix": ["Link them", "Retain an identity link"], "investigation": INV,
       "applied_actions": [{"kind": "alias", "a": "kestrel", "b": "anvaya"},
                           {"kind": "retain_doc", "bank": "b", "document_id": "sre-alias-kestrel-anvaya"},
                           {"kind": "invalidate", "bank": "b", "memory_id": "1e7247a7-523e"}],
       "reask": {"answer": "No, Growth has no audit export.", "short_answer": "No", "used_memory_ids": [], "used_memories": []},
       "verification": {"passed": True, "skipped": False, "attempt": 1, "reason": "2 of 2 re-asked answers consistent",
                        "checks": [{"question": "Q1?", "short_answer": "No", "consistent": True, "reason": "matches"},
                                   {"question": "Q2?", "short_answer": "Yes", "consistent": False, "reason": "still wrong"}]},
       "policy": {"decision": "approval", "kind": "reactive", "confidence": 0.96, "reason": "policy requires approval"},
       "hypotheses": [{"attempt": 1, "failure_type": "FRESHNESS", "culprit_ids": ["x"], "foreign_tag": None,
                       "failed_checks": [{"question": "Q?", "short_answer": "Yes", "reason": "r"}]}], "needs_human": False}
PREVENTED = {**INC, "id": "INC-004", "status": "auto-opened", "question": None, "wrong_answer": None, "correction": None,
             "trigger": "patrol", "rule_id": "rule-INC-001", "shared_value": "kaveriagro.co.in", "applied_actions": [],
             "reask": None, "verification": None, "hypotheses": [],
             "policy": {"decision": "approval", "kind": "prevented", "confidence": 0.95, "reason": "needs approval"}}
FINDING = {"a": "saffron", "b": "mehta-bros", "name_a": "Saffron Retail", "name_b": "Mehta Brothers", "value": "mehtabros.co.in",
           "shared_domain": "mehtabros.co.in", "rule_id": "rule-INC-001", "same_customer": True, "confidence": 0.95,
           "linking_evidence": "a@mehtabros.co.in", "reason": "shared domain", "status": "prevented", "incident_id": "INC-002",
           "investigation": {"steps": [{"tool": "compare_records"}, {"tool": "final"}]}}


class _Balance(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
        else:
            self.stack.pop()


def balanced(html: str) -> bool:
    p = _Balance()
    p.feed(html)
    p.close()
    assert not p.errors and not p.stack, (p.errors, p.stack, html[:300])
    return True


BUILDERS = {
    "hero": lambda: C.hero({"bank_ok": True, "bank_id": "bank", "auto_mode": True, "open_incidents": 1, "rules": 2}),
    "hero_down": lambda: C.hero({"bank_ok": False, "bank_error": EVIL, "auto_mode": False, "open_incidents": 0, "rules": 0}),
    "metric": lambda: C.metric_card({"label": "Accuracy", "value": 60, "value2": 100, "suffix": "%", "note": "n"}),
    "metric_none": lambda: C.metric_card({"label": "Accuracy", "value": None, "note": "n"}),
    "metrics": lambda: C.metric_cards([{"label": "A", "value": 1}, {"label": "B", "value": 2}]),
    "answer_reveal": lambda: C.answer_card({"customer_name": "Kestrel Logistics", "question": "Q?", "answer": "Yes,\nthey can.",
                                            "short_answer": "Yes", "answer_id": "ANS-1", "memories": 1, "watch": [FINDING]}, True),
    "answer_static": lambda: C.answer_card({"customer_name": "", "question": "Q?", "answer": "A", "answer_id": "ANS-1"}, False),
    "mems_dicts": lambda: C.memory_cards([MEM, FOREIGN], title="Memories"),
    "mems_objects": lambda: C.memory_cards([Mem(**MEM, document_id="evt-1"), Mem(**FOREIGN, document_id="sre-alias-x")]),
    "mems_empty": lambda: C.memory_cards([]),
    "culprit_struck": lambda: C.memory_card(MEM, "culprit", own_tag="customer:kestrel", struck=True, animate=True, note="n"),
    "evidence": lambda: C.memory_card(FOREIGN, "evidence", own_tag="customer:kestrel", foreign_tags={"customer:anvaya"}),
    "customer_panel": lambda: C.customer_panel("Kestrel", "customer:kestrel", ["customer:kestrel"], ["Anvaya"], {"Incidents": 1}),
    "watch_panel": lambda: C.watch_panel(1, True),
    "watch_panel_empty": lambda: C.watch_panel(0, False),
    "timeline": lambda: C.trace_timeline(INV, animate=True),
    "timeline_fallback": lambda: C.trace_timeline({**INV, "fallback": True, "fallback_reason": "no verdict"}),
    "timeline_empty": lambda: C.trace_timeline({}),
    "trace_header": lambda: C.trace_header("Investigating", "sub", live=True, stats=["1 step"], badges=["Applied rule r"]),
    "cand": lambda: C.patrol_candidate_header({"a": "saffron", "b": "mehta-bros", "value": "mehtabros.co.in", "rule_id": "r"}),
    "outcome": lambda: C.patrol_outcome(FINDING),
    "outcome_dismissed": lambda: C.patrol_outcome({**FINDING, "status": "dismissed", "incident_id": None}),
    "incident_card": lambda: C.incident_card(INC, True),
    "incident_card_prevented": lambda: C.incident_card(PREVENTED, False),
    "case_header": lambda: C.case_header(INC),
    "case_header_prevented": lambda: C.case_header(PREVENTED),
    "www": lambda: C.what_went_wrong(INC),
    "www_prevented": lambda: C.what_went_wrong(PREVENTED),
    "identity": lambda: C.identity_link(INC),
    "identity_diff": lambda: C.identity_link({**INC, "identity": {**INC["identity"], "same_customer": False}}),
    "identity_none": lambda: C.identity_link({**INC, "identity": None}),
    "blast": lambda: C.blast_radius(2, ["ANS-0001"]),
    "root": lambda: C.root_cause_card(INC),
    "plan": lambda: C.fix_plan(INC),
    "plan_nofix": lambda: C.fix_plan({**INC, "recommended_fix": []}),
    "healed": lambda: C.healed_banner(INC, True),
    "healed_prevented": lambda: C.healed_banner({**PREVENTED, "status": "prevented"}, False),
    "verification": lambda: C.verification(INC["verification"], True),
    "rollback": lambda: C.rollback_cards(INC["hypotheses"], True),
    "before_after": lambda: C.before_after(INC),
    "actions": lambda: C.applied_actions(INC["applied_actions"] + [{"kind": "other"}]),
    "approval": lambda: C.approval_card(PREVENTED),
    "finding": lambda: C.finding_card(FINDING),
    "finding_dismissed": lambda: C.finding_card({**FINDING, "status": "dismissed", "investigation": None}),
    "proposal": lambda: C.proposal_card(FINDING, "pending"),
    "feed": lambda: C.activity_feed([{"ts": "2026-09-29T08:53:32+00:00", "icon": "bot", "tone": "accent", "title": "T",
                                      "detail": "D", "incident_id": "INC-001"}]),
    "feed_empty": lambda: C.activity_feed([]),
    "rules": lambda: C.rule_cards([{"id": "rule-INC-001", "signal_type": "email_domain", "text": "rule"}], {"rule-INC-001": 2}),
    "rules_empty": lambda: C.rule_cards([], {}),
    "exceptions": lambda: C.exception_cards([{"value": "nimbusit.in", "pair": "a+b", "signal_type": "email_domain", "text": "t"}]),
    "observations": lambda: C.observations([{"text": "t", "proof_count": 3}]),
    "diff": lambda: C.playbook_diff("a\nb", "a\nc\nd", "v1", "v2"),
    "diff_same": lambda: C.playbook_diff("a", "a", "v1", "v2"),
    "policy": lambda: C.policy_summary({"auto_apply_min_confidence": 0.85, "reactive": "approval", "prevented": "auto",
                                        "auto_patrol_after_fix": True}),
    "section": lambda: C.section_header("Title", "sub", "radar", C.chip("x")),
    "empty": lambda: C.empty_state("siren", "T", "B", "H"),
}


EMPTY_BY_DESIGN = {"identity_none"}   # nothing to show → the builder returns ""


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_builders_return_balanced_html(name):
    html = BUILDERS[name]()
    assert isinstance(html, str)
    assert (html == "") if name in EMPTY_BY_DESIGN else bool(html.strip())
    assert balanced(html)


@pytest.mark.parametrize("state", ["thinking", "running", "done", "rejected", "invalid", "error", "verdict", "accepted", "fallback"])
def test_trace_step_every_state(state):
    html = C.trace_step({"tool": "compare_records", "thought": "t", "args": {"tag_a": "a"}, "result_summary": "r"}, 3, state,
                        last=True, verdict={"failure_type": "RESOLUTION", "confidence": 0.9})
    assert balanced(html) and f"ms-step {state}" in html and ">04<" in html


@pytest.mark.parametrize("kind", ["answer", "cards", "timeline", "chart", "line"])
def test_skeletons(kind):
    assert balanced(C.skeleton(kind, 2)) and "ms-skel" in C.skeleton(kind, 2)


def test_user_text_is_escaped_everywhere():
    evil_mem = {**MEM, "text": EVIL, "tags": ["customer:" + EVIL]}
    evil_inc = {**INC, "customer_name": EVIL, "question": EVIL, "wrong_answer": EVIL, "correction": EVIL, "culprits": [evil_mem],
                "identity": {**INC["identity"], "foreign_name": EVIL, "linking_evidence": EVIL + " x@y.io", "reason": EVIL},
                "root_cause": EVIL, "recommended_fix": [EVIL]}
    outputs = [C.memory_card(evil_mem, "culprit"), C.case_header(evil_inc), C.what_went_wrong(evil_inc), C.identity_link(evil_inc),
               C.root_cause_card(evil_inc), C.fix_plan(evil_inc), C.incident_card(evil_inc, False),
               C.answer_card({"customer_name": EVIL, "question": EVIL, "answer": EVIL, "answer_id": EVIL}, True),
               C.trace_step({"tool": EVIL, "thought": EVIL, "args": {EVIL: EVIL}, "result_summary": EVIL}, 0, "done"),
               C.hero({"bank_ok": False, "bank_error": EVIL}), C.exception_cards([{"value": EVIL, "text": EVIL}]),
               C.activity_feed([{"title": EVIL, "detail": EVIL, "ts": "x"}])]
    for html in outputs:
        assert "<script>" not in html and "&lt;script&gt;" in html


def test_split_memory_text_and_ids():
    fact, meta = C.split_memory_text(MEM["text"])
    assert fact == "Kestrel Logistics signed a 12-month Enterprise plan." and meta == {"When": "2026-06-01", "Involving": "Kestrel Logistics"}
    assert C.split_memory_text("A | budget cuts")[0] == "A · budget cuts"
    assert C.short_id("1e7247a7-523e") == "1e7247a7" and C.short_id(None) == ""


def test_time_ago_and_plural():
    now = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    assert C.time_ago("2026-09-29T11:59:50+00:00", now) == "just now"
    assert C.time_ago("2026-09-29T11:57:00+00:00", now) == "3m ago"
    assert C.time_ago("2026-09-29T09:00:00Z", now) == "3h ago"
    assert C.time_ago("2026-09-20T09:00:00+00:00", now) == "Sep 20"
    assert C.time_ago(None) == "" and C.time_ago("not a date") == "not a date"
    assert C.plural(1, "step") == "1 step" and C.plural(3, "LLM call") == "3 LLM calls"


def test_trace_memory_badges():
    assert C.trace_memory_badges(INV) == ["Used playbook from INC-001", "Applied rule-INC-001"]
    assert C.trace_memory_badges({"fallback": True}) == ["Fell back to the fixed pipeline"]
    assert C.trace_memory_badges({}) == []


def test_timeline_maps_step_states():
    html = C.trace_timeline(INV)
    for state in ("ms-step done", "ms-step rejected", "ms-step invalid", "ms-step accepted"):
        assert state in html
    assert "96% confidence" in html and "7 LLM calls" in html and "5 steps" in html


def test_status_and_failure_labels():
    assert "Awaiting approval" in C.status_pill("auto-opened") and "ms-tone-warning" in C.status_pill("auto-opened")
    assert "ms-tone-success" in C.status_pill("prevented")
    assert "ms-ft-RESOLUTION" in C.failure_badge("RESOLUTION") and "ms-ft-UNKNOWN" in C.failure_badge("NOT_A_TYPE")


def test_policy_chip_follows_incident_state():
    assert "awaiting approval" in C.policy_chip({**INC, "status": "open"}).lower()
    assert "approved by a human" in C.policy_chip(INC).lower()                         # fixed after an approval decision
    assert "auto-applied" in C.policy_chip({**INC, "policy": {"decision": "auto", "confidence": 0.9}}).lower()


def test_every_icon_used_exists_in_the_theme():
    src = Path(C.__file__).read_text(encoding="utf-8") + Path(C.__file__).with_name("live.py").read_text(encoding="utf-8")
    used = set(re.findall(r'icon\("([a-z-]+)"', src)) | set(re.findall(r'icon_name="([a-z-]+)"', src))
    used |= set(C.TOOL_ICONS.values()) | {ic for _, ic in C.SOURCES.values()} | {v for v in C._STATE_ICONS.values() if v}
    used |= {ic for ic, _ in C._FINDING_ICONS.values()}
    app = (Path(C.__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
    used |= set(re.findall(r'C\.(?:icon|empty_state|section_header)\("([a-z-]+)"', app))
    used |= set(re.findall(r'C\.section_header\([^)]*?,\s*"([a-z-]+)"', app))
    missing = sorted(u for u in used if u not in theme.ICONS)
    assert not missing, missing


def test_stylesheet_survives_the_sanitizer():
    css = theme.css()
    assert re.search(r"<[A-Za-z/!?]", css) is None           # DOMPurify drops a <style> that contains one
    assert "@property --n" in css and "prefers-reduced-motion" in css
    for name in theme.ICONS:
        assert f".ms-i-{name}{{" in css


def test_clean_meta_and_new_trace_pieces():
    assert C.clean_meta("Rejected. | When: 2026-09-29 | Involving: SRE reviewer | The agent erred.") == "Rejected. · The agent erred."
    assert C.clean_meta('Invalidate: "X signed. | When: 2026-06-01 | Involving: X"') == 'Invalidate: "X signed."'
    for html in (C.trace_divider("Next hypothesis"), C.trace_folded(3, earlier=True), C.trace_folded(1), C.trace_note("n"),
                 C.trace_pipeline_summary(INC)):
        assert balanced(html)
    assert "+3 earlier steps" in C.trace_folded(3, earlier=True) and "1 step · done" in C.trace_folded(1)


def test_state_aware_copy():
    assert "Auto mode is now on" in C.approval_card(PREVENTED, {"prevented": "auto"})
    assert "asks a human" in C.approval_card(PREVENTED, {"prevented": "approval"})
    assert "ms-finding prevented" in C.finding_card({**FINDING, "status": "pending"}, live_status="prevented")
    assert "zero" in C.blast_radius(0, []) and "no customer saw a wrong answer" in C.blast_radius(0, [])
    assert "Applied rule-INC-001" in C.trace_memory_badges(INV)[1]
    feed = C.activity_feed([{"ts": "2026-09-29T09:00:00+00:00", "title": "new"}, {"ts": "2026-09-29T08:00:00+00:00", "title": "old"}],
                           seen_ts="2026-09-29T08:30:00+00:00")
    assert feed.count("ms-feed-item anim") == 1
    assert "Awaiting approval" not in C.case_header({**INC, "status": "open"}).split("ms-case-meta")[1]
