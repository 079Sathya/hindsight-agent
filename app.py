"""Memory SRE for Hindsight: Streamlit UI. Business logic lives in memsre/; this file only calls it (see API.md)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from memsre import agent, catalog, config, diagnose, lessons, repair, store
from memsre.grading import normalize

st.set_page_config(page_title="Memory SRE", page_icon="🩺", layout="wide")

BADGE_COLORS = {"RESOLUTION": "orange", "FRESHNESS": "blue", "RECALL_MISS": "violet",
                "EXECUTION": "gray", "MISSING_KNOWLEDGE": "red", "UNKNOWN": "gray"}


def call(fn, *args, **kwargs):
    """Every backend call goes through here: on failure show st.error(str(e)) and return None."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 - the UI must never crash on a backend error
        st.error(str(e))
        return None


def flash(kind: str, message: str) -> None:
    """Show a message after the st.rerun() that follows an incident action."""
    st.session_state["flash"] = (kind, message)


def show_flash() -> None:
    if msg := st.session_state.pop("flash", None):
        getattr(st, msg[0])(msg[1])


def memory_table(mems) -> None:
    rows = [{"id": m["id"][:8] if isinstance(m, dict) else m.id[:8],
             "date": m["date"] if isinstance(m, dict) else m.date,
             "source": m["source"] if isinstance(m, dict) else m.source,
             "text": m["text"] if isinstance(m, dict) else m.text} for m in mems]
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.caption("No memories were used.")


def learning_curve_figure(points: list[dict]) -> go.Figure:
    """x = incidents in order, y = wrong answers customers saw before the fix; reactive vs prevented; lesson marker."""
    xs = list(range(1, len(points) + 1))
    colors = ["#f59e0b" if p["kind"] == "reactive" else "#22c55e" for p in points]
    fig = go.Figure(go.Scatter(
        x=xs, y=[p["wrong_answers"] for p in points], mode="lines+markers+text",
        line={"color": "#94a3b8", "width": 2}, marker={"size": 14, "color": colors, "line": {"width": 2, "color": "white"}},
        text=[f"{p['wrong_answers']} wrong" if p["kind"] == "reactive" else "prevented" for p in points],
        textposition="top center",
        customdata=[[p["id"], p["customer_name"], p["kind"]] for p in points],
        hovertemplate="%{customdata[0]} · %{customdata[1]}<br>%{customdata[2]}: %{y} wrong answers<extra></extra>"))
    for x, p in zip(xs, points):
        if p["lesson_learned"]:
            fig.add_vline(x=x + 0.5, line={"dash": "dash", "color": "#a78bfa"})
            fig.add_annotation(x=x + 0.5, y=max(pp["wrong_answers"] for pp in points) or 1, text="Lesson learned",
                               showarrow=False, xanchor="left", yanchor="bottom", font={"color": "#a78bfa"})
    fig.update_layout(
        height=320, margin={"l": 40, "r": 20, "t": 30, "b": 40}, showlegend=False,
        xaxis={"tickmode": "array", "tickvals": xs, "ticktext": [f"{p['id']}<br>{p['customer_name']}" for p in points]},
        yaxis={"title": "Wrong answers customers saw", "rangemode": "tozero", "dtick": 1})
    return fig


for k, v in {"last_answer": None, "show_report": False, "selected_incident": None,
             "proposals": None, "reported": {}}.items():
    st.session_state.setdefault(k, v)

st.title("Memory SRE for Hindsight")
st.caption("Find the memory that made your agent wrong — and fix it.")

try:
    config.check()
except Exception as e:
    st.error(str(e))
    st.stop()

tab_console, tab_incidents, tab_health = st.tabs(["Support Console", "Incidents", "Memory Health"])

