"""Before/after evaluation on the 20 support questions.  Usage: python scripts/eval.py [--no-reset]"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(errors="replace")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from memsre import agent, catalog, config, repair  # noqa: E402
from memsre.diagnose import NO_FIX_TYPES, create_incident  # noqa: E402
from memsre.grading import grade  # noqa: E402
from seed import seed  # noqa: E402  (scripts/ is on sys.path when run as a script)


def run(no_reset: bool = False) -> dict:
    config.check()
    if not no_reset:
        seed(keep_lessons=False)
    questions = catalog.load_questions()

    print("\n=== BEFORE ===", flush=True)
    before = {}
    for q in questions:
        ans = agent.answer(q["customer"], q["question"], q["format"], run="eval-before")
        before[q["id"]] = (ans.short_answer, grade(ans.short_answer, q["accepted"]))
        print(f"{q['id']}  {'OK ' if before[q['id']][1] else 'BAD'}  {ans.short_answer!r}", flush=True)

    print("\n=== REPAIR ===", flush=True)
    fixed_by: dict[str, str | None] = {}
    incidents: list[dict] = []
    last_incident_id = None
    for q in questions:
        if before[q["id"]][1]:
            continue
        ans = agent.answer(q["customer"], q["question"], q["format"], run="eval-repair")
        if grade(ans.short_answer, q["accepted"]):
            fixed_by[q["id"]] = last_incident_id
            print(f"{q['id']}  now correct on re-ask (fixed by {last_incident_id})", flush=True)
            continue
        try:
            inc = create_incident(ans, q["correction"], q["format"])
            incidents.append(inc)
            last_incident_id = inc["id"]
            print(f"{q['id']}  {inc['id']} {inc['failure_type']}", flush=True)
            if inc["failure_type"] in NO_FIX_TYPES:
                continue
            repair.apply_fix(inc["id"])
            again = repair.reask(inc["id"])["reask"]
        except Exception as e:  # one failed repair must not abort a 20-minute run
            print(f"{q['id']}  repair failed: {e}", flush=True)
            continue
        if grade(again["short_answer"], q["accepted"]):
            fixed_by[q["id"]] = inc["id"]
        print(f"      fix applied; re-ask -> {again['short_answer']!r} "
              f"({'fixed' if q['id'] in fixed_by else 'still wrong'})", flush=True)

    print("\n=== AFTER ===", flush=True)
    rows = []
    for q in questions:
        ans = agent.answer(q["customer"], q["question"], q["format"], run="eval-after")
        ok = grade(ans.short_answer, q["accepted"])
        rows.append({
            "id": q["id"], "customer": q["customer"], "question": q["question"], "defect": q["defect"],
            "before_correct": before[q["id"]][1], "before_short": before[q["id"]][0],
            "after_correct": ok, "after_short": ans.short_answer, "fixed_by": fixed_by.get(q["id"]),
        })

    n = len(rows)
    fixed_counts = Counter(r["fixed_by"] for r in rows if r["fixed_by"])
    results = {
        "before_accuracy": round(100 * sum(r["before_correct"] for r in rows) / n, 1),
        "after_accuracy": round(100 * sum(r["after_correct"] for r in rows) / n, 1),
        "n": n,
        "questions": rows,
        "incidents": [{"id": i["id"], "failure_type": i["failure_type"], "customer": i["customer_key"],
                       "answers_fixed": fixed_counts.get(i["id"], 0)} for i in incidents],
        "by_type": dict(Counter(i["failure_type"] for i in incidents)),
    }
    for path in (config.RESULTS_DIR / "eval_latest.json",
                 config.RESULTS_DIR / f"eval_{datetime.now().strftime('%Y%m%d_%H%M')}.json"):
        path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    chart(results)
    summary(results)
    return results


def chart(results: dict) -> Path:
    fig, (left, right) = plt.subplots(1, 2, figsize=(10, 4), dpi=150)
    labels = ["Before Memory SRE", "After Memory SRE"]
    values = [results["before_accuracy"], results["after_accuracy"]]
    bars = left.bar(labels, values, color=["#c0504d", "#4f81bd"])
    left.bar_label(bars, labels=[f"{v:.0f}%" for v in values], label_type="center", color="white",
                   fontsize=14, fontweight="bold")
    left.set_ylim(0, 100)
    left.set_ylabel("Accuracy (%)")
    left.set_title("Accuracy")

    incs = results["incidents"]
    if incs:
        names = [f"{i['id']} · {i['failure_type']}" for i in incs]
        counts = [i["answers_fixed"] for i in incs]
        hbars = right.barh(names, counts, color="#9bbb59")
        right.bar_label(hbars, padding=3)
        right.invert_yaxis()
        right.set_xlim(0, max(counts + [1]) + 1)
    else:
        right.text(0.5, 0.5, "No incidents", ha="center", va="center", transform=right.transAxes)
        right.set_yticks([])
    right.set_xlabel("Wrong answers fixed")
    right.set_title("Wrong answers fixed per incident")

    fig.suptitle(f"Memory SRE — support-agent accuracy on {results['n']} questions")
    fig.tight_layout()
    out = config.DOCS_DIR / "before_after.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def summary(results: dict) -> None:
    print("\n=== SUMMARY ===")
    print(f"{'id':4}  {'customer':10}  {'before':14}  {'after':14}  fixed_by")
    for r in results["questions"]:
        b = f"{'OK ' if r['before_correct'] else 'BAD'} {r['before_short'][:10]}"
        a = f"{'OK ' if r['after_correct'] else 'BAD'} {r['after_short'][:10]}"
        print(f"{r['id']:4}  {r['customer']:10}  {b:14}  {a:14}  {r['fixed_by'] or ''}")
    print(f"\nIncidents: {[(i['id'], i['failure_type'], i['answers_fixed']) for i in results['incidents']]}")
    print(f"Accuracy: before {results['before_accuracy']}%  ->  after {results['after_accuracy']}%  (n={results['n']})")
    print(f"Wrote {config.RESULTS_DIR / 'eval_latest.json'} and {config.DOCS_DIR / 'before_after.png'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-reset", action="store_true", help="do not re-seed the memory bank first")
    run(no_reset=parser.parse_args().no_reset)
