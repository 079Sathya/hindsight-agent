"""HTML components for the premium UI. Pure functions: each returns an HTML string for ``st.html`` and never calls
Streamlit. Every piece of dynamic text is escaped; styling lives in ui/theme.py (classes prefixed ``ms-``)."""
from __future__ import annotations

import difflib
import html
import re
from datetime import datetime, timezone

from . import theme

# ------------------------------------------------------------------ helpers

SOURCES = {
    "crm_notes": ("CRM notes", "notebook"), "onboarding_form": ("Onboarding form", "clipboard"),
    "support_ticket": ("Support ticket", "ticket"), "csm_notes": ("CSM notes", "message"),
    "billing_system": ("Billing system", "receipt"),
}
TOOL_ICONS = {
    "recall_customer": "user", "recall_whole_bank": "database", "get_memory": "file", "list_customer_tags": "tag",
    "find_records_sharing": "scan", "compare_records": "compare", "recall_lessons": "book", "get_playbook": "book-open",
    "blast_radius": "target", "propose_fix": "wrench", "final": "shield-check", "verdict_rejected": "shield-alert",
    "invalid": "alert", "fallback": "branch",
}
TRIGGER_LABELS = {"patrol": "Patrol", "watch": "Watch", "scan": "Scan", None: "Reported by support"}
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def esc(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def icon(name: str, cls: str = "") -> str:
    return f'<span class="ms-i ms-i-{esc(name)} {cls}" aria-hidden="true"></span>'


def _get(m, key, default=None):
    return m.get(key, default) if isinstance(m, dict) else getattr(m, key, default)


def time_ago(iso: str | None, now: datetime | None = None) -> str:
    """'just now', '3m ago', '2h ago', 'Sep 28' (UTC ISO timestamps)."""
    if not iso:
        return ""
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return str(iso)[:16]
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    s = (now - t).total_seconds()
    if s < 45:
        return "just now"
    if s < 3600:
        return f"{int(s // 60) or 1}m ago"
    if s < 86400:
        return f"{int(s // 3600)}h ago"
    return t.strftime("%b %d").replace(" 0", " ")


def short_id(mid) -> str:
    return str(mid or "")[:8]


def split_memory_text(text) -> tuple[str, dict]:
    """Hindsight appends ' | When: … | Involving: …' to facts; split the fact from that metadata."""
    parts = [p.strip() for p in str(text or "").split(" | ")]
    fact, meta = parts[0], {}
    for p in parts[1:]:
        if ":" in p:
            k, v = p.split(":", 1)
            if k.strip() and len(k) < 24:
                meta[k.strip()] = v.strip()
                continue
        fact = f"{fact} · {p}" if p else fact
    return fact, meta


def plural(n, word: str, suffix: str = "s") -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return f"{n} {word}{suffix}"
    return f"{n} {word}{'' if n == 1 else suffix}"


_META = re.compile(r"\s*\|\s*(?:When|Involving|Where|Who)\s*:[^|\"]*")


def clean_meta(text) -> str:
    """Drop Hindsight's retrieval metadata (' | When: … | Involving: …') from user-facing text."""
    t = _META.sub("", str(text or ""))
    return re.sub(r"\s*\|\s*", " · ", t).strip(" ·")


def _pct(x) -> str:
    try:
        return f"{round(float(x) * 100)}%"
    except (TypeError, ValueError):
        return "—"


def _highlight_emails(text: str) -> str:
    """Escape text, then set email addresses in mono."""
    out, last = [], 0
    for m in _EMAIL.finditer(text or ""):
        out.append(esc(text[last:m.start()]))
        out.append(f'<span class="ms-mono">{esc(m.group(0))}</span>')
        last = m.end()
    out.append(esc((text or "")[last:]))
    return "".join(out)


def _clip(text, n: int) -> str:
    text = str(text or "")
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def chip(text, tone: str = "neutral", mono: bool = False, icon_name: str | None = None, glow: bool = False,
         title: str | None = None) -> str:
    cls = f"ms-chip ms-tone-{tone}" + (" mono" if mono else "") + (" glow" if glow else "")
    t = f' title="{esc(title)}"' if title else ""
    return f'<span class="{cls}"{t}>{icon(icon_name, "sm") if icon_name else ""}{esc(text)}</span>'


def failure_badge(ftype: str, glow: bool = True) -> str:
    ftype = ftype if ftype in theme.FAILURE_COLORS else "UNKNOWN"
    label = theme.FAILURE_LABELS.get(ftype, ftype)
    return (f'<span class="ms-badge-ft ms-ft-{ftype}{" glow" if glow else ""}" title="{esc(ftype)}">'
            f'<span class="ms-dot"></span>{esc(label)}</span>')


def status_pill(status: str) -> str:
    tone = theme.STATUS_TONES.get(status, "neutral")
    label = theme.STATUS_LABELS.get(status, str(status).replace("_", " ").capitalize())
    dot = '<span class="ms-dot live"></span>' if status in ("open", "auto-opened") else '<span class="ms-dot"></span>'
    return f'<span class="ms-status ms-tone-{tone} st-{esc(status)}">{dot}{esc(label)}</span>'


def section_header(title: str, subtitle: str | None = None, icon_name: str | None = None, right_html: str = "") -> str:
    sub = f'<div class="ms-section-sub">{esc(subtitle)}</div>' if subtitle else ""
    return (f'<div class="ms-section"><div><div class="ms-section-title">{icon(icon_name) if icon_name else ""}'
            f'{esc(title)}</div>{sub}</div><div>{right_html}</div></div>')


def kicker(text: str) -> str:
    return f'<div class="ms-kicker">{esc(text)}</div>'


def empty_state(icon_name: str, title: str, body: str, hint: str | None = None) -> str:
    h = f'<div class="ms-empty-hint">{esc(hint)}</div>' if hint else ""
    return (f'<div class="ms-empty"><div class="ms-empty-icon">{icon(icon_name)}</div>'
            f'<div class="ms-empty-title">{esc(title)}</div><div class="ms-empty-body">{esc(body)}</div>{h}</div>')


def skeleton(kind: str = "cards", n: int = 3) -> str:
    if kind == "answer":
        return ('<div class="ms-skel-wrap"><div class="ms-skel" style="height:22px;width:38%"></div>'
                '<div class="ms-skel" style="height:64px"></div><div class="ms-skel" style="height:18px;width:22%"></div></div>')
    if kind == "timeline":
        rows = "".join('<div style="display:grid;grid-template-columns:28px 1fr;gap:12px"><div class="ms-skel" '
                       'style="height:28px;border-radius:50%"></div><div class="ms-skel" style="height:44px"></div></div>'
                       for _ in range(n))
        return f'<div class="ms-skel-wrap">{rows}</div>'
    if kind == "chart":
        return '<div class="ms-skel" style="height:260px;border-radius:14px"></div>'
    if kind == "line":
        return '<div class="ms-skel" style="height:16px;width:60%"></div>'
    cells = "".join('<div class="ms-skel" style="height:112px;border-radius:14px"></div>' for _ in range(n))
    return f'<div class="ms-skel-grid">{cells}</div>'


# ------------------------------------------------------------------ hero & metrics

def hero(status: dict) -> str:
    ok = status.get("bank_ok", True)
    bank = (f'<span class="ms-pill ms-tone-success" title="Main memory bank"><span class="ms-dot live"></span>Hindsight connected '
            f'<code>{esc(status.get("bank_id"))}</code></span>') if ok else (
        f'<span class="ms-pill ms-tone-danger" title="{esc(status.get("bank_error") or "")}"><span class="ms-dot live"></span>'
        f'Hindsight unreachable</span>')
    auto = status.get("auto_mode")
    auto_pill = (f'<span class="ms-pill {"ms-tone-accent" if auto else ""}">{icon("zap", "sm")}Auto mode '
                 f'<b>{"on" if auto else "off"}</b></span>')
    n_open = int(status.get("open_incidents") or 0)
    open_pill = (f'<span class="ms-pill {"ms-tone-warning" if n_open else ""}"><span class="ms-dot{" live" if n_open else ""}">'
                 f'</span><b>{n_open}</b> incident{"s" if n_open != 1 else ""} open</span>')
    n_rules = status.get("rules")
    rules_pill = (f'<span class="ms-pill">{icon("sparkles", "sm")}rules <b>—</b></span>' if n_rules is None else
                  f'<span class="ms-pill {"ms-tone-accent" if n_rules else ""}">{icon("sparkles", "sm")}<b>{int(n_rules)}</b> '
                  f'rule{"s" if n_rules != 1 else ""} learned</span>')
    return (
        '<section class="ms-hero"><div class="ms-hero-glow"></div><div class="ms-hero-line"></div>'
        '<div class="ms-hero-inner"><div class="ms-brand">'
        f'<div class="ms-logo">{icon("activity")}</div><div>'
        '<div class="ms-brand-row"><div class="ms-title">Memory SRE</div>'
        f'<span class="ms-chip ms-tone-neutral">{icon("layers", "sm")}Built on Hindsight</span></div>'
        '<p class="ms-tagline">Find the memory that made your agent wrong — and fix it.</p></div></div>'
        f'<div class="ms-hero-pills">{bank}{auto_pill}{open_pill}{rules_pill}</div></div></section>')


_METRIC_TONES = {"accent": ("#B9B8FF", "rgba(108,106,246,.12)", "rgba(142,140,255,.35)", "rgba(142,140,255,.7)"),
                 "success": ("#86EFBC", "rgba(61,214,140,.1)", "rgba(61,214,140,.32)", "rgba(61,214,140,.7)"),
                 "warning": ("#FFC56B", "rgba(245,165,36,.1)", "rgba(245,165,36,.32)", "rgba(245,165,36,.7)"),
                 "info": ("#8CCBFF", "rgba(62,166,255,.1)", "rgba(62,166,255,.3)", "rgba(62,166,255,.7)")}


def _count(value: int, start: int = 0, i: int = 0, cls: str = "") -> str:
    return f'<span class="ms-count {cls}" style="--from:{int(start)};--to:{int(value)};--i:{i}" aria-label="{int(value)}"></span>'


def metric_card(card: dict) -> str:
    """{icon, label, value, start, value2, start2, suffix, note, tone, i}; value None → an em dash."""
    fg, bg, bd, line = _METRIC_TONES.get(card.get("tone", "accent"), _METRIC_TONES["accent"])
    i = int(card.get("i", 0))
    suffix = f'<span class="unit">{esc(card.get("suffix"))}</span>' if card.get("suffix") else ""
    if card.get("value") is None:
        value = '<span class="ms-muted">—</span>'
    elif card.get("value2") is not None:
        value = (_count(card["value"], card.get("start", 0), i, "bad") + suffix + '<span class="to">→</span>'
                 + _count(card["value2"], card.get("start2", 0), i, "good") + suffix)
    else:
        value = _count(card["value"], card.get("start", 0), i) + suffix
    return (f'<div class="ms-metric" style="--i:{i};--mc:{line}"><div class="ms-metric-top">'
            f'<span class="ms-metric-icon" style="color:{fg};background:{bg};border-color:{bd}">{icon(card.get("icon", "activity"))}</span>'
            f'{esc(card.get("label"))}</div><div class="ms-metric-value">{value}</div>'
            f'<div class="ms-metric-note">{esc(card.get("note"))}</div></div>')


def metric_cards(cards: list[dict]) -> str:
    inner = "".join(metric_card({**c, "i": c.get("i", k)}) for k, c in enumerate(cards))
    return f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px">{inner}</div>'


# ------------------------------------------------------------------ console

def _initials(name: str) -> str:
    words = [w for w in re.split(r"\s+", str(name or "").strip()) if w[:1].isalnum()]
    return (("".join(w[0] for w in words[:2])) or "?").upper()


def _words(text: str) -> str:
    out, k = [], 0
    for para in str(text or "").split("\n"):
        ws = []
        for w in para.split():
            ws.append(f'<span class="w" style="--i:{k}">{esc(w)}</span>')
            k += 1
        out.append(" ".join(ws))
    return "<br>".join(out)


def answer_card(view: dict, reveal: bool) -> str:
    name = view.get("customer_name") or ""
    body = _words(view.get("answer")) if reveal else esc(view.get("answer")).replace("\n", "<br>")
    short = view.get("short_answer")
    foot = ([f'<span class="ms-label">Short answer</span>{chip(short, "accent")}'] if short else []) + [
        chip(view.get("answer_id"), "neutral", mono=True)]
    if view.get("memories") is not None:
        foot.append(f'<span class="ms-muted" style="font-size:12px">· answered from {int(view["memories"])} '
                    f'recalled memor{"y" if view["memories"] == 1 else "ies"}</span>')
    watch = ""
    for f in view.get("watch") or []:
        outcome = {"prevented": "prevented", "pending": "awaiting approval", "dismissed": "dismissed after checking"}.get(
            f.get("status"), f.get("status"))
        watch += (f'<div class="ms-watch">{icon("eye")}<div><b>Watch</b> · learned rule '
                  f'<span class="ms-mono">{esc(f.get("rule_id"))}</span> fired on this answer → '
                  f'{esc(f.get("name_a"))} ≡ {esc(f.get("name_b"))} (shared <span class="ms-mono">{esc(f.get("shared_domain"))}</span>): '
                  f'<b>{esc(outcome)}</b>{" as " + esc(f.get("incident_id")) if f.get("incident_id") else ""}</div></div>')
    return (f'<article class="ms-answer"><header class="ms-answer-head"><span class="ms-avatar">{esc(_initials(name))}</span>'
            f'<div class="ms-answer-who"><div class="ms-answer-cust">Support asked about {esc(name)}</div>'
            f'<div class="ms-answer-q">{esc(view.get("question"))}</div></div></header>'
            f'<div class="ms-answer-body{" reveal" if reveal else ""}">{body}</div>'
            f'<footer class="ms-answer-foot">{"".join(foot)}</footer>{watch}</article>')


def memory_card(m, variant: str = "plain", own_tag: str | None = None, foreign_tags=(), struck: bool = False,
                animate: bool = False, note: str | None = None, i: int = 0) -> str:
    text, meta = split_memory_text(_get(m, "text", ""))
    source = _get(m, "source") or ""
    label, ic = SOURCES.get(source, (source.replace("_", " ").capitalize() or "Memory", "database"))
    doc = str(_get(m, "document_id") or "")
    if doc.startswith("sre-alias-"):
        label, ic = "Identity link", "link"
    tags = [t for t in (_get(m, "tags") or []) if str(t).startswith("customer:")]
    foreign = set(foreign_tags or ())
    tag_html = "".join(
        f'<span class="ms-tag{" foreign" if (t in foreign or (own_tag and t != own_tag and variant == "evidence")) else ""}">'
        f'{icon("tag", "sm")}{esc(t)}</span>' for t in tags)
    kind = ""
    if variant == "culprit":
        kind = f'<span class="ms-mem-kind">{icon("target", "sm")}Culprit memory</span>'
        if struck:
            kind += f' <span class="ms-stamp">{icon("ban", "sm")}Invalidated</span>'
    elif variant == "evidence":
        kind = f'<span class="ms-mem-kind">{icon("search", "sm")}Contradicting evidence</span>'
    involving = f'<span class="ms-mem-meta">{icon("users", "sm")} {esc(meta["Involving"])}</span>' if meta.get("Involving") else ""
    date = _get(m, "date") or meta.get("When") or ""
    note_html = f'<div class="ms-mem-note">{note}</div>' if note else ""
    cls = f"ms-mem {variant}" + (" struck" if struck else "") + (" anim" if struck and animate else "")
    mid = str(_get(m, "id") or "")
    return (f'<div class="{cls}" style="--i:{i}"><div class="ms-mem-top"><span class="ms-src">{icon(ic)}{esc(label)}</span>'
            f'{f"<span class=ms-date>{esc(date)}</span>" if date else ""}</div>'
            f'{f"<div>{kind}</div>" if kind else ""}<div class="ms-mem-text" title="{esc(text)}"><span class="t">{esc(text)}</span></div>{note_html}'
            f'<div class="ms-mem-foot"><div class="ms-tags">{tag_html}{involving}</div>'
            f'<span class="ms-id" title="{esc(mid)}">{esc(short_id(mid))}</span></div></div>')


def memory_cards(mems, title: str | None = None) -> str:
    mems = list(mems or [])
    if not mems:
        return empty_state("database", "No memories were used", "The agent answered without recalling a memory.")
    head = section_header(title, None, "database") if title else ""
    cards = "".join(memory_card(m, i=k) for k, m in enumerate(mems))
    return f'{head}<div class="ms-mem-grid">{cards}</div>'


def customer_panel(name: str, key: str, tags: list[str], linked: list[str], stats: dict | None = None) -> str:
    tag_html = "".join(f'<span class="ms-tag">{icon("tag", "sm")}{esc(t)}</span>' for t in tags)
    linked_html = "".join(chip(n, "warning", icon_name="link") for n in linked)
    rows = "".join(f'<div class="ms-kv"><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in (stats or {}).items())
    return (f'<div class="ms-side-card"><div class="ms-side-title">{icon("user")}Customer record</div>'
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px"><span class="ms-avatar">{esc(_initials(name))}</span>'
            f'<div><div style="font-weight:640;color:var(--text)">{esc(name)}</div><div class="ms-muted ms-mono">{esc(key)}</div></div></div>'
            f'<div class="ms-kicker">Memory tags</div><div class="ms-tags">{tag_html}</div>'
            + (f'<div class="ms-kicker" style="margin-top:12px">Linked identities</div><div class="ms-tags">{linked_html}</div>' if linked else "")
            + (f'<div style="margin-top:12px">{rows}</div>' if rows else "") + '</div>')


def watch_panel(rules_count: int, auto_mode: bool) -> str:
    if rules_count:
        body = (f'After every answer, Watch runs <b>{rules_count}</b> learned detection rule{"s" if rules_count != 1 else ""} '
                f'on the recalled memories and investigates only if one fires.')
        tone, state = "success", "Watch is on"
    else:
        body = "No detection rules yet. Memory SRE writes its first rule in the post-mortem of the first verified fix."
        tone, state = "neutral", "Watch is waiting"
    return (f'<div class="ms-side-card"><div class="ms-side-title">{icon("eye")}{esc(state)}</div>'
            f'<div style="color:var(--text-2);font-size:13px;line-height:1.55">{body}</div>'
            f'<div style="margin-top:12px;display:flex;gap:6px;flex-wrap:wrap">{chip("Auto mode on" if auto_mode else "Auto mode off", "accent" if auto_mode else "neutral", icon_name="zap")}'
            f'{chip(f"{rules_count} rule" + ("s" if rules_count != 1 else ""), tone, icon_name="sparkles")}</div></div>')


# ------------------------------------------------------------------ agent trace

def _args_html(args: dict) -> str:
    out = []
    for k, v in (args or {}).items():
        val = v if isinstance(v, (int, float)) else f'"{_clip(v, 60)}"' if isinstance(v, str) else _clip(v, 60)
        out.append(f'<span class="ms-arg" title="{esc(v)}"><i>{esc(k)}=</i>{esc(val)}</span>')
    return "".join(out)


_STATE_ICONS = {"thinking": "bot", "running": None, "done": "check", "rejected": "shield-alert", "invalid": "x",
                "error": "x", "verdict": "shield", "accepted": "check", "fallback": "branch"}


def trace_step(step: dict, n: int, state: str, *, animate: bool = True, last: bool = False,
               verdict: dict | None = None, stagger: bool = True) -> str:
    """One timeline row. state: thinking | running | done | rejected | invalid | error | verdict | accepted | fallback."""
    tool = step.get("tool") or ""
    thought = step.get("thought") or ""
    ic = _STATE_ICONS.get(state) or TOOL_ICONS.get(tool, "cpu")
    label, body = tool, ""
    if state == "thinking":
        label = ""
        body = '<div class="ms-thought shimmer">Thinking about the next step…</div>'
    elif state in ("rejected",):
        label = "evidence gate"
        body = (f'<div class="ms-thought">{esc(thought) or "Proposed a verdict"}</div>'
                f'<div class="ms-result"><div class="ms-clamp">Pushed back: {esc(_clip(step.get("result_summary"), 360))}</div></div>')
    elif state in ("invalid", "error"):
        label = "invalid reply" if state == "invalid" else "failed"
        body = f'<div class="ms-result"><div class="ms-clamp">{esc(_clip(step.get("result_summary"), 300))}</div></div>'
    elif state == "fallback":
        forced = bool(step.get("forced"))
        label = "fixed pipeline (forced)" if forced else "fixed pipeline"
        body = (('<div class="ms-thought">The investigator agent is switched off, so the fixed pipeline diagnosed it.</div>'
                 if forced else '<div class="ms-thought">The agent could not finish within its bounds, so the fixed '
                 'pipeline diagnosed the incident.</div>') + (f'<div class="ms-result"><div class="ms-clamp">{esc(step.get("result_summary"))}</div></div>'
                                                  if step.get("result_summary") else ""))
    elif state == "verdict":
        label = "verdict"
        body = (f'<div class="ms-thought">{esc(thought)}</div>'
                '<div class="ms-thought shimmer" style="margin-top:4px">Checking the evidence gates…</div>')
    elif state == "accepted":
        label = "verdict"
        v = verdict or {}
        parts = [failure_badge(v["failure_type"], glow=True)] if v.get("failure_type") else []
        if v.get("confidence") is not None:
            parts.append(chip(f"confidence {_pct(v['confidence'])}", "success"))
        parts.append(chip("evidence gates passed", "success", icon_name="shield-check"))
        body = f'<div class="ms-thought">{esc(thought)}</div><div class="ms-verdict">{"".join(parts)}</div>'
    else:
        result = step.get("result_summary")
        body = (f'<div class="ms-thought">{esc(thought)}</div>' if thought else "") + (
            f'<div class="ms-result" title="{esc(result)}"><div class="ms-clamp">{esc(_clip(result, 420))}</div></div>'
            if (state == "done" and result) else "")
        if state == "running":
            body += '<div class="ms-thought shimmer" style="margin-top:4px">Running…</div>'
    tool_chip = (f'<span class="ms-tool">{icon(TOOL_ICONS.get(tool, "cpu"))}{esc(label)}</span>' if label else "")
    args = _args_html(step.get("args")) if state in ("running", "done") else ""
    cls = f"ms-step {state}" + (" anim" if animate else "") + (" last" if last else "")
    return (f'<li class="{cls}" style="--i:{n if stagger else 0}"><div class="ms-node">{icon(ic)}</div><div class="ms-step-body">'
            f'<div class="ms-step-row"><span class="ms-step-n">{n + 1:02d}</span>{tool_chip}{args}</div>{body}</div></li>')


def trace_memory_badges(inv: dict) -> list[str]:
    badges = []
    pb = (inv or {}).get("used_playbook_id")
    if pb:
        src = str(pb).split("playbook-", 1)[-1]
        badges.append(f"Used playbook from {src}")
    for r in (inv or {}).get("used_rules") or []:
        if r:
            badges.append(f"Applied {r}")
    if (inv or {}).get("fallback"):
        badges.append("Fell back to the fixed pipeline")
    return badges


def trace_divider(label: str) -> str:
    return f'<div class="ms-trace-divider">{icon("branch", "sm")}<span>{esc(label)}</span></div>'


def trace_folded(n: int, earlier: bool = False) -> str:
    text = f"+{n} earlier step{'s' if n != 1 else ''}" if earlier else f"{n} step{'s' if n != 1 else ''} · done"
    return f'<div class="ms-folded">{icon("layers", "sm")}{esc(text)}</div>'


def trace_note(text: str, shimmer: bool = False) -> str:
    if shimmer:
        return (f'<div class="ms-trace-note">{icon("radar", "sm")}<span class="ms-thought shimmer" style="margin:0">'
                f'{esc(text)}</span></div>')
    return f'<div class="ms-trace-note">{icon("shield-check", "sm")}{esc(text)}</div>'


def trace_pipeline_summary(inc: dict) -> str:
    head = trace_header("Diagnosed by the fixed pipeline", f"{inc.get('id')} · {inc.get('customer_name')}",
                        stats=[], icon_name="branch")
    return (f'<section class="ms-trace">{head}<div class="ms-trace-note">{failure_badge(inc.get("failure_type") or "UNKNOWN")}'
            f'<span>{esc(inc.get("root_cause"))}</span></div></section>')


def _badge_html(b: str) -> str:
    if b.startswith("Used playbook"):
        return chip(b, "accent", icon_name="book-open", glow=True)
    if b.startswith("Applied "):
        return chip(b, "accent", icon_name="sparkles", glow=True)
    return chip(b, "warning", icon_name="branch")


def trace_header(title: str, subtitle: str = "", *, live: bool = False, stats: list[str] | None = None,
                 badges: list[str] | None = None, icon_name: str = "bot") -> str:
    """stats: preformatted chip texts, e.g. ["6 steps", "7 LLM calls"]."""
    live_b = '<span class="ms-live-badge"><span class="ms-dot"></span>LIVE</span>' if live else ""
    sub = f'<span class="ms-trace-sub">{esc(subtitle)}</span>' if subtitle else ""
    st_html = "".join(chip(v, "neutral") for v in (stats or []) if v)
    b_html = "".join(_badge_html(b) for b in badges or [])
    return (f'<header class="ms-trace-head"><div class="ms-trace-title">{icon(icon_name)}{esc(title)}{live_b}{sub}</div>'
            f'<div class="ms-trace-stats">{st_html}</div></header>'
            + (f'<div class="ms-trace-badges">{b_html}</div>' if b_html else ""))


def step_state(tool: str) -> str:
    return {"verdict_rejected": "rejected", "invalid": "invalid", "final": "accepted"}.get(tool, "done")


def trace_timeline(inv: dict, *, animate: bool = False, title: str = "Agent trace", compact: bool = False,
                   subtitle: str = "") -> str:
    inv = inv or {}
    steps = list(inv.get("steps") or [])
    stats = [plural(len(steps), "step"),
             plural(inv.get("llm_calls"), "LLM call") if inv.get("llm_calls") is not None else None,
             f"{inv.get('duration_s')}s" if inv.get("duration_s") is not None else None,
             f"{_pct(inv['confidence'])} confidence" if inv.get("confidence") is not None else None]
    head = trace_header(title, subtitle or ("investigator agent" if inv.get("agent") != "patrol" else "patrol agent"),
                        stats=stats, badges=trace_memory_badges(inv))
    verdict = {"failure_type": inv.get("agent_failure_type"), "confidence": inv.get("confidence")}
    rows = []
    shown = steps if not compact else steps[-6:]
    offset = len(steps) - len(shown)
    for k, s in enumerate(shown):
        state = step_state(s.get("tool"))
        last = (k == len(shown) - 1) and not inv.get("fallback")
        rows.append(trace_step(s, k + offset, state, animate=animate, last=last,
                               verdict=verdict if state == "accepted" else None))
    if inv.get("fallback"):
        rows.append(trace_step({"tool": "fallback", "result_summary": inv.get("fallback_reason") or ""}, len(steps), "fallback",
                               animate=animate, last=True))
    if not rows:
        rows.append('<li class="ms-step last"><div class="ms-node">' + icon("cpu") + '</div><div class="ms-step-body">'
                    '<div class="ms-thought">No steps recorded.</div></div></li>')
    return f'<section class="ms-trace">{head}<ol class="ms-steps">{"".join(rows)}</ol></section>'


def patrol_candidate_header(c: dict) -> str:
    from memsre import catalog  # names only
    a, b = c.get("a"), c.get("b")
    try:
        na, nb = catalog.customer_name(a), catalog.customer_name(b)
    except Exception:
        na, nb = a, b
    values = ", ".join(c.get("values") or [c.get("value") or ""])
    return (f'<div class="ms-cand">{icon("radar")}<b>{esc(na)} ≡ {esc(nb)}</b>'
            f'{chip(values, "neutral", mono=True, icon_name="mail")}{chip(c.get("rule_id") or "rule", "accent", mono=True, icon_name="sparkles")}'
            f'<span class="ms-muted" style="font-size:12px">rule fired · verifying with the agent</span></div>')


def patrol_outcome(f: dict) -> str:
    status = f.get("status")
    if status == "prevented":
        body = chip("Prevented — linked before any wrong answer", "success", icon_name="check-circle")
    elif status == "pending":
        body = chip("Awaiting approval", "warning", icon_name="clock")
    elif status == "proposed":
        body = chip("Proposed", "accent")
    else:
        body = chip("Dismissed after checking", "neutral", icon_name="x-circle")
    conf = chip(f"confidence {_pct(f.get('confidence'))}", "neutral")
    inc = chip(f["incident_id"], "neutral", mono=True) if f.get("incident_id") else ""
    reason = f'<span class="ms-muted">{esc(_clip(f.get("reason"), 160))}</span>' if f.get("reason") else ""
    return f'<div class="ms-outcome">{body}{conf}{inc}{reason}</div>'


# ------------------------------------------------------------------ incidents

def _trigger(inc: dict) -> str:
    return TRIGGER_LABELS.get(inc.get("trigger"), str(inc.get("trigger") or "").capitalize())


def incident_card(inc: dict, active: bool) -> str:
    inv = inc.get("investigation") or {}
    steps = len(inv.get("steps") or [])
    trig = "Support" if inc.get("trigger") is None else _trigger(inc)
    meta = [failure_badge(inc.get("failure_type"), glow=False), f'<span>{esc(trig)}</span>']
    if inc.get("created_at"):
        meta.append(f'<span>{esc(time_ago(inc["created_at"]))}</span>')
    if steps:
        meta.append(f'<span>{plural(steps, "step")}</span>')
    return (f'<div class="ms-inc-card ms-card-click{" active" if active else ""}"><div class="ms-inc-top">'
            f'<span class="ms-inc-id">{esc(inc.get("id"))}</span>{status_pill(inc.get("status"))}</div>'
            f'<div class="ms-inc-cust">{esc(inc.get("customer_name"))}</div><div class="ms-inc-meta">{"".join(meta)}</div></div>')


def case_header(inc: dict) -> str:
    ft = inc.get("failure_type") if inc.get("failure_type") in theme.FAILURE_COLORS else "UNKNOWN"
    inv = inc.get("investigation") or {}
    meta = [chip(_trigger(inc), "neutral", icon_name="radar" if inc.get("trigger") else "message")]
    if inc.get("created_at"):
        meta.append(chip(f"opened {time_ago(inc['created_at'])}", "neutral", icon_name="clock"))
    if inv:
        who = "patrol agent" if inv.get("agent") == "patrol" else "investigator agent"
        if inv.get("fallback"):
            meta.append(chip("fixed pipeline (agent fell back)", "warning", icon_name="branch"))
        else:
            meta.append(chip(f"{who} · {len(inv.get('steps') or [])} steps · {inv.get('llm_calls')} LLM calls · "
                             f"{inv.get('duration_s')}s", "accent", icon_name="bot"))
    elif inc.get("question") is not None:
        meta.append(chip("fixed pipeline", "neutral", icon_name="branch"))
    if inc.get("policy") and inc.get("status") not in ("open", "auto-opened"):
        meta.append(policy_chip(inc))
    return (f'<div class="ms-case-head" style="--c:{theme.FAILURE_COLORS[ft]}"><div class="ms-case-row">'
            f'<span class="ms-case-id">{esc(inc.get("id"))}</span>{failure_badge(ft, glow=True)}{status_pill(inc.get("status"))}</div>'
            f'<div class="ms-case-cust">Customer <b>{esc(inc.get("customer_name"))}</b> '
            f'<span class="ms-mono ms-muted">customer:{esc(inc.get("customer_key"))}</span></div>'
            f'<div class="ms-case-meta">{"".join(meta)}</div></div>')


def what_went_wrong(inc: dict) -> str:
    if inc.get("question") is None:
        rule = inc.get("rule_id")
        by = f' using rule <span class="ms-mono">{esc(rule)}</span>' if rule else ""
        return (f'<div class="ms-banner success">{icon("shield-check")}<div><b>Caught before any wrong answer.</b> '
                f'Found by {esc(_trigger(inc).lower())}{by}; no customer saw a wrong answer.</div></div>')
    healed = inc.get("status") == "fixed"
    return ('<div class="ms-www">'
            f'<div class="ms-www-card" style="--i:0"><div class="ms-label">{icon("message", "sm")}Customer asked</div>'
            f'<div class="ms-www-text">{esc(inc.get("question"))}</div></div>'
            f'<div class="ms-www-card wrong{" healed" if healed else ""}" style="--i:1"><div class="ms-label">{icon("x-circle", "sm")}Agent answered</div>'
            f'<div class="ms-www-text">{esc(inc.get("wrong_answer"))}</div></div>'
            f'<div class="ms-www-card truth" style="--i:2"><div class="ms-label">{icon("check-circle", "sm")}Support rep\'s correction</div>'
            f'<div class="ms-www-text">{esc(inc.get("correction"))}</div></div></div>')


def identity_link(inc: dict) -> str:
    ident = inc.get("identity") or {}
    if not ident:
        return ""
    own_tag = f"customer:{inc.get('customer_key')}"
    same = ident.get("same_customer")
    node = f'{icon("equal" if same else "x", "sm")}{esc(_pct(ident.get("confidence")))}'
    cap = "same customer" if same else "different customers"
    evidence = ident.get("linking_evidence") or ""
    quote = f'<div class="ms-quote">{icon("link", "sm")} {_highlight_emails(evidence)}</div>' if evidence else ""
    reason = f'<div class="ms-idl-reason">{esc(ident.get("reason"))}</div>' if ident.get("reason") else ""
    return (f'<div class="ms-idl"><div class="ms-kicker" style="margin-top:0">{icon("link", "sm")} Identity link · compared by the agent</div>'
            '<div class="ms-idl-row">'
            f'<div class="ms-entity"><div class="ms-entity-kind">{icon("user", "sm")}Support knows them as</div>'
            f'<div class="ms-entity-name">{esc(inc.get("customer_name"))}</div><span class="ms-tag">{icon("tag", "sm")}{esc(own_tag)}</span></div>'
            f'<div class="ms-conn{"" if same else " diff"}"><span class="ms-conn-node">{node}</span>'
            f'<span class="ms-conn-cap">{cap}</span></div>'
            f'<div class="ms-entity b"><div class="ms-entity-kind">{icon("receipt", "sm")}Billing knows them as</div>'
            f'<div class="ms-entity-name">{esc(ident.get("foreign_name"))}</div>'
            f'<span class="ms-tag foreign">{icon("tag", "sm")}{esc(ident.get("foreign_tag"))}</span></div>'
            f'</div>{quote}{reason}</div>')


_FT_EXPLAIN = {
    "RESOLUTION": "Identity split: the correct fact is stored under another name for the same customer, so scoped recall never saw it.",
    "FRESHNESS": "A newer fact superseded the memory the agent used, but only the outdated one was recalled.",
    "RECALL_MISS": "The correct fact exists under this customer but was not retrieved for this question.",
    "EXECUTION": "The right memory was retrieved and the answer was still wrong: a model or prompt problem, not memory.",
    "MISSING_KNOWLEDGE": "Memory never contained the correct fact.",
    "UNKNOWN": "No memory-level cause could be confirmed.",
}


def root_cause_card(inc: dict) -> str:
    ft = inc.get("failure_type") or "UNKNOWN"
    return (f'<div class="ms-banner info" style="align-items:flex-start">{icon("bulb")}<div><div style="display:flex;gap:8px;'
            f'align-items:center;flex-wrap:wrap;margin-bottom:4px"><b>Root cause</b>{failure_badge(ft, glow=False)}</div>'
            f'<div>{esc(inc.get("root_cause"))}</div><div class="ms-muted" style="margin-top:4px;font-size:12.5px">'
            f'{esc(_FT_EXPLAIN.get(ft, ""))}</div></div></div>')


def policy_summary(policy: dict) -> str:
    p = policy or {}
    thr = p.get("auto_apply_min_confidence", 0.85)
    chips = [chip(f"prevented fixes: {'auto-apply' if p.get('prevented') == 'auto' else 'need approval'}",
                  "accent" if p.get("prevented") == "auto" else "warning", icon_name="radar"),
             chip(f"reactive fixes: {'auto-apply' if p.get('reactive') == 'auto' else 'need approval'}",
                  "accent" if p.get("reactive") == "auto" else "neutral", icon_name="message"),
             chip(f"confidence ≥ {_pct(thr)}", "neutral", icon_name="gauge"),
             chip("reversible fixes only", "neutral", icon_name="undo"), chip("every write audited", "neutral", icon_name="clipboard")]
    if p.get("auto_patrol_after_fix"):
        chips.append(chip("patrol after every verified fix", "accent", icon_name="refresh"))
    return f'<div class="ms-policy">{"".join(chips)}</div>'


def _blast_label(n) -> str:
    if not n:
        return "no customer saw a wrong answer"
    return f"earlier answer{'s' if n != 1 else ''} used this memory"


def blast_radius(n: int, answer_ids: list[str]) -> str:
    ids = "".join(chip(a, "neutral", mono=True) for a in (answer_ids or [])[:6])
    return (f'<div class="ms-blast"><div class="ms-label">{icon("target", "sm")} Blast radius</div>'
            f'<div class="ms-blast-n{' zero' if not n else ''}">{_count(int(n or 0))}</div>'
            f'<div class="ms-blast-label">{_blast_label(n)}</div>'
            f'<div class="ms-tags" style="margin-top:4px">{ids}</div></div>')


def fix_plan(inc: dict) -> str:
    items = inc.get("recommended_fix") or []
    lis = "".join(f'<li><span class="ms-plan-n">{k + 1}</span><span>{esc(clean_meta(t))}</span></li>' for k, t in enumerate(items))
    chips = [policy_chip(inc, long=True)] if inc.get("policy") else []
    chips.append(chip("reversible", "neutral", icon_name="undo"))
    chips.append(chip("audited", "neutral", icon_name="clipboard"))
    body = f"<ol>{lis}</ol>" if lis else '<div class="ms-muted" style="margin-top:8px">No automatic fix for this failure type.</div>'
    return (f'<div class="ms-plan"><div class="ms-section-title">{icon("wrench")}Recommended fix</div>{body}'
            f'<div class="ms-plan-policy">{"".join(chips)}</div></div>')


def policy_chip(inc: dict, long: bool = False) -> str:
    """What the autonomy policy decided, phrased for the incident's current state."""
    pol = inc.get("policy") or {}
    applied = inc.get("status") in ("fixed", "prevented", "reverted") and bool(inc.get("applied_actions") or inc.get("status") == "reverted")
    conf = _pct(pol.get("confidence"))
    if pol.get("decision") == "auto":
        return chip(f"Auto-applied by policy · confidence {conf} · reversible" if long else "auto-applied by policy",
                    "success", icon_name="zap")
    if applied or inc.get("status") == "reverted":
        return chip("Approved by a human, then applied" if long else "approved by a human", "success", icon_name="user")
    if inc.get("status") in ("open", "auto-opened"):
        return chip(f"Awaiting approval — {pol.get('reason') or 'policy'}" if long else "awaiting approval",
                    "warning", icon_name="shield")
    return chip("policy: " + str(pol.get("decision") or "—"), "neutral", icon_name="shield")


def healed_banner(inc: dict, animate: bool) -> str:
    ver = inc.get("verification") or {}
    n = len(ver.get("checks") or [])
    prevented = inc.get("status") == "prevented"
    title = "Linked before any wrong answer" if prevented else "Memory healed"
    sub = (f"Verified by re-asking {n} question{'s' if n != 1 else ''} · attempt {ver.get('attempt', 1)} · every change is reversible"
           if n else "Reversible fix applied in Hindsight · audited")
    return (f'<div class="ms-heal{" anim" if animate else ""}"><div class="ms-heal-icon">{icon("check")}</div>'
            f'<div><div class="ms-heal-title">{esc(title)}</div><div class="ms-heal-sub">{esc(sub)}</div></div></div>')


def verification(ver: dict, animate: bool) -> str:
    if not ver or ver.get("skipped"):
        return ""
    rows = []
    for k, c in enumerate(ver.get("checks") or []):
        ok = bool(c.get("consistent"))
        flip = (f'<div class="ms-flip{" anim" if animate and ok else ""}{"" if ok else " fail"}" style="--i:{k}"><div class="ms-flip-in">'
                f'<div class="ms-face front">{icon("x")}</div><div class="ms-face back">{icon("check")}</div></div></div>')
        rows.append(f'<div class="ms-check">{flip}<div><div class="ms-check-q">{esc(c.get("question"))}</div>'
                    f'<div class="ms-check-r">{esc(_clip(c.get("reason"), 180))}</div></div>'
                    f'{chip(c.get("short_answer") or "—", "success" if ok else "danger")}</div>')
    tone = "success" if ver.get("passed") else "warning"
    head = chip(f"Attempt {ver.get('attempt', 1)}: {ver.get('reason') or ''}", tone,
                icon_name="shield-check" if ver.get("passed") else "alert")
    return (f'<div><div class="ms-section" style="margin-bottom:4px"><div class="ms-section-title">{icon("refresh")}'
            f'Verification · re-asked and judged</div><div>{head}</div></div><div class="ms-checks">{"".join(rows)}</div></div>')


def rollback_cards(hypotheses: list[dict], needs_human: bool) -> str:
    cards = []
    hyps = hypotheses or []
    for k, h in enumerate(hyps):
        failed = h.get("failed_checks") or []
        body = "; ".join(f"“{_clip(c.get('question'), 70)}” → {c.get('short_answer')}" for c in failed[:3]) or "re-asked answers were still wrong"
        nxt = ("" if (k == len(hyps) - 1 and needs_human) else
               f'<div class="ms-rb-next">{icon("arrow-right", "sm")}Next hypothesis: the investigator re-opened the case '
               f'with this attempt ruled out.</div>')
        cards.append(f'<div class="ms-rollback"><div class="ms-rb-title">{icon("undo")}Attempt {esc(h.get("attempt"))} · '
                     f'{failure_badge(h.get("failure_type") or "UNKNOWN", glow=False)} rolled back automatically</div>'
                     f'<div class="ms-rb-body">Still wrong after the fix: {esc(body)}</div>{nxt}</div>')
    if needs_human:
        cards.append(f'<div class="ms-rollback" style="border-color:rgba(240,97,109,.45);box-shadow:inset 3px 0 0 var(--danger)">'
                     f'<div class="ms-rb-title" style="color:#FFC9CE">{icon("user")}A human needs to look at this</div>'
                     '<div class="ms-rb-body">No hypothesis verified, so every change was rolled back. Nothing is left applied.</div></div>')
    return "".join(cards)


def before_after(inc: dict) -> str:
    re_ = inc.get("reask") or {}
    if not re_:
        return ""
    return ('<div class="ms-ba">'
            f'<div class="ms-ba-card before"><div class="ms-label"><span>{icon("x-circle", "sm")} Before</span>'
            f'{chip(inc.get("wrong_short_answer") or "—", "danger")}</div>'
            f'<div class="ms-ba-text">{esc(inc.get("wrong_answer"))}</div></div>'
            f'<div class="ms-ba-card after"><div class="ms-label"><span>{icon("check-circle", "sm")} After re-ask</span>'
            f'{chip(re_.get("short_answer") or "—", "success")}</div>'
            f'<div class="ms-ba-text">{esc(re_.get("answer"))}</div></div></div>')


def applied_actions(actions: list[dict]) -> str:
    rows = []
    for a in actions or []:
        kind = a.get("kind")
        if kind == "alias":
            ic, text, ref = "link", "Linked identities", f"{a.get('a')} ≡ {a.get('b')}"
        elif kind == "retain_doc":
            ic, text, ref = "pin", "Retained in Hindsight", a.get("document_id")
        elif kind == "invalidate":
            ic, text, ref = "ban", "Invalidated superseded memory", short_id(a.get("memory_id")) + "…"
        else:
            ic, text, ref = "wrench", str(kind), ""
        rows.append(f'<div class="ms-action"><span class="ms-action-ic">{icon(ic)}</span><span>{esc(text)} '
                    f'<span class="ms-mono ms-muted">{esc(ref)}</span></span>{chip("reversible", "neutral", icon_name="undo")}</div>')
    if not rows:
        return ""
    return (f'<div><div class="ms-section-title" style="margin-bottom:8px">{icon("layers")}Applied in Hindsight</div>'
            f'<div class="ms-actions">{"".join(rows)}</div></div>')


# ------------------------------------------------------------------ autonomy

def approval_card(inc: dict, current_policy: dict | None = None) -> str:
    ident = inc.get("identity") or {}
    chips = [chip(inc.get("shared_value") or "", "neutral", mono=True, icon_name="mail") if inc.get("shared_value") else "",
             chip(inc.get("rule_id"), "accent", mono=True, icon_name="sparkles") if inc.get("rule_id") else "",
             chip(f"confidence {_pct(ident.get('confidence'))}", "neutral"), chip(inc.get("id"), "neutral", mono=True)]
    return (f'<div class="ms-approval"><div class="ms-approval-title">{icon("clock")}{esc(inc.get("customer_name"))} ≡ '
            f'{esc(ident.get("foreign_name"))}{"".join(chips)}</div>'
            f'<div class="ms-approval-body">{esc(_trigger(inc))} found this identity split before any wrong answer. '
            f'{_approval_note(current_policy)}</div>'
            + (f'<div class="ms-quote" style="margin-top:10px">{_highlight_emails(ident.get("linking_evidence") or "")}</div>'
               if ident.get("linking_evidence") else "") + '</div>')


def _approval_note(current_policy: dict | None) -> str:
    if (current_policy or {}).get("prevented") == "auto":
        return "It was held for approval under the policy at the time. Auto mode is now on — approve to apply it."
    return "The policy asks a human before linking it."


_FINDING_ICONS = {"prevented": ("check-circle", "success"), "pending": ("clock", "warning"),
                  "proposed": ("sparkles", "accent"), "dismissed": ("x-circle", "neutral")}


def finding_card(f: dict, i: int = 0, live_status: str | None = None) -> str:
    status = {"prevented": "prevented", "fixed": "prevented", "auto-opened": "pending", "rejected": "dismissed"}.get(
        live_status or "", f.get("status") or "dismissed")
    ic, tone = _FINDING_ICONS.get(status, ("radar", "neutral"))
    fg, bg, bd, _ = _METRIC_TONES.get(tone, ("#A1A7B3", "rgba(255,255,255,.04)", "rgba(255,255,255,.12)", ""))
    label = {"prevented": "prevented", "pending": "awaiting approval", "proposed": "proposed",
             "dismissed": "dismissed"}.get(status, status)
    path = " → ".join(s.get("tool") for s in ((f.get("investigation") or {}).get("steps") or []))
    chips = [chip(label, tone), chip(f.get("shared_domain") or f.get("value") or "", "neutral", mono=True, icon_name="mail"),
             chip(f"confidence {_pct(f.get('confidence'))}", "neutral")]
    if f.get("rule_id"):
        chips.append(chip(f["rule_id"], "accent", mono=True, icon_name="sparkles"))
    if f.get("incident_id"):
        chips.append(chip(f["incident_id"], "neutral", mono=True))
    return (f'<div class="ms-finding {esc(status)}" style="--i:{i}"><span class="ms-finding-ic" style="color:{fg};background:{bg};border-color:{bd}">'
            f'{icon(ic)}</span><div><div class="ms-finding-title">{esc(f.get("name_a"))} ≡ {esc(f.get("name_b"))}</div>'
            f'<div class="ms-finding-sub">{"".join(chips)}</div>'
            + (f'<div class="ms-finding-reason">{esc(f.get("reason"))}</div>' if f.get("reason") else "")
            + (f'<div class="ms-finding-reason ms-mono" style="font-size:11px">agent: {esc(path)}</div>' if path else "")
            + '</div><div></div></div>')


def proposal_card(p: dict, state: str) -> str:
    tone = {"prevented": "success", "rejected": "muted"}.get(state, "accent")
    label = {"prevented": "Prevented: linked before any wrong answer", "rejected": "Rejected: retained as a rule exception"}.get(
        state, "Proposed link")
    conf = chip("confidence " + _pct(p.get("confidence")), "neutral")
    shared = chip(p.get("shared_domain") or "", "neutral", mono=True, icon_name="mail")
    quote = (f'<div class="ms-quote">{_highlight_emails(p.get("linking_evidence") or "")}</div>'
             if p.get("linking_evidence") else "")
    return (f'<div class="ms-proposal {esc(state)}"><div class="ms-approval-title">{icon("link")}{esc(p.get("name_a"))} ≡ '
            f'{esc(p.get("name_b"))}{chip(label, tone)}</div><div class="ms-finding-sub" style="margin-top:8px">{shared}{conf}</div>'
            f'{quote}</div>')


_FEED_TONES = {"accent": ("#B9B8FF", "rgba(108,106,246,.12)", "rgba(142,140,255,.35)"),
               "success": ("#86EFBC", "rgba(61,214,140,.1)", "rgba(61,214,140,.32)"),
               "warning": ("#FFC56B", "rgba(245,165,36,.1)", "rgba(245,165,36,.32)"),
               "danger": ("#FF9AA3", "rgba(240,97,109,.1)", "rgba(240,97,109,.32)"),
               "info": ("#8CCBFF", "rgba(62,166,255,.1)", "rgba(62,166,255,.3)"),
               "neutral": ("#A1A7B3", "rgba(255,255,255,.04)", "rgba(255,255,255,.12)")}


def _clock(iso) -> str:
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return t.astimezone().strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return str(iso or "")[:8]


def activity_feed(items: list[dict], now: datetime | None = None, seen_ts: str | None = None) -> str:
    if not items:
        return empty_state("activity", "No activity yet", "Investigations, fixes, verifications, patrols and policy "
                           "decisions appear here as they happen.")
    rows = []
    for k, it in enumerate(items):
        fg, bg, bd = _FEED_TONES.get(it.get("tone", "neutral"), _FEED_TONES["neutral"])
        inc = chip(it["incident_id"], "neutral", mono=True) if it.get("incident_id") else ""
        new = seen_ts is not None and str(it.get("ts") or "") > seen_ts
        rows.append(f'<li class="ms-feed-item{" anim" if new else ""}" style="--i:{min(k, 12)}"><span class="ms-feed-ic" style="color:{fg};background:{bg};border-color:{bd}">'
                    f'{icon(it.get("icon") or "activity")}</span><div><div class="ms-feed-title">{esc(it.get("title"))} {inc}</div>'
                    f'<div class="ms-feed-detail">{esc(it.get("detail"))}</div></div>'
                    f'<span class="ms-feed-time" title="{esc(time_ago(it.get("ts"), now))}">{esc(_clock(it.get("ts")))}</span></li>')
    return f'<ol class="ms-feed">{"".join(rows)}</ol>'


# ------------------------------------------------------------------ learning

def rule_cards(rules: list[dict], confirmations: dict[str, int]) -> str:
    if not rules:
        return empty_state("sparkles", "No rules yet", "After the first verified fix, the post-mortem writes a general "
                           "detection rule into Hindsight. Patrol and Watch run only these rules.")
    cards = []
    for k, r in enumerate(rules):
        rid = r.get("id") or ""
        origin = rid.split("rule-", 1)[-1] if rid.startswith("rule-") else ""
        n = int((confirmations or {}).get(rid, 0))
        foot = [chip(f"signal · {r.get('signal_type')}", "accent", mono=True, icon_name="scan")]
        if origin:
            foot.append(chip(f"written after {origin}", "neutral", icon_name="file"))
        foot.append(chip(f"confirmed {n}×", "success" if n else "neutral", icon_name="check-circle"))
        cards.append(f'<div class="ms-rule" style="--i:{k}"><div class="ms-rule-top"><span class="ms-rule-id">{esc(rid)}</span>'
                     f'{chip("stored in Hindsight", "neutral", icon_name="database")}</div>'
                     f'{_rule_text(r.get("text"))}'
                     f'<div class="ms-rule-foot">{"".join(foot)}</div></div>')
    return f'<div class="ms-rules">{"".join(cards)}</div>'


def _rule_text(text) -> str:
    t = clean_meta(text)
    if len(t) <= 220:
        return f'<div class="ms-rule-text">{esc(t)}</div>'
    head = t[:200].rsplit(" ", 1)[0] + "…"
    return (f'<details class="ms-rule-more"><summary><span class="ms-rule-text">{esc(head)}</span>'
            f'<span class="ms-more">Read the full rule</span></summary><div class="ms-rule-text full">{esc(t)}</div></details>')


def exception_cards(exceptions: list[dict]) -> str:
    if not exceptions:
        return empty_state("ban", "No rejected patterns", "When a reviewer rejects a proposed link, the pattern is "
                           "retained here so it is not proposed again.")
    cards = []
    for e in exceptions:
        pair = str(e.get("pair") or "").replace("+", " ≡ ")
        cards.append(f'<div class="ms-exc"><div class="ms-exc-top">{icon("ban")}{chip(e.get("value") or "", "danger", mono=True)}'
                     f'{chip(pair, "neutral") if pair else ""}{chip(e.get("signal_type") or "", "neutral", mono=True) if e.get("signal_type") else ""}</div>'
                     f'<div class="ms-exc-text">{esc(clean_meta(e.get("text")))}</div></div>')
    return "".join(cards)


def observations(items: list[dict]) -> str:
    if not items:
        return empty_state("bulb", "Nothing consolidated yet", "Hindsight consolidates lessons into observations with "
                           "proof counts after the first fixes.")
    rows = "".join(f'<div class="ms-obs-item"><span>{esc(clean_meta(o.get("text")))}</span><span class="ms-proof">{icon("check", "sm")}'
                   f'proof {int(o.get("proof_count") or 1)}</span></div>' for o in items)
    return f'<div class="ms-obs">{rows}</div>'


def playbook_diff(old: str, new: str, old_label: str, new_label: str) -> str:
    lines = list(difflib.unified_diff((old or "").splitlines(), (new or "").splitlines(), lineterm="", n=2))[2:]
    adds = sum(1 for ln in lines if ln.startswith("+"))
    dels = sum(1 for ln in lines if ln.startswith("-"))
    body = []
    for ln in lines[:400]:
        cls = "add" if ln.startswith("+") else "del" if ln.startswith("-") else "hunk" if ln.startswith("@@") else ""
        body.append(f'<div class="ms-dl {cls}">{esc(ln) or "&nbsp;"}</div>')
    if not body:
        body = ['<div class="ms-dl">No text changes between these versions.</div>']
    return (f'<div class="ms-diff"><div class="ms-diff-head"><span>{icon("branch", "sm")} {esc(old_label)} → {esc(new_label)}</span>'
            f'<span>{chip(f"+{adds}", "success", mono=True)} {chip(f"−{dels}", "danger", mono=True)}</span></div>'
            f'<div class="ms-diff-body">{"".join(body)}</div></div>')
