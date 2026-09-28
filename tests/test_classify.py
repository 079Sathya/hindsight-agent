from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memsre.diagnose import classify  # noqa: E402
from memsre.hs import Mem  # noqa: E402

CUST = ["customer:kestrel"]


def mem(id: str, date: str, customer: str = "kestrel") -> Mem:
    return Mem(id=id, text=f"memory {id}", date=date, tags=[f"customer:{customer}", "source:crm_notes"],
               source="crm_notes", document_id=None)


CULPRIT = mem("culprit", "2026-06-01")


def test_resolution_foreign_evidence_with_confirmed_identity():
    foreign = mem("billing", "2026-08-01", customer="anvaya")
    assert classify([CULPRIT], [foreign], ["culprit"], CUST, True) == "RESOLUTION"


def test_freshness_newer_local_fact_not_used():
    newer = mem("newer", "2026-09-08")
    assert classify([CULPRIT], [newer], ["culprit"], CUST, None) == "FRESHNESS"


def test_recall_miss_local_fact_not_newer_and_not_used():
    older = mem("older", "2026-05-01")
    assert classify([CULPRIT], [older], ["culprit"], CUST, None) == "RECALL_MISS"


def test_execution_correct_memory_was_used():
    used = mem("used", "2026-09-08")
    assert classify([CULPRIT], [used], ["culprit", "used"], CUST, None) == "EXECUTION"


def test_missing_knowledge_culprit_but_no_evidence():
    assert classify([CULPRIT], [], ["culprit"], CUST, None) == "MISSING_KNOWLEDGE"


def test_unknown_no_evidence_or_unconfirmed_foreign_evidence():
    assert classify([], [], [], CUST, None) == "UNKNOWN"
    foreign = mem("billing", "2026-08-01", customer="anvaya")
    assert classify([CULPRIT], [foreign], ["culprit"], CUST, False) == "UNKNOWN"
