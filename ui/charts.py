"""Plotly figures for the Learning tab, styled by theme.style_fig. Pure: data in, go.Figure out."""
from __future__ import annotations

import plotly.graph_objects as go

from .theme import FAILURE_COLORS, TOKENS, style_fig

OFF, ON = "#6E7581", "#8E8CFF"
KIND_COLORS = {"reactive": TOKENS["danger"], "prevented": TOKENS["success"], "caught by watch": TOKENS["info"],
               "awaiting approval": TOKENS["warning"]}
KIND_LABELS = {"reactive": "reached customers (reactive)", "prevented": "prevented", "caught by watch": "caught by Watch",
               "awaiting approval": "awaiting approval"}


def accuracy(results: dict) -> go.Figure:
    """Before/after accuracy of the committed 20-question evaluation."""
    before, after = float(results.get("before_accuracy") or 0), float(results.get("after_accuracy") or 0)
    fig = go.Figure(go.Bar(
        x=[before, after], y=["Before Memory SRE", "After Memory SRE"], orientation="h", width=0.52,
        marker={"color": [TOKENS["danger"], TOKENS["success"]], "line": {"width": 0}, "cornerradius": 8},
        text=[f"{before:.0f}%", f"{after:.0f}%"], textposition="inside", insidetextanchor="end",
        textfont={"color": "#0B0C10", "size": 14, "family": TOKENS["font_sans"]},
        hovertemplate="%{y}: %{x:.0f}% correct<extra></extra>"))
    fig.update_xaxes(range=[0, 104], tickvals=[0, 25, 50, 75, 100], ticksuffix="%", showgrid=True,
                     gridcolor="rgba(255,255,255,0.05)")
    fig.update_yaxes(autorange="reversed", tickfont={"color": TOKENS["text2"], "size": 12.5})
    return style_fig(fig, height=280, legend=False)


def _episodes(bench: dict, arm: str) -> list[dict]:
    return ((bench or {}).get(arm) or {}).get("episodes") or []


def ab_wrong_answers(bench: dict) -> go.Figure:
    """Cumulative wrong answers that reached customers, per episode, memory OFF vs ON."""
    fig = go.Figure()
    for arm, color, name, fill in (("off", OFF, "Memory OFF", None), ("on", ON, "Memory ON", "tozeroy")):
        eps = _episodes(bench, arm)
        xs = [e.get("name") for e in eps]
        total, ys = 0, []
        for e in eps:
            total += int(e.get("wrong_answers_reaching_customers") or 0)
            ys.append(total)
        fig.add_trace(go.Scatter(
            x=xs, y=ys, name=name, mode="lines+markers", line={"color": color, "width": 3 if arm == "on" else 2.2},
            marker={"size": 9, "color": color, "line": {"width": 2, "color": TOKENS["bg"]}},
            fill=fill, fillcolor="rgba(142,140,255,0.10)" if fill else None,
            customdata=[[e.get("handled_by") or "", "prevented" if e.get("prevented") else ""] for e in eps],
            hovertemplate=f"{name} · %{{x}}<br>%{{y}} wrong so far · %{{customdata[0]}}<extra></extra>"))
    on = _episodes(bench, "on")
    for e in on:
        if e.get("prevented"):
            fig.add_annotation(x=e.get("name"), y=sum(int(x.get("wrong_answers_reaching_customers") or 0) for x in on[: on.index(e) + 1]),
                               text="prevented", showarrow=False, yshift=16, font={"color": TOKENS["success"], "size": 11})
    fig.update_yaxes(rangemode="tozero", dtick=1, title_text="wrong answers (cumulative)")
    return style_fig(fig, height=280)


def ab_steps(bench: dict) -> go.Figure:
    """Investigation steps per episode, memory OFF vs ON."""
    fig = go.Figure()
    for arm, color, name in (("off", OFF, "Memory OFF"), ("on", ON, "Memory ON")):
        eps = _episodes(bench, arm)
        fig.add_trace(go.Bar(
            x=[e.get("name") for e in eps], y=[int(e.get("investigation_steps") or 0) for e in eps], name=name,
            marker={"color": color, "cornerradius": 6, "line": {"width": 0}},
            text=[int(e.get("investigation_steps") or 0) for e in eps], textposition="outside",
            textfont={"color": TOKENS["text2"], "size": 11},
            customdata=[[int(e.get("llm_calls") or 0), e.get("handled_by") or ""] for e in eps],
            hovertemplate=f"{name} · %{{x}}<br>%{{y}} steps · %{{customdata[0]}} LLM calls<br>%{{customdata[1]}}<extra></extra>"))
    fig.update_layout(barmode="group")
    fig.update_yaxes(rangemode="tozero", title_text="investigation steps")
    return style_fig(fig, height=280)


def _kind(inc: dict) -> str:
    if inc.get("status") == "auto-opened":
        return "awaiting approval"
    if inc.get("question") is None:
        return "prevented"
    return "caught by watch" if inc.get("trigger") == "watch" else "reactive"