# ---------------------------------------------------------------- Tab 1: Support Console
with tab_console:
    customers = call(catalog.load_customers) or []
    names = {c["key"]: c["name"] for c in customers}
    key = st.selectbox("Customer", list(names), format_func=names.get, key="customer")

    samples = [q for q in (call(catalog.load_questions) or []) if q["customer"] == key][:4]
    for col, q in zip(st.columns(4), samples):
        col.button(q["question"], key=f"sample-{q['id']}", width="stretch",
                   on_click=lambda text=q["question"]: st.session_state.update(question=text))

    question = st.text_input("Question", key="question")
    if st.button("Ask", type="primary", key="ask"):
        if not question.strip():
            st.warning("Type a question first.")
        else:
            with st.spinner("Asking the support agent…"):
                ans = call(agent.answer, key, question.strip())
                if ans is not None:
                    st.session_state["last_answer"] = ans
                    st.session_state["show_report"] = False

    ans = st.session_state["last_answer"]
    if ans is not None:
        with st.container(border=True):
            st.markdown(f"**{names.get(ans.customer_key, ans.customer_key)}** — {ans.question}")
            st.markdown(ans.answer)
            st.caption(f"Short answer: {ans.short_answer or '—'} · {ans.answer_id}")
        st.markdown("**Memories used**")
        memory_table(ans.used_memories)

        st.markdown("Was this correct?")
        up, down, _ = st.columns([1, 1, 6])
        if up.button("👍 Correct", key="thumbs-up"):
            st.toast("Logged")
        if down.button("👎 Wrong", key="thumbs-down"):
            st.session_state["show_report"] = True

        if st.session_state["show_report"]:
            correction = st.text_area("What's actually true? (paste what the customer told you)", key="correction")
            if st.button("Report & diagnose", type="primary", key="report"):
                if not correction.strip():
                    st.warning("Paste what the customer told you first.")
                else:
                    inc = None
                    if ans.answer_id in st.session_state["reported"]:   # already diagnosed (e.g. a double click)
                        inc = call(store.get_incident, st.session_state["reported"][ans.answer_id])
                    if inc is None:
                        with st.spinner("Memory SRE is diagnosing…"):
                            inc = call(diagnose.create_incident, ans, correction.strip())
                            if inc is not None:
                                st.session_state["reported"][ans.answer_id] = inc["id"]
                    if inc is not None:
                        st.session_state["selected_incident"] = inc["id"]   # the Incidents tab opens on it
                        st.success(f"{inc['id']} created — type {inc['failure_type']}. Open the Incidents tab.")

