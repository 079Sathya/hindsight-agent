"""A/B learning benchmark: does memory stored in Hindsight make Memory SRE measurably better?

Scenario: the four planted identity splits in a fixed order (Kestrel, Saffron, Monsoon, Neelgiri). In each episode a
customer asks a question that touches the split. If the answer is wrong, the harness plays the support rep: it
reports the answer with the correction, the investigator diagnoses it, and the fix is applied and verified.

The same scenario runs twice, each arm in its own process with its own Hindsight banks and local state:
  memory OFF  (MEMSRE_MEMORY=off): no lessons, playbooks, detection rules or feedback; every split is handled reactively.
  memory ON   (MEMSRE_MEMORY=on):  post-mortems write playbooks + detection rules, and after every verified fix the
                                   patrol runs the learned rules across the bank (policy: auto-apply prevented fixes).

Usage:  python scripts/learning_benchmark.py            # both arms, then data/results/learning_benchmark.json + chart
        python scripts/learning_benchmark.py --arm on   # one arm (used internally)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(errors="replace")

ARMS = {
    "off": {"MEMSRE_MEMORY": "off", "MAIN_BANK_ID": "memsre-bench-off", "LESSONS_BANK_ID": "memsre-bench-off-lessons"},
    "on": {"MEMSRE_MEMORY": "on", "MAIN_BANK_ID": "memsre-bench-on", "LESSONS_BANK_ID": "memsre-bench-on-lessons"},
}
TRUE_SPLITS = {frozenset(p) for p in [("kestrel", "anvaya"), ("saffron", "mehta-bros"), ("monsoon", "ruparel"),
                                       ("neelgiri", "kaveri-agro")]}
PLAN_FORMAT = "one of: starter, growth, enterprise"


def episodes() -> list[dict]:
    from memsre import catalog
    q = {x["id"]: x for x in catalog.load_questions()}
    return [
        {"name": "Kestrel", "customer": "kestrel", "question": q["Q01"]["question"], "format": q["Q01"]["format"],
         "accepted": q["Q01"]["accepted"], "correction": q["Q01"]["correction"]},
        {"name": "Saffron", "customer": "saffron", "question": q["Q05"]["question"], "format": q["Q05"]["format"],
         "accepted": q["Q05"]["accepted"], "correction": q["Q05"]["correction"]},
        {"name": "Monsoon", "customer": "monsoon", "question": "Which Lumora plan is Monsoon Trails on right now?",
         "format": PLAN_FORMAT, "accepted": ["starter"],
         "correction": "Wrong. Monsoon Trails moved to the Starter plan on 20 August 2026."},
        {"name": "Neelgiri", "customer": "neelgiri", "question": "Which Lumora plan is Neelgiri Organics on right now?",
         "format": PLAN_FORMAT, "accepted": ["growth"],
         "correction": "Wrong. Neelgiri Organics upgraded to the Growth plan on 5 September 2026."},
    ]


def run_arm(arm: str) -> dict:
    """One arm, in this process (its env selects the banks, state dir and memory switch)."""
    from memsre import agent, autonomy, config, diagnose, llm, lessons, repair, store
    from memsre.grading import grade
    from seed import seed

    config.check()
    t_arm = time.monotonic()
    seed(keep_lessons=False)
    store.set_policy(reactive="approval", prevented="auto", auto_patrol_after_fix=False)
    prevention: dict[str, dict] = {}     # customer key -> the patrol finding that prevented its split
    patrols, rows = [], []
    for n, ep in enumerate(episodes(), 1):
        t0, c0 = time.monotonic(), llm.STATS["calls"]
        ans = agent.answer(ep["customer"], ep["question"], ep["format"], run="bench")
        correct = grade(ans.short_answer, ep["accepted"])
        row = {"episode": n, "name": ep["name"], "customer": ep["customer"], "answer": ans.short_answer,
               "correct": correct, "wrong_answers_reaching_customers": 0 if correct else 1}
        if correct:
            f = prevention.get(ep["customer"])
            inv = (f or {}).get("investigation") or {}
            row.update(prevented=f is not None, investigation_steps=len(inv.get("steps") or []),
                       llm_calls=(llm.STATS["calls"] - c0) + (inv.get("llm_calls") or 0),
                       seconds=round(time.monotonic() - t0 + (inv.get("duration_s") or 0), 1),
                       handled_by=(f"patrol ({f['incident_id']})" if f else "answered correctly without a fix"))
        else:
            inc = diagnose.create_incident(ans, ep["correction"], ep["format"])
            inc = repair.apply_fix(inc["id"]) if inc["failure_type"] not in diagnose.NO_FIX_TYPES else inc
            inv = inc.get("investigation") or {}
            row.update(prevented=False, investigation_steps=len(inv.get("steps") or []),
                       llm_calls=llm.STATS["calls"] - c0, seconds=round(time.monotonic() - t0, 1),
                       handled_by=f"reactive ({inc['id']})", incident_id=inc["id"], failure_type=inc["failure_type"],
                       verified=inc["status"] == "fixed", fallback=inc.get("fallback"),
                       used_playbook_id=inv.get("used_playbook_id"), playbooks_shown=inv.get("playbooks_shown"),
                       agent_path=[s["tool"] for s in inv.get("steps") or []])
            if config.MEMORY_ENABLED and inc["status"] == "fixed":
                p0 = llm.STATS["calls"]
                report = autonomy.patrol(apply=True, trigger="after_fix")   # the policy's "after consolidation" run
                patrols.append({"after_episode": n, "checks": report["checks"], "candidates": report["candidates"],
                                "llm_calls": llm.STATS["calls"] - p0, "seconds": report["duration_s"],
                                "findings": [{k: f.get(k) for k in ("a", "b", "shared_domain", "confidence", "status",
                                                                    "incident_id")} for f in report["findings"]]})
                for f in report["findings"]:
                    if f["status"] == "prevented":
                        prevention[f["a"]] = f
        rows.append(row)
        print(f"[{arm}] episode {n} {ep['name']}: answer={ans.short_answer!r} correct={correct} -> {row['handled_by']} "
              f"steps={row['investigation_steps']} llm_calls={row['llm_calls']} {row['seconds']}s", flush=True)

    linked = {frozenset(p) for p in store.alias_pairs()}
    result = {
        "arm": arm, "memory": config.MEMORY_ENABLED, "main_bank": config.MAIN_BANK_ID,
        "lessons_bank": config.LESSONS_BANK_ID, "episodes": rows, "patrols": patrols,
        "rules_learned": [r["id"] for r in lessons.learned_rules()],
        "false_links": sorted("+".join(sorted(p)) for p in linked - TRUE_SPLITS),
        "totals": {
            "wrong_answers_reaching_customers": sum(r["wrong_answers_reaching_customers"] for r in rows),
            "prevented": sum(bool(r["prevented"]) for r in rows),
            "investigation_steps": sum(r["investigation_steps"] for r in rows),
            "llm_calls": llm.STATS["calls"], "llm_api_calls": llm.STATS["api"], "llm_cache_hits": llm.STATS["cache"],
            "seconds": round(time.monotonic() - t_arm, 1),
        },
    }
    out = ROOT / "data" / "results" / f"learning_benchmark_{arm}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def chart(off: dict, on: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [r["name"] for r in off["episodes"]]
    x = range(1, len(names) + 1)
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.2), dpi=150)
    for ax, key, title in ((left, "wrong_answers_reaching_customers", "Wrong answers reaching customers"),
                           (right, "investigation_steps", "Investigation steps")):
        for res, label, color, marker in ((off, "memory OFF", "#ef4444", "o"), (on, "memory ON", "#14b8a6", "s")):
            ys = [r[key] for r in res["episodes"]]
            ax.plot(list(x), ys, marker=marker, color=color, linewidth=2.2, markersize=8, label=label)
            for xi, yi, r in zip(x, ys, res["episodes"]):
                if res is on and r["prevented"]:
                    ax.annotate("prevented", (xi, yi), textcoords="offset points", xytext=(0, 9), ha="center",
                                fontsize=8, color=color)
        ax.set_xticks(list(x))
        ax.set_xticklabels([f"{i}. {n}" for i, n in zip(x, names)])
        ax.set_title(title)
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", alpha=0.3)
        ax.legend(frameon=False)
    left.set_yticks([0, 1])
    t_off, t_on = off["totals"], on["totals"]
    fig.suptitle(f"Memory SRE learns: wrong answers {t_off['wrong_answers_reaching_customers']} → "
                 f"{t_on['wrong_answers_reaching_customers']}, investigation steps {t_off['investigation_steps']} → "
                 f"{t_on['investigation_steps']} (memory OFF → ON, same 4 identity splits)")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arm", choices=list(ARMS))
    args = parser.parse_args()
    if args.arm:
        run_arm(args.arm)
        return
    results = {}
    for arm, env in ARMS.items():
        print(f"=== arm: memory {arm.upper()} ===", flush=True)
        child_env = {**os.environ, **env, "MEMSRE_STATE_DIR": str(ROOT / "data" / "state" / f"bench-{arm}"),
                     "PYTHONIOENCODING": "utf-8"}
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--arm", arm], env=child_env, check=True)
        results[arm] = json.loads((ROOT / "data" / "results" / f"learning_benchmark_{arm}.json").read_text(encoding="utf-8"))
    merged = {"scenario": [e["name"] for e in episodes()], "off": results["off"], "on": results["on"]}
    (ROOT / "data" / "results" / "learning_benchmark.json").write_text(json.dumps(merged, indent=2, ensure_ascii=False),
                                                                        encoding="utf-8")
    chart(results["off"], results["on"], ROOT / "docs" / "learning_curve.png")
    for arm in ("off", "on"):
        t = results[arm]["totals"]
        print(f"memory {arm.upper():3}: wrong answers {t['wrong_answers_reaching_customers']}, prevented {t['prevented']}, "
              f"steps {t['investigation_steps']}, llm_calls {t['llm_calls']}, {t['seconds']}s, "
              f"false links {results[arm]['false_links']}")
    print("Wrote data/results/learning_benchmark.json and docs/learning_curve.png")


if __name__ == "__main__":
    main()