def diagnosis_cost(incidents: list[dict]) -> go.Figure:
    """LLM calls (bars) and agent steps (markers) per incident, oldest first."""
    rows = [i for i in reversed(incidents or []) if i.get("investigation") and i.get("status") != "rejected"]
    xs = [i["id"] for i in rows]
    calls = [int(i["investigation"].get("llm_calls") or 0) for i in rows]
    steps = [len(i["investigation"].get("steps") or []) for i in rows]
    fig = go.Figure()
    for kind in ("reactive", "caught by watch", "prevented", "awaiting approval"):
        sel = [k for k, i in enumerate(rows) if _kind(i) == kind]
        if not sel:
            continue
        color = KIND_COLORS[kind]
        hollow = kind == "awaiting approval"
        fig.add_trace(go.Bar(
            x=[xs[k] for k in sel], y=[calls[k] for k in sel], name=f"LLM calls · {KIND_LABELS[kind]}",
            marker={"color": "rgba(245,165,36,0.12)" if hollow else color, "cornerradius": 6, "opacity": 0.92,
                    "line": {"color": color, "width": 2 if hollow else 0}},
            customdata=[[rows[k].get("customer_name"), KIND_LABELS[kind], rows[k]["investigation"].get("duration_s")] for k in sel],
            hovertemplate="%{x} · %{customdata[0]}<br>%{customdata[1]} · %{y} LLM calls · %{customdata[2]}s<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=xs, y=steps, name="agent steps", mode="markers+lines", line={"color": "rgba(255,255,255,0.35)", "width": 1.5, "dash": "dot"},
        marker={"size": 9, "color": TOKENS["text"], "line": {"width": 2, "color": TOKENS["bg"]}},
        hovertemplate="%{x}: %{y} steps<extra></extra>"))
    fig.update_layout(barmode="overlay")
    fig.update_xaxes(categoryorder="array", categoryarray=xs)
    fig.update_yaxes(rangemode="tozero", title_text="per incident")
    return style_fig(fig, height=280)


def learning_curve(points: list[dict]) -> go.Figure:
    """Wrong answers customers saw per incident (reactive vs prevented), with a 'lesson learned' marker."""
    xs = [p["id"] for p in points]
    ys = [int(p["wrong_answers"]) for p in points]
    def label(p):
        if p.get("status") == "auto-opened":
            return "awaiting approval"
        if p["kind"] == "reactive":
            return f"{p['wrong_answers']} wrong"
        return "caught by watch" if p["kind"] == "caught by watch" else "prevented"
    pending = [p.get("status") == "auto-opened" for p in points]
    colors = [TOKENS["bg"] if w else KIND_COLORS.get(p["kind"], TOKENS["success"]) for p, w in zip(points, pending)]
    outlines = [TOKENS["warning"] if w else TOKENS["bg"] for w in pending]
    labels = [label(p) for p in points]
    fig = go.Figure(go.Scatter(
        x=xs, y=ys, mode="lines+markers+text", text=labels, textposition="top center",
        textfont={"color": TOKENS["text2"], "size": 11.5},
        line={"color": "rgba(255,255,255,0.28)", "width": 2},
        marker={"size": 15, "color": colors, "line": {"width": 3, "color": outlines}},
        customdata=[[p["customer_name"], p["kind"]] for p in points],
        hovertemplate="%{x} · %{customdata[0]}<br>%{customdata[1]}: %{y} wrong answers<extra></extra>"))
    top = max(ys or [1]) or 1
    for k, p in enumerate(points):
        if p.get("lesson_learned") and k + 1 < len(points):
            fig.add_vrect(x0=k + 0.5, x1=len(points) - 0.5, fillcolor="rgba(61,214,140,0.06)", line_width=0, layer="below")
            fig.add_vline(x=k + 0.5, line={"dash": "dot", "color": ON, "width": 1.5})
            fig.add_annotation(x=k + 0.5, y=top * 1.18 + 0.2, text="lesson learned", showarrow=False, xanchor="left", xshift=6,
                               font={"color": ON, "size": 11.5})
    fig.update_xaxes(tickmode="array", tickvals=xs, ticktext=[f"{p['id']}<br><span style='font-size:10px'>{p['customer_name']}</span>"
                                                              for p in points])
    fig.update_yaxes(rangemode="tozero", dtick=1, range=[-0.2, top * 1.35 + 0.4], title_text="wrong answers customers saw")
    return style_fig(fig, height=280, legend=False)


def rule_proofs(rules: list[dict], confirmations: dict[str, int]) -> go.Figure:
    """Proof count per learned rule: the incident it came from plus every prevention it confirmed."""
    ids = [r["id"] for r in rules]
    proofs = [1 + int((confirmations or {}).get(r["id"], 0)) for r in rules]
    fig = go.Figure(go.Bar(
        x=proofs, y=ids, orientation="h", width=0.5,
        marker={"color": ON, "cornerradius": 6, "line": {"width": 0}},
        text=[f"{p} proof{'s' if p != 1 else ''}" for p in proofs], textposition="outside",
        textfont={"color": TOKENS["text2"], "size": 11.5},
        customdata=[[r.get("signal_type")] for r in rules],
        hovertemplate="%{y} · signal %{customdata[0]}<br>%{x} proofs<extra></extra>"))
    fig.update_xaxes(rangemode="tozero", dtick=1, range=[0, max(proofs or [1]) + 1.2], title_text="proof count")
    fig.update_yaxes(autorange="reversed", tickfont={"family": TOKENS["font_mono"], "size": 11.5, "color": TOKENS["text2"]})
    return style_fig(fig, height=max(280, 70 + 44 * len(ids)), legend=False)