# ---------------------------------------------------------------- Tab 2: Incidents
with tab_incidents:
    incidents = call(store.list_incidents) or []
    if not incidents:
        st.info("No incidents yet.")
    else:
        ids = [i["id"] for i in incidents]
        labels = {i["id"]: f"{i['id']} · {i['failure_type']} · {i['customer_name']} · {i['status']}" for i in incidents}
        # selected_incident is the source of truth. Pushing it into the widget on every run makes Streamlit send the
        # current label (the status in it changes after Apply/Undo), so the browser never holds a stale label.
        if st.session_state["selected_incident"] not in ids:
            st.session_state["selected_incident"] = ids[0]
        st.session_state["incident_select"] = st.session_state["selected_incident"]
        selected = st.selectbox(
            "Incident", ids, format_func=labels.get, key="incident_select",
            on_change=lambda: st.session_state.update(selected_incident=st.session_state["incident_select"]))
        inc = call(store.get_incident, selected)
        if inc is not None:
            show_flash()
            ftype, status = inc["failure_type"], inc["status"]
            identity = inc.get("identity")

            # 1. Header
            st.markdown(f"### {inc['id']} · {status} &nbsp; :{BADGE_COLORS.get(ftype, 'gray')}-background[**{ftype}**]")

            # 2. What went wrong
            st.markdown("#### What went wrong")
            if inc["question"] is None:
                st.info("Found by the proactive identity scan — no wrong answer was given.")
            else:
                st.markdown(f"**Question:** {inc['question']}")
                st.markdown(f"**Agent's answer:** {inc['wrong_answer']}")
                st.markdown(f"**Correction:** {inc['correction']}")

            # 3. Culprit memory
            st.markdown("#### Culprit memory")
            if inc["culprits"]:
                for m in inc["culprits"]:
                    with st.container(border=True):
                        st.markdown(m["text"])
                        st.caption(f"{m['date'] or 'no date'} · {m['source'] or 'unknown source'} · id {m['id']}")
                st.markdown(f"**Wrong claim:** {inc['wrong_claim']}")
            else:
                st.caption("No culprit memory identified.")

            # 4. Contradicting evidence (foreign customer tag highlighted)
            st.markdown("#### Contradicting evidence")
            own_tag = f"customer:{inc['customer_key']}"
            foreign = {identity["foreign_tag"]} if identity else set()
            if inc["supporting"]:
                for m in inc["supporting"]:
                    tags = " ".join(
                        f":orange-background[**{t}**]" if (t in foreign or (t.startswith("customer:") and t != own_tag))
                        else f"`{t}`" for t in m["tags"])
                    with st.container(border=True):
                        st.markdown(m["text"])
                        st.caption(f"{m['date'] or 'no date'} · {m['source'] or 'unknown source'} · id {m['id']}")
                        st.markdown(tags)
            else:
                st.caption("No contradicting evidence found.")

            # Agent trace (investigator)
            inv = inc.get("investigation")
            if inv:
                label = (f"Investigation trace · {len(inv['steps'])} steps · {inv['llm_calls']} LLM calls · "
                         f"{inv['duration_s']}s" + (" · fell back to the fixed pipeline" if inv.get("fallback") else ""))
                with st.expander(label):
                    for n, s in enumerate(inv["steps"], 1):
                        args = ", ".join(f"{k}={v!r}" for k, v in s["args"].items())
                        st.markdown(f"**{n}. `{s['tool']}`**({args}) — {s['thought']}")
                        if s["tool"] not in ("final",):
                            st.caption(s["result_summary"][:400])

            # 5. Root cause
            st.markdown("#### Root cause")
            st.warning(inc["root_cause"])
            if identity:
                st.markdown(f"**{inc['customer_name']} ≡ {identity['foreign_name']} · confidence {identity['confidence']:.2f}**")
                if identity.get("linking_evidence"):
                    st.markdown(f"> {identity['linking_evidence']}")

            # 6. Blast radius
            st.metric("Earlier answers that used this memory", inc["blast_radius"]["answers_affected"])

            # 7. Recommended fix
            st.markdown("#### Recommended fix")
            st.markdown("\n".join(f"- {f}" for f in inc["recommended_fix"]) or "No automatic fix.")

            # 8. Buttons
            b1, b2, b3, _ = st.columns([1, 1, 1, 3])
            can_fix = status == "open" and ftype not in diagnose.NO_FIX_TYPES
            if b1.button("Apply fix", type="primary", disabled=not can_fix, key="apply-fix"):
                with st.spinner("Applying the fix in Hindsight, then re-asking and verifying…"):
                    done = call(repair.apply_fix, inc["id"])
                    if done is not None:
                        flash(*(("success", f"{inc['id']} fixed and verified. Re-ask the question to see it.")
                                if done["status"] == "fixed" else
                                ("warning", f"{inc['id']}: the fix did not verify and was rolled back.")))
                if done is not None:
                    st.rerun()
            if b2.button("Undo fix", disabled=status != "fixed", key="undo-fix"):
                with st.spinner("Reverting the fix in Hindsight…"):
                    done = call(repair.undo_fix, inc["id"])
                    if done is not None:
                        flash("info", f"{inc['id']} reverted: every applied action was undone.")
                if done is not None:
                    st.rerun()
            if b3.button("Re-ask question", disabled=not (status == "fixed" and inc["question"] is not None),
                         key="reask"):
                with st.spinner("Asking the support agent again…"):
                    done = call(repair.reask, inc["id"])
                if done is not None:
                    st.rerun()

            # 9. After re-ask
            if inc.get("reask"):
                before, after = st.columns(2)
                with before:
                    st.markdown("#### Before")
                    with st.container(border=True):
                        st.markdown(inc["wrong_answer"] or "")
                with after:
                    st.markdown("#### After")
                    with st.container(border=True):
                        st.markdown(inc["reask"]["answer"])
                    memory_table(inc["reask"]["used_memories"])
                if normalize(inc["reask"]["short_answer"]) != normalize(inc["wrong_short_answer"] or ""):
                    st.success(f"The answer changed after the fix: "
                               f"{inc['wrong_short_answer']} → {inc['reask']['short_answer']}")

            # Verification (Phase 2): re-asked answers judged against the correction; failed hypotheses rolled back
            ver = inc.get("verification")
            if ver and not ver.get("skipped"):
                st.markdown("#### Verification")
                (st.success if ver["passed"] else st.error)(
                    f"Attempt {ver['attempt']}: {ver['reason']}" + ("" if ver["passed"] else " — fix rolled back"))
                for c in ver["checks"]:
                    st.markdown(f"- {'✅' if c['consistent'] else '❌'} *{c['question']}* → **{c['short_answer']}** "
                                f":gray[({c['reason']})]")
            for h in inc.get("hypotheses") or []:
                st.caption(f"Hypothesis {h['attempt']} ({h['failure_type']}) failed verification and was rolled back.")
            if inc.get("needs_human"):
                st.warning("No hypothesis verified: every change was rolled back. A human needs to look at this incident.")
            if inc.get("policy"):
                st.caption(f"Autonomy policy: {inc['policy']['decision']} — {inc['policy']['reason']}")

            # 10. Applied actions
            if inc["applied_actions"]:
                st.markdown("#### Applied actions")
                lines = []
                for a in inc["applied_actions"]:
                    if a["kind"] == "invalidate":
                        lines.append(f"- Invalidated in Hindsight: `{a['memory_id']}` (reversible)")
                    elif a["kind"] == "alias":
                        lines.append(f"- Linked identities: `{a['a']}` ≡ `{a['b']}`")
                    elif a["kind"] == "retain_doc":
                        lines.append(f"- Retained in Hindsight: `{a['document_id']}`")
                st.markdown("\n".join(lines))

