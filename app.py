"""Memory SRE for Hindsight — Streamlit UI.

Business logic lives in memsre/ and this file only calls the functions documented in API.md. The ui/ package holds the
design system (theme, components, charts), the live agent trace and cached reads."""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from memsre import agent, autonomy, catalog, config, diagnose, lessons, repair, store
from memsre.grading import normalize
from ui import charts, data, live, theme
from ui import components as C

st.set_page_config(page_title="Memory SRE", page_icon=":material/monitor_heart:", layout="wide",
                   initial_sidebar_state="collapsed")
theme.inject()
live.install()

TABS = [":material/support_agent: Support console", ":material/crisis_alert: Incidents",
        ":material/radar: Autonomy", ":material/school: Learning"]
CHART_CFG = {"displayModeBar": False, "responsive": True}
HS_BACKOFF_S = 20          # after a failed Hindsight read, skip further reads for this long (the page stays fast)
_shown_errors: set = set()  # one error card per (call, message) per run


def call(fn, *args, **kwargs):
    """Every backend call goes through here: on failure show a styled error card (once per run) and return None."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 - the UI must never crash on a backend error
        name = getattr(fn, "__name__", "backend call").strip("_").replace("_", " ")
        key = (name, str(e)[:200])
        if key not in _shown_errors:
            _shown_errors.add(key)
            st.error(f"**{name.capitalize()} failed** · {type(e).__name__}: {e}", icon=":material/error:")
        return None


def hs_read(fn, *args):
    """A cached Hindsight read through call(), skipped (with a styled notice) while Hindsight is known to be down."""
    if time.time() < st.session_state.get("hs_down_until", 0):
        key = ("hindsight", "down")
        if key not in _shown_errors:
            _shown_errors.add(key)
            st.error("**Hindsight unavailable** · retrying shortly; showing what is stored locally.", icon=":material/cloud_off:")
        return None
    name = getattr(fn, "__name__", "").strip("_").replace("_", " ")
    before = {k for k in _shown_errors if k[0] == name}
    out = call(fn, *args)
    if out is None and {k for k in _shown_errors if k[0] == name} - before:
        st.session_state["hs_down_until"] = time.time() + HS_BACKOFF_S
    return out


def toast(message: str, icon: str | None = None, now: bool = False) -> None:
    """now=True shows it immediately (flows that don't rerun); otherwise it is queued for the next run (st.rerun)."""
    if now:
        st.toast(message, icon=icon)
    else:
        st.session_state["toasts"].append((message, icon))


def show(html: str, **kw) -> None:
    st.html(html, **kw)


def safe_name(key: str) -> str:
    try:
        return catalog.customer_name(key)
    except Exception:  # noqa: BLE001
        return key


for k, v in {"last_answer": None, "show_report": False, "selected_incident": None, "proposals": None, "reported": {},
             "patrol_report": None, "patrol_trace": None, "rejected_pairs": set(), "toasts": [], "revealed": set(),
             "just_created": None, "just_fixed": None, "metric_state": {}, "feed_seen": None}.items():
    st.session_state.setdefault(k, v)

try:
    config.check()
except Exception as e:  # noqa: BLE001
    st.error(f"**Configuration error** · {e}", icon=":material/error:")
    st.stop()

for msg, ic in st.session_state["toasts"]:
    st.toast(msg, icon=ic)
st.session_state["toasts"] = []

st.session_state.setdefault("active_tab", TABS[0])
if nav := st.session_state.pop("pending_nav", None):   # programmatic tab switch, before the widget exists
    st.session_state["active_tab"] = nav
    st.session_state["nav"] = nav
theme.inject_compact(st.session_state["active_tab"] in (TABS[1], TABS[2]))

# ---------------------------------------------------------------- one Hindsight rules read per run (hero, KPIs, Watch)
RULES_ERR = None
if time.time() < st.session_state.get("hs_down_until", 0):
    RULES, RULES_ERR = None, "Hindsight unavailable (retrying shortly)"
else:
    try:
        RULES = data.learned_rules()
    except Exception as e:  # noqa: BLE001 - shown in the hero pill; sections that need rules show their own state
        RULES, RULES_ERR = None, f"{type(e).__name__}: {e}"[:240]
        st.session_state["hs_down_until"] = time.time() + HS_BACKOFF_S


# ---------------------------------------------------------------- hero + metrics (computed first, so slots never flash)
def top_html() -> tuple[str, list[str]]:
    incidents = call(store.list_incidents) or []
    policy = call(store.get_policy) or {}
    hero = C.hero(data.status(incidents, policy, RULES, RULES_ERR))
    results = call(store.load_eval_results)
    cnt = data.counts(incidents)
    cards = [
        {"label": "Support accuracy", "icon": "target", "tone": "success", "suffix": "%",
         "value": round(results["before_accuracy"]) if results else None,
         "value2": round(results["after_accuracy"]) if results else None, "note": "20-question eval · before → after"},
        {"label": "Incidents fixed", "icon": "shield-check", "tone": "accent", "value": cnt["fixed"],
         "note": "diagnosed, repaired, verified by re-asking"},
        {"label": "Prevented", "icon": "radar", "tone": "success", "value": cnt["prevented"],
         "note": "identity splits linked before any wrong answer"},
        {"label": "Rules learned", "icon": "sparkles", "tone": "accent", "value": None if RULES is None else len(RULES),
         "note": "self-written · stored in Hindsight" if RULES is not None else "unavailable — Hindsight unreachable"},
    ]
    state = st.session_state["metric_state"]
    out = []
    for k, card in enumerate(cards):
        key = (card["value"], card.get("value2"))
        old = state.get(card["label"])
        if old and old[0] == key:
            out.append(old[1])                     # unchanged: identical HTML, so nothing re-animates
            continue
        start = old[0][0] if old and isinstance(old[0][0], int) else 0
        html = C.metric_card({**card, "i": k, "start": start})
        state[card["label"]] = (key, html)
        out.append(html)
    return hero, out


_hero, _metrics = top_html()
hero_ph = st.html(_hero)
metric_phs = [c.html(h) for c, h in zip(st.columns(4, gap="small"), _metrics)]


def refresh_top() -> None:
    """End of run: counts include this run's actions. Identical HTML is kept by the frontend, so nothing replays."""
    hero, metrics = top_html()
    hero_ph.html(hero)
    for ph, h in zip(metric_phs, metrics):
        ph.html(h)


def _remember_tab() -> None:
    st.session_state["active_tab"] = st.session_state["nav"]


def _go(tab: str, incident_id: str | None = None) -> None:
    st.session_state["pending_nav"] = tab
    if incident_id:
        st.session_state["selected_incident"] = incident_id


# ================================================================ Support console
def _use_sample() -> None:
    st.session_state["question"] = st.session_state.get("sample") or ""
    st.session_state["sample"] = None


def _customer_changed() -> None:
    st.session_state["question"] = ""
    st.session_state["sample"] = None


def render_console() -> None:
    customers = call(catalog.load_customers) or []
    names = {c["key"]: c["name"] for c in customers}
    if not names:
        show(C.empty_state("users", "No customers", "catalog.load_customers() returned no customers."))
        return
    keys = list(names)
    if st.session_state.get("customer") not in keys:
        st.session_state["customer"] = keys[0]
    main, side = st.columns([2.3, 1], gap="large")
    with side:   # first: it has no entry animation, and it no longer fades while the main column waits on the agent
        render_customer_side(st.session_state["customer"], names)
    with main:
        show(C.kicker("Customer"))
        key = st.pills("Customer", keys, format_func=names.get, key="customer", required=True,
                       label_visibility="collapsed", on_change=_customer_changed)
        samples = [q for q in (call(catalog.load_questions) or []) if q["customer"] == key][:4]
        if samples:
            show(C.kicker("Try asking"))
            st.pills("Try asking", [q["question"] for q in samples], key="sample", on_change=_use_sample,
                     label_visibility="collapsed")
        with st.container(horizontal=True, key="qrow", vertical_alignment="center"):
            question = st.text_input("Question", key="question", placeholder="Ask the support agent…",
                                     label_visibility="collapsed")
            asked = st.button("Ask", type="primary", icon=":material/send:", key="ask")
        area = st.empty()
        if asked:
            if not (question or "").strip():
                st.warning("Type a question first.", icon=":material/edit:")
            else:
                area.html(C.skeleton("answer"))
                with live.LiveTrace(st.container(), title="Watch · a learned rule fired on this answer",
                                    subtitle="checking before anyone acts on it", mode="watch") as wt:
                    ans = call(agent.answer, key, question.strip())
                wt.finish_watch()
                if ans is not None:
                    st.session_state["last_answer"] = ans
                    st.session_state["show_report"] = False
                    data.invalidate()
                    if getattr(ans, "watch", None):
                        toast(f"Watch: a learned rule fired · {len(ans.watch)} finding(s)", ":material/visibility:", now=True)
                wt.resume()
        with area.container():
            render_answer(names)


def render_answer(names: dict) -> None:
    ans = st.session_state["last_answer"]
    if ans is None:
        show(C.empty_state("message", "Ask the support agent a question",
                           "Pick a customer and a suggested question. When an answer is wrong, report it and watch "
                           "the investigator find the memory that caused it.",
                           "Try Kestrel Logistics → “Can Kestrel Logistics export audit logs?”"))
        return
    first = ans.answer_id not in st.session_state["revealed"]
    st.session_state["revealed"].add(ans.answer_id)
    show(C.answer_card({"customer_name": names.get(ans.customer_key, ans.customer_key), "question": ans.question,
                        "answer": ans.answer, "short_answer": ans.short_answer, "answer_id": ans.answer_id,
                        "memories": len(ans.used_memories), "watch": getattr(ans, "watch", None) or []}, reveal=first))
    show(C.section_header("Memories used", f"{len(ans.used_memories)} of {len(ans.shown_memories)} recalled memories "
                          "made it into the answer", "database"))
    show(C.memory_cards(ans.used_memories))

    inc_id = st.session_state["reported"].get(ans.answer_id)
    with st.container(horizontal=True, vertical_alignment="center", key="feedback-row"):
        show(C.kicker("Was this correct?"))
        if st.button("Correct", icon=":material/thumb_up:", key="thumbs-up"):
            st.toast("Thanks — marked as correct", icon=":material/check_circle:")
        if st.button("Wrong", icon=":material/thumb_down:", key="thumbs-down",
                     type="primary" if (st.session_state["show_report"] or inc_id) else "secondary"):
            st.session_state["show_report"] = True

    cta = st.empty()               # "Open case file" sits right under the form, above the (long) trace
    slot = st.empty()              # the finished trace on later runs
    if st.session_state["show_report"] and not inc_id:
        # Each part of the form has its own placeholder, so the live trace can take the form's place without the old
        # textarea/button lingering underneath as stale elements while the investigation runs.
        with st.container(key="panel-report"):
            head_ph, area_ph, btn_ph = st.empty(), st.empty(), st.empty()
        head_ph.html(C.section_header("Report a wrong answer", "Paste what the customer actually told you. The investigator "
                                      "takes it from there — about a minute; stay on this tab.", "siren"))
        correction = area_ph.text_area("What's actually true? Paste what the customer told you", key="correction",
                                       placeholder="e.g. Wrong — they moved to the Growth plan in August.")
        report = btn_ph.button("Report & diagnose", type="primary", icon=":material/troubleshoot:", key="report")
        if report:
            if not (correction or "").strip():
                st.warning("Paste what the customer told you first.", icon=":material/edit:")
            else:
                area_ph.empty()
                btn_ph.empty()
                with live.LiveTrace(head_ph, title="Investigating",
                                    subtitle=f"{names.get(ans.customer_key, ans.customer_key)} · {ans.answer_id} · "
                                             "about a minute — stay on this tab") as lt:
                    inc = call(diagnose.create_incident, ans, correction.strip())
                lt.finish(inc)
                if inc is not None:
                    st.session_state["reported"][ans.answer_id] = inc["id"]
                    st.session_state["selected_incident"] = inc["id"]
                    st.session_state["just_created"] = inc["id"]
                    data.invalidate()
                    toast(f"{inc['id']} opened · {inc['failure_type']}", ":material/emergency:", now=True)
                    render_cta(cta, inc["id"])
                lt.resume()
        return
    if inc_id:
        render_cta(cta, inc_id)
        inc = call(store.get_incident, inc_id)
        if inc is not None:
            with slot.container():
                if inc.get("investigation"):
                    show(C.trace_timeline(inc["investigation"], animate=False, title="Investigation complete",
                                          subtitle=f"{inc['id']} · {inc['customer_name']}"))
                else:
                    show(C.trace_pipeline_summary(inc))


def render_cta(cta, inc_id: str | None) -> None:
    if not inc_id:
        return
    inc = call(store.get_incident, inc_id)
    if inc is None:
        return
    with cta.container(horizontal=True, vertical_alignment="center", key="case-cta"):
        show(f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">{C.failure_badge(inc["failure_type"])}'
             f'{C.status_pill(inc["status"])}<span class="ms-muted" style="font-size:13px">{C.esc(inc["id"])} is ready: '
             f'culprit, evidence, identity link and a reversible fix.</span></div>')
        st.button("Open case file", type="primary", icon=":material/arrow_forward:", key="open-case",
                  on_click=_go, args=(TABS[1], inc["id"]))


def render_customer_side(key: str, names: dict) -> None:
    pairs = call(store.alias_pairs) or []
    linked = [b for a, b in pairs if a == key] + [a for a, b in pairs if b == key]
    ans = st.session_state["last_answer"]
    incidents = [i for i in (call(store.list_incidents) or []) if i["customer_key"] == key]
    stats = {"Incidents": len(incidents)}
    if ans is not None and ans.customer_key == key:
        stats["Memories recalled"] = len(ans.shown_memories)
        stats["Memories used"] = len(ans.used_memories)
    show(C.customer_panel(names.get(key, key), f"customer:{key}", [f"customer:{key}"] + [f"customer:{k}" for k in linked],
                          [safe_name(k) for k in linked], stats))
    policy = call(store.get_policy) or {}
    if RULES is None:
        show(C.empty_state("alert-circle", "Rules unavailable",
                           "Hindsight could not be reached, so Watch's learned rules can't be shown right now."))
    else:
        show(C.watch_panel(len(RULES), policy.get("prevented") == "auto"))


# ================================================================ Incidents
def _select(incident_id: str) -> None:
    st.session_state["selected_incident"] = incident_id


def render_incidents() -> None:
    incidents = call(store.list_incidents)
    if incidents is None:
        return        # the error card says why; no false "no incidents" state
    if not incidents:
        show(C.empty_state("siren", "No incidents yet", "Report a wrong answer in the Support console and the "
                           "investigator opens a case here — or run a patrol once Memory SRE has learned a rule."))
        return
    ids = [i["id"] for i in incidents]
    if st.session_state["selected_incident"] not in ids:
        st.session_state["selected_incident"] = ids[0]
    selected = st.session_state["selected_incident"]
    rail, main = st.columns([1, 2.75], gap="large")
    with rail:
        cnt = data.counts(incidents)
        show(C.kicker(f"{C.plural(cnt['total'], 'incident')} · {cnt['open']} open · {cnt['fixed'] + cnt['prevented']} resolved"))
        for inc in incidents:
            with st.container(key=f"cc-inc-{inc['id']}"):
                show(C.incident_card(inc, active=inc["id"] == selected))
                st.button(f"Open {inc['id']}", key=f"pick-{inc['id']}", on_click=_select, args=(inc["id"],))
    with main:
        inc = call(store.get_incident, selected)
        if inc is not None:
            render_case(inc)


def render_case(inc: dict) -> None:
    iid, ftype, status = inc["id"], inc["failure_type"], inc["status"]
    identity = inc.get("identity")
    just_fixed = st.session_state.get("just_fixed") == iid
    just_created = st.session_state.get("just_created") == iid
    healed = status in ("fixed", "prevented") and bool(inc.get("applied_actions"))
    culprits, supporting = inc.get("culprits") or [], inc.get("supporting") or []

    show(C.case_header(inc))
    show(C.what_went_wrong(inc))
    if healed and not just_fixed:
        show(C.healed_banner(inc, animate=False))
    if identity:
        show(C.identity_link(inc))

    if culprits or supporting or inc.get("question") is not None:
        own_tag = f"customer:{inc['customer_key']}"
        foreign = {identity["foreign_tag"]} if identity else set()
        claim = C.esc(inc.get("wrong_claim"))
        cards = [C.memory_card(m, "culprit", own_tag=own_tag, struck=healed and status == "fixed", animate=just_fixed,
                               note=f"Wrong claim: <q>{claim}</q>" if claim else None, i=k) for k, m in enumerate(culprits)]
        cards += [C.memory_card(m, "evidence", own_tag=own_tag, foreign_tags=foreign, i=k + 1) for k, m in enumerate(supporting)]
        br = inc.get("blast_radius") or {}
        grid = (f'<div class="ms-mem-grid">{"".join(cards)}</div>' if cards else
                C.empty_state("search", "No memory evidence", "No culprit or contradicting memory was identified."))
        show('<div class="ms-evidence-row" style="display:grid;grid-template-columns:minmax(0,2.6fr) minmax(220px,1fr);'
             f'gap:12px;align-items:stretch">{grid}{C.blast_radius(br.get("answers_affected", 0), br.get("answer_ids") or [])}</div>')
    show(C.root_cause_card(inc))

    # ---- fix (right after the diagnosis, so the heal moment plays on screen)
    show(C.fix_plan(inc))
    can_fix = status in ("open", "auto-opened") and ftype not in diagnose.NO_FIX_TYPES
    with st.container(horizontal=True, key="fix-row", vertical_alignment="center"):
        if status in ("fixed", "prevented"):
            show(C.chip("Fixed · verified" if status == "fixed" else "Prevented · linked", "success",
                        icon_name="check-circle"), width="content")
            apply_clicked = False
        else:
            apply_clicked = st.button("Approve & apply" if status == "auto-opened" else "Apply fix", type="primary",
                                      icon=":material/healing:", disabled=not can_fix, key="apply-fix")
        undo_clicked = st.button("Undo fix", icon=":material/undo:", disabled=status != "fixed", key="undo-fix")
        reask_clicked = st.button("Re-ask question", icon=":material/replay:",
                                  disabled=not (status == "fixed" and inc["question"] is not None), key="reask")
    if apply_clicked:
        with st.status("Applying the fix in Hindsight, re-asking every affected question and judging each answer…",
                       expanded=False) as s:
            done = call(repair.apply_fix, iid)
            if done is None:
                s.update(label="Apply fix failed — see the error. Some changes may be partly applied; the Activity "
                               "feed shows every write.", state="error", expanded=True)
            else:
                ok = done["status"] in ("fixed", "prevented")
                s.update(label="Fix verified" if ok else "The fix did not verify, so it was rolled back",
                         state="complete" if ok else "error")
        data.invalidate()
        if done is not None:
            st.session_state["just_fixed"] = iid
            toast(f"{iid} healed and verified" if done["status"] in ("fixed", "prevented")
                  else f"{iid}: the fix did not verify and was rolled back", ":material/verified:")
            st.rerun()
    if undo_clicked:
        with st.spinner("Reverting every applied action in Hindsight…"):
            done = call(repair.undo_fix, iid)
        data.invalidate()
        if done is not None:
            toast(f"{iid} reverted: every applied action was undone", ":material/undo:")
            st.rerun()
    if reask_clicked:
        with st.spinner("Asking the support agent again…"):
            done = call(repair.reask, iid)
        if done is not None:
            changed = normalize(done["reask"]["short_answer"]) != normalize(done.get("wrong_short_answer") or "")
            toast(f"The answer changed: {done.get('wrong_short_answer')} → {done['reask']['short_answer']}" if changed
                  else "Re-asked: the answer did not change", ":material/replay:")
            data.invalidate()
            st.rerun()
    if just_fixed and healed:
        show(C.healed_banner(inc, animate=True))

    # ---- verification, self-correction, before/after
    ver = inc.get("verification")
    if ver and not ver.get("skipped"):
        show(C.verification(ver, animate=just_fixed))
    if inc.get("hypotheses") or inc.get("needs_human"):
        show(C.rollback_cards(inc.get("hypotheses") or [], bool(inc.get("needs_human"))))
    if inc.get("reask"):
        show(C.section_header("Before and after", "The same question, asked again after the fix", "refresh"))
        show(C.before_after(inc))
    if inc.get("applied_actions"):
        show(C.applied_actions(inc["applied_actions"]))

    # ---- the agent's trace (every attempt), collapsed unless the case was just opened
    inv = inc.get("investigation")
    if inv:
        attempts = [inv] + list(inv.get("attempts") or [])
        latest = attempts[-1] or {}
        label = (f"Agent trace · {C.plural(len(latest.get('steps') or []), 'step')} · "
                 f"{C.plural(latest.get('llm_calls'), 'LLM call')}" + (f" · {len(attempts)} attempts" if len(attempts) > 1 else ""))
        with st.expander(label, icon=":material/smart_toy:", expanded=just_created or len(attempts) > 1):
            for n, a in enumerate(attempts, 1):
                if not a:
                    continue
                title = ("Agent trace" if len(attempts) == 1 else
                         f"Attempt {n}" + (" · current hypothesis" if n == len(attempts) else " · rolled back"))
                show(C.trace_timeline(a, animate=just_created and n == 1, title=title))

    # ---- reviewer feedback on autonomous incidents
    if status in ("prevented", "auto-opened") and identity:
        with st.expander("Reject this link (retained as a rule exception)", icon=":material/block:"):
            reason = st.text_input("Why is this not the same customer?", key=f"inc-reason-{iid}")
            if st.button("Reject", key=f"inc-reject-{iid}", icon=":material/block:"):
                with st.spinner("Undoing the link and recording the rejection…"):
                    done = call(lessons.reject_proposal, _proposal_from_incident(inc), reason)
                data.invalidate()
                if done is not None:
                    toast(f"Rejected: {done['value']} is now a rule exception", ":material/block:")
                    st.rerun()

    if just_fixed:
        st.session_state["just_fixed"] = None
    if just_created:
        st.session_state["just_created"] = None


def _proposal_from_incident(inc: dict) -> dict:
    identity = inc.get("identity") or {}
    return {"a": inc["customer_key"], "b": str(identity.get("foreign_tag") or ":").split(":", 1)[1],
            "signal_type": inc.get("signal_type") or "email_domain",
            "shared_domain": inc.get("shared_value") or str(inc.get("evidence_reason") or "").rsplit(" ", 1)[-1]}


# ================================================================ Autonomy
def _set_policy(**changes) -> None:
    done = call(store.set_policy, **changes)
    if done is not None:
        data.invalidate()
        toast("Autonomy policy updated", ":material/tune:")


def _toggle_auto() -> None:
    _set_policy(prevented="auto" if st.session_state["auto-mode"] else "approval")


def _toggle_reactive() -> None:
    _set_policy(reactive="auto" if st.session_state["pol-reactive"] else "approval")


def _toggle_autopatrol() -> None:
    _set_policy(auto_patrol_after_fix=bool(st.session_state["pol-autopatrol"]))


@st.fragment(run_every="15s")
def _activity_feed() -> None:
    audit = call(store.list_audit) or []
    show(C.section_header("Activity", "Every investigation, fix, verification, patrol and policy decision — live",
                          "activity", C.chip(f"{len(audit)} events", "neutral")))
    items = data.activity(audit)
    with st.container(height=760, border=False, key="feed-scroll"):
        show(C.activity_feed(items, seen_ts=st.session_state["feed_seen"]))
    if items:
        st.session_state["feed_seen"] = max(str(i.get("ts") or "") for i in items)


def render_autonomy() -> None:
    policy = call(store.get_policy) or {}
    has = bool(RULES) or bool(hs_read(data.has_lesson))
    st.session_state["auto-mode"] = policy.get("prevented") == "auto"
    st.session_state["pol-reactive"] = policy.get("reactive") == "auto"
    st.session_state["pol-autopatrol"] = bool(policy.get("auto_patrol_after_fix"))
    with st.container(key="panel-autonomy"):
        show(C.section_header("Bounded autonomy", "Watch runs the learned rules after every answer; Patrol runs them "
                              "across every customer record. The policy decides what applies without a human.", "radar"))
        with st.container(horizontal=True, vertical_alignment="center", key="auto-controls"):
            st.toggle("Auto mode", key="auto-mode", on_change=_toggle_auto,
                      help="On: confident, reversible fixes for patrol findings apply automatically. Off: they wait for approval.")
            with st.popover("Policy", icon=":material/tune:"):
                st.toggle("Auto-apply reactive fixes", key="pol-reactive", on_change=_toggle_reactive)
                st.toggle("Patrol after every verified fix", key="pol-autopatrol", on_change=_toggle_autopatrol)
                st.caption("Fixes apply without a human only if their kind is set to auto, the agent's confidence is at "
                           "least the threshold, and the fix is reversible. Every write is audited.")
            patrol_clicked = st.button("Run patrol", type="primary", icon=":material/radar:", disabled=not has, key="patrol")
            scan_clicked = st.button("Run proactive scan", icon=":material/preview:", disabled=not has, key="scan",
                                     help="Read-only: proposes links without writing anything")
        show(C.policy_summary(policy))
        if not has:
            show('<div class="ms-muted" style="font-size:12.5px;margin-top:10px">Patrol unlocks after the first verified '
                 'fix: its post-mortem writes the detection rule the patrol runs.</div>')

    if patrol_clicked:
        with live.LiveTrace(st.container(), title="Patrol running",
                            subtitle="every learned rule across every record · stay on this tab", mode="patrol") as lt:
            report = call(autonomy.patrol)
        lt.finish_patrol(report)
        data.invalidate()
        if report is not None:
            st.session_state["patrol_report"] = report
            st.session_state["patrol_trace"] = lt.final_html()
            out = {s: sum(f["status"] == s for f in report["findings"]) for s in ("prevented", "pending", "dismissed")}
            toast(f"Patrol: {out['prevented']} prevented · {out['pending']} awaiting approval · {out['dismissed']} dismissed",
                  ":material/radar:")
            st.rerun()
        lt.resume()
    if scan_clicked:
        with live.LiveTrace(st.container(), title="Proactive scan (read-only)", subtitle="proposals only, nothing is written",
                            mode="scan") as lt:
            proposals = call(lessons.proactive_identity_scan)
        lt.finish_patrol(None, ok=proposals is not None, kind="Scan")
        if proposals is not None:
            st.session_state["proposals"] = proposals
            toast(f"Scan: {len(proposals)} proposal(s)", ":material/preview:")
            st.rerun()
        lt.resume()

    incidents = call(store.list_incidents) or []
    pending = [i for i in incidents if i["status"] == "auto-opened"]
    left, right = st.columns([1.35, 1], gap="large")
    with left:
        show(C.section_header("Awaiting approval", "Found before any wrong answer; the policy asks a human first",
                              "clock", C.chip(str(len(pending)), "warning" if pending else "neutral")))
        if not pending:
            show(C.empty_state("check-circle", "Nothing waiting", "Auto mode applies confident, reversible fixes by "
                               "itself; with it off, patrol findings wait here for you."))
        for inc in pending:
            show(C.approval_card(inc, policy))
            with st.container(horizontal=True, vertical_alignment="bottom", key=f"approve-row-{inc['id']}"):
                if st.button("Approve & apply", type="primary", icon=":material/check:", key=f"approve-{inc['id']}"):
                    with st.spinner(f"Linking {inc['customer_name']} in Hindsight…"):
                        done = call(repair.apply_fix, inc["id"])
                    data.invalidate()
                    if done is not None:
                        toast(f"{inc['id']} approved and applied", ":material/verified:")
                        st.rerun()
                reason = st.text_input("Reason to reject", key=f"feed-reason-{inc['id']}", label_visibility="collapsed",
                                       placeholder="Reason to reject (e.g. shared vendor domain)")
                if st.button("Reject", icon=":material/block:", key=f"feed-reject-{inc['id']}"):
                    with st.spinner("Recording the rejection…"):
                        done = call(lessons.reject_proposal, _proposal_from_incident(inc), reason)
                    data.invalidate()
                    if done is not None:
                        toast(f"Rejected: {done['value']} is now a rule exception", ":material/block:")
                        st.rerun()
        render_patrol_report({i["id"]: i["status"] for i in incidents})
        render_proposals()
    with right:
        _activity_feed()


def render_patrol_report(statuses: dict) -> None:
    report = st.session_state.get("patrol_report")
    if not report:
        return
    right = C.chip(f"{report['checks']} checks · {report['candidates']} candidates · {report['duration_s']}s", "neutral")
    show(C.section_header("Latest patrol", "What the rules found and what the agent decided", "radar", right))
    if st.session_state.get("patrol_trace"):
        with st.expander("Patrol trace — what the agent checked", icon=":material/radar:"):
            show(st.session_state["patrol_trace"])
    if not report["findings"]:
        show(C.empty_state("shield-check", "No candidates", "Every rule check came back clean."))
    for k, f in enumerate(report["findings"]):
        show(C.finding_card(f, i=k, live_status=statuses.get(f.get("incident_id"))))
        if f["status"] != "dismissed":
            continue
        pair = f"{f['a']}|{f['b']}"   # the agent dismissed this hit; a reviewer can make that stick
        if pair in st.session_state["rejected_pairs"]:
            show(f'<div class="ms-muted" style="font-size:12.5px;margin:6px 0 4px 46px">Pattern <span class="ms-mono">'
                 f'{C.esc(f["value"])}</span> rejected: retained as a rule exception, so it is not checked again.</div>')
            continue
        with st.expander(f"Reject this pattern for good ({f['value']})", icon=":material/block:"):
            reason = st.text_input("Reason to reject", key=f"dreason-{pair}",
                                   placeholder="e.g. shared IT vendor domain, not the customer's own")
            if st.button("Reject pattern", key=f"dreject-{pair}", icon=":material/block:"):
                with st.spinner("Recording the rejection as a lesson…"):
                    done = call(lessons.reject_proposal, f, reason)
                data.invalidate()
                if done is not None:
                    st.session_state["rejected_pairs"].add(pair)
                    toast(f"Pattern {done['value']} rejected: patrol will not check it again", ":material/block:")
                    st.rerun()


def render_proposals() -> None:
    proposals = st.session_state["proposals"]
    if proposals is None:
        return
    show(C.section_header("Proactive scan proposals", "Read-only preview: link them yourself", "scan"))
    if proposals == []:
        show(C.empty_state("shield-check", "No unlinked identities found", "Every rule check came back clean."))
        return
    linked = {tuple(sorted(p)) for p in (call(store.alias_pairs) or [])}
    pending = [p for p in proposals if tuple(sorted((p["a"], p["b"]))) not in linked]
    if len(pending) > 1 and st.button(f"Accept all ({len(pending)})", type="primary", icon=":material/done_all:",
                                      key="accept-all"):
        with st.spinner(f"Linking {len(pending)} identities in Hindsight…"):
            done = call(lessons.accept_all, pending)
        data.invalidate()
        if done is not None:
            toast(f"Linked {len(done)} identities before any wrong answer", ":material/verified:")
            st.rerun()
    for p in proposals:
        pair = f"{p['a']}|{p['b']}"
        state = ("prevented" if tuple(sorted((p["a"], p["b"]))) in linked else
                 "rejected" if pair in st.session_state["rejected_pairs"] else "pending")
        show(C.proposal_card(p, state))
        if state != "pending":
            continue
        with st.container(horizontal=True, vertical_alignment="bottom", key=f"prop-row-{pair}"):
            if st.button("Link identities", type="primary", icon=":material/link:", key=f"link-{pair}"):
                with st.spinner("Linking identities in Hindsight…"):
                    inc = call(lessons.accept_proposal, p)
                data.invalidate()
                if inc is not None:
                    st.session_state["selected_incident"] = inc["id"]
                    toast(f"Prevented: {p['name_a']} ≡ {p['name_b']} linked", ":material/verified:")
                    st.rerun()
            reason = st.text_input("Reason to reject", key=f"reason-{pair}", label_visibility="collapsed",
                                   placeholder="Reason to reject (e.g. shared IT vendor domain)")
            if st.button("Reject", icon=":material/block:", key=f"reject-{pair}"):
                with st.spinner("Recording the rejection as a lesson…"):
                    done = call(lessons.reject_proposal, p, reason)
                data.invalidate()
                if done is not None:
                    st.session_state["rejected_pairs"].add(pair)
                    toast(f"Rejected: {done['value']} is now a rule exception", ":material/block:")
                    st.rerun()


# ================================================================ Learning
def _chart(key: str, title: str, sub: str, icon_name: str, fig_fn, empty: tuple[str, str]) -> None:
    with st.container(key=f"panel-chart-{key}", height="stretch"):
        show(f'<div class="ms-chart-title">{C.icon(icon_name)}{C.esc(title)}</div><div class="ms-chart-sub">{C.esc(sub)}</div>')
        fig = fig_fn()
        if fig is None:
            show(C.empty_state(icon_name, *empty))
        else:
            st.plotly_chart(fig, width="stretch", config=CHART_CFG, key=f"chart-{key}")


def render_learning() -> None:
    incidents = call(store.list_incidents) or []
    results = call(store.load_eval_results)
    bench = data.benchmark()
    points = call(lessons.learning_curve) or []
    rules = RULES
    conf = data.rule_confirmations(incidents)
    gain = f" · +{results['after_accuracy'] - results['before_accuracy']:.0f} pts" if results else ""

    show(C.section_header("How Memory SRE learns", "Every lesson lives in Hindsight and changes what the agent does next",
                          "sparkles"))
    a, b = st.columns(2, gap="medium")
    with a:
        _chart("accuracy", "Support accuracy, before and after", f"The committed 20-question evaluation{gain}", "target",
               lambda: charts.accuracy(results) if results else None,
               ("No evaluation yet", "Run python scripts/eval.py to produce the before/after result."))
    with b:
        _chart("ab-wrong", "A/B: wrong answers reaching customers", "Same four identity splits, memory OFF vs ON",
               "shield", lambda: charts.ab_wrong_answers(bench) if bench else None,
               ("No benchmark yet", "Run python scripts/learning_benchmark.py (about 30 minutes)."))
    a, b = st.columns(2, gap="medium")
    with a:
        _chart("ab-steps", "A/B: investigation steps per episode", "Learned rules and playbooks cut the work",
               "bot", lambda: charts.ab_steps(bench) if bench else None,
               ("No benchmark yet", "Run python scripts/learning_benchmark.py."))
    with b:
        _chart("cost", "Diagnosis cost per incident", "LLM calls (bars, by kind) and agent steps (dots), this session",
               "cpu", lambda: charts.diagnosis_cost(incidents) if any(i.get("investigation") for i in incidents) else None,
               ("No investigations yet", "Report a wrong answer to start one."))
    a, b = st.columns(2, gap="medium")
    with a:
        _chart("curve", "Learning curve", "First identity split reached customers. After Memory SRE learned from it, "
               "every later one was prevented before any wrong answer.", "activity",
               lambda: charts.learning_curve(points) if points else None,
               ("No incidents yet", "The curve starts with the first reported wrong answer."))
    with b:
        _chart("proofs", "Rule proof counts", "The incident a rule came from, plus every prevention it confirmed",
               "sparkles", lambda: charts.rule_proofs(rules, conf) if rules else None,
               ("No rules yet" if rules is not None else "Rules unavailable",
                "The first verified fix writes the first rule." if rules is not None else "Hindsight could not be reached."))

    n_rules = "—" if rules is None else C.plural(len(rules), "rule")
    show(C.section_header("Rules the agent wrote", "Self-written detection rules, read back from Hindsight — Patrol and "
                          "Watch run only these", "sparkles", C.chip(n_rules, "accent")))
    if rules is not None:
        show(C.rule_cards(rules, conf))
    sk = st.empty()
    sk.html(C.skeleton("cards", 2))
    exc = hs_read(data.exceptions)
    obs = hs_read(data.learned)
    sk.empty()
    show(C.section_header("Rejected patterns", "Reviewer feedback, retained as rule exceptions", "ban"))
    if exc is not None:
        show(C.exception_cards(exc))
    _living_playbook(fresh=not incidents)
    show(C.section_header("What Memory SRE has learned", "Hindsight's consolidated observations, with proof counts", "bulb"))
    if obs is not None:
        show(C.observations(obs))
    if results:
        with st.expander("Evaluation details (20 questions)", icon=":material/table:"):
            st.dataframe(pd.DataFrame([{
                "id": r["id"], "customer": r["customer"], "question": r["question"],
                "before": "✓" if r["before_correct"] else "✗", "after": "✓" if r["after_correct"] else "✗",
                "fixed_by": r["fixed_by"] or ""} for r in results["questions"]]), hide_index=True, width="stretch")


@st.fragment(run_every="20s")
def _living_playbook(fresh: bool = False) -> None:
    sk = st.empty()
    sk.html(C.skeleton("chart"))
    pb = hs_read(data.playbook)
    hist = hs_read(data.playbook_history) or []
    sk.empty()
    versions = data.playbook_versions(pb, hist, fresh=fresh)
    right = C.chip(C.plural(len(versions), "version"), "accent") if versions else ""
    show(C.section_header("Living playbook", "A Hindsight mental model, refreshed after every post-mortem — updates live",
                          "book-open", right))
    if not versions:
        show(C.empty_state("book-open", "No playbook yet", "The Memory SRE Playbook appears after the first verified "
                           "fix; its post-mortem feeds the mental model."))
        return
    labels = [v["label"] for v in versions]
    if st.session_state.get("pb-version") not in labels:
        st.session_state["pb-version"] = labels[-1]
    with st.container(key="panel-playbook-card"):
        refreshed = (pb or {}).get("last_refreshed_at") or versions[-1].get("at")
        head = (f'<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
                f'{C.chip((pb or {}).get("name") or "Memory SRE Playbook", "accent", icon_name="book-open")}'
                f'{C.chip("refreshed " + C.time_ago(refreshed), "neutral", icon_name="clock")}'
                f'{C.chip("mental model · lessons bank", "neutral", icon_name="database")}'
                + ("" if pb is not None else C.chip("live copy unavailable — showing the last version seen", "warning",
                                                     icon_name="alert"))
                + '</div>')
        show(head)
        if len(labels) == 1:
            show('<div class="ms-muted" style="font-size:12.5px;margin:8px 0">Diffs appear after the next refresh — the '
                 'playbook refreshes after each post-mortem, patrol and rejection.</div>')
            with st.container(height=420, key="pb-scroll"):
                st.markdown(versions[0]["content"])
            return
        sel = st.select_slider("Version", options=labels, key="pb-version")
        idx = labels.index(sel)
        cur = versions[idx]
        left, right_col = st.columns([1.35, 1], gap="medium")
        with left:
            with st.container(height=420, key="pb-scroll"):
                st.markdown(cur["content"])
        with right_col:
            if idx > 0:
                show(C.playbook_diff(versions[idx - 1]["content"], cur["content"], versions[idx - 1]["label"], cur["label"]))
            else:
                show(C.empty_state("branch", "First version", "Move the slider to a later version to see what the "
                                   "playbook learned since."))


# ---------------------------------------------------------------- render the active tab
t_console, t_inc, t_auto, t_learn = st.tabs(TABS, key="nav", default=st.session_state["active_tab"],
                                             on_change=_remember_tab)
with t_console:
    if t_console.open:
        render_console()
with t_inc:
    if t_inc.open:
        render_incidents()
with t_auto:
    if t_auto.open:
        render_autonomy()
with t_learn:
    if t_learn.open:
        render_learning()

refresh_top()