# ---------------------------------------------------------------- Tab 3: Memory Health
with tab_health:
    results = call(store.load_eval_results)
    if results:
        rows = results["questions"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Accuracy before", f"{results['before_accuracy']:.0f}%")
        c2.metric("Accuracy after", f"{results['after_accuracy']:.0f}%",
                  delta=f"{results['after_accuracy'] - results['before_accuracy']:+.0f} pts")
        c3.metric("Wrong answers fixed", sum(i["answers_fixed"] for i in results["incidents"]))
        c4.metric("Incidents by type", ", ".join(f"{t} ×{n}" for t, n in results["by_type"].items()) or "none")
        chart = config.DOCS_DIR / "before_after.png"
        if chart.exists():
            st.image(str(chart))
        st.dataframe(pd.DataFrame([{
            "id": r["id"], "customer": r["customer"], "question": r["question"],
            "before": "✓" if r["before_correct"] else "✗", "after": "✓" if r["after_correct"] else "✗",
            "fixed_by": r["fixed_by"] or "",
        } for r in rows]), hide_index=True, width="stretch")
    else:
        st.info("No evaluation yet. Run `python scripts/eval.py` in a terminal.")

    st.divider()
    st.subheader("Learning curve")
    points = call(lessons.learning_curve) or []
    if points:
        st.plotly_chart(learning_curve_figure(points), width="stretch")
        st.caption("First identity split reached customers. After Memory SRE learned from it, every later one "
                   "was prevented before any wrong answer.")
    else:
        st.caption("No incidents yet. The curve starts with the first reported wrong answer.")

    st.divider()
    st.subheader("What Memory SRE has learned")
    learned = call(lessons.learned) or []
    if learned:
        st.markdown("\n".join(f"- {l['text']} :gray[(proof count {l['proof_count']})]" for l in learned))
    else:
        st.caption("No lessons yet. A lesson is recorded each time a fix is applied.")

    has_lesson = bool(call(lessons.has_resolution_lesson))
    if not has_lesson:
        st.session_state["proposals"] = None   # e.g. after a reseed: old cards no longer apply
    if st.button("Run proactive scan", disabled=not has_lesson, key="scan"):
        with st.spinner("Scanning memory for unlinked identities…"):
            proposals = call(lessons.proactive_identity_scan)
            if proposals is not None:
                st.session_state["proposals"] = proposals
    st.caption("Applies the identity-split lesson learned from past incidents to find unlinked customers "
               "before they cause wrong answers.")

    proposals = st.session_state["proposals"]
    if proposals == []:
        st.info("No unlinked identities found.")
    linked = {tuple(sorted(pair)) for pair in (call(store.alias_pairs) or [])}
    pending = [p for p in proposals or [] if tuple(sorted((p["a"], p["b"]))) not in linked]
    if len(pending) > 1 and st.button(f"Accept all ({len(pending)})", type="primary", key="accept-all"):
        with st.spinner(f"Linking {len(pending)} identities in Hindsight…"):
            done = call(lessons.accept_all, pending)
        if done is not None:
            st.rerun()   # every card then shows Prevented
    for p in proposals or []:
        with st.container(border=True):
            st.markdown(f"**{p['name_a']} ≡ {p['name_b']}**")
            st.markdown(f"Shared domain: `{p['shared_domain']}` · confidence {p['confidence']:.2f}")
            st.markdown(f"> {p['linking_evidence']}")
            if tuple(sorted((p["a"], p["b"]))) in linked:
                st.success("Prevented: linked before any wrong answer.")
            elif st.button("Link identities", key=f"link-{p['a']}|{p['b']}"):
                with st.spinner("Linking identities in Hindsight…"):
                    inc = call(lessons.accept_proposal, p)
                if inc is not None:
                    st.session_state["selected_incident"] = inc["id"]
                    st.rerun()   # refresh the Incidents tab and the lessons list; the card then shows Prevented

# ---------------------------------------------------------------- Sidebar (last, so counts include this run's actions)
with st.sidebar:
    st.markdown(f"**Main bank:** `{config.MAIN_BANK_ID}`  \n**Lessons bank:** `{config.LESSONS_BANK_ID}`")
    st.metric("Incidents", len(call(store.list_incidents) or []))
    st.metric("Linked identities", len(call(store.alias_pairs) or []))
    st.metric("Answers logged", len(call(store.list_answers) or []))
    if results := call(store.load_eval_results):
        st.markdown(f"**Last eval:** {results['before_accuracy']:.0f}% → {results['after_accuracy']:.0f}%")
    st.caption("Reset: run `python scripts/seed.py` in a terminal.")
