"""Design system: tokens, icon set, the global stylesheet and Plotly styling.

The stylesheet is injected with one style-only ``st.html`` per run. Streamlit sanitizes st.html with DOMPurify, which
drops a whole <style> element if its text contains "<" followed by a letter or "/" — so the CSS below never contains
one (the @property syntax uses the CSS escape \\3c, SVG icons are URL-encoded data URIs). ``css()`` asserts it.
"""
from __future__ import annotations

import re
from urllib.parse import quote

import streamlit as st

TOKENS = {
    "bg": "#06070A", "surface": "#0C0D12", "surface2": "#12141C", "surface3": "#181B25",
    "border": "rgba(255,255,255,0.07)", "border_strong": "rgba(255,255,255,0.13)",
    "text": "#ECEDEE", "text2": "#A1A7B3", "text3": "#878E9A", "text4": "#6E7581",
    "accent": "#6C6AF6", "accent_hi": "#8E8CFF", "accent_btn": "#5E5CE6",
    "success": "#3DD68C", "danger": "#F0616D", "warning": "#F5A524", "info": "#3EA6FF", "cyan": "#22D3EE",
    "font_sans": "Geist, Inter, ui-sans-serif, system-ui, 'Segoe UI', sans-serif",
    "font_mono": "'Geist Mono', 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
}

FAILURE_COLORS = {"RESOLUTION": "#FF8B3E", "FRESHNESS": "#FACC15", "RECALL_MISS": "#3EA6FF",
                  "EXECUTION": "#A1A7B3", "MISSING_KNOWLEDGE": "#F0616D", "UNKNOWN": "#6E7581"}
FAILURE_LABELS = {"RESOLUTION": "Resolution", "FRESHNESS": "Freshness", "RECALL_MISS": "Recall miss",
                  "EXECUTION": "Execution", "MISSING_KNOWLEDGE": "Missing knowledge", "UNKNOWN": "Unknown"}
STATUS_TONES = {"fixed": "success", "prevented": "success", "open": "danger", "auto-opened": "warning",
                "reverted": "muted", "no_fix": "neutral", "rejected": "muted"}
STATUS_LABELS = {"fixed": "Fixed", "prevented": "Prevented", "open": "Open", "auto-opened": "Awaiting approval",
                 "reverted": "Reverted", "no_fix": "No fix", "rejected": "Rejected"}

# Stroke icons (24x24). Rendered as CSS masks so they take the current text colour: <span class="ms-i ms-i-NAME">.
ICONS = {
    "activity": "<polyline points='22 12 18 12 15 21 9 3 6 12 2 12'/>",
    "search": "<circle cx='11' cy='11' r='7'/><line x1='21' y1='21' x2='16.65' y2='16.65'/>",
    "database": ("<ellipse cx='12' cy='5' rx='8' ry='3'/><path d='M4 5v6c0 1.66 3.58 3 8 3s8-1.34 8-3V5'/>"
                 "<path d='M4 11v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6'/>"),
    "user": "<circle cx='12' cy='8' r='4'/><path d='M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7'/>",
    "users": ("<circle cx='9' cy='8' r='3.5'/><path d='M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6'/>"
              "<path d='M16 4.6a3.5 3.5 0 0 1 0 6.8'/><path d='M18.5 14.3c1.8.8 3 2.7 3 5.7'/>"),
    "link": ("<path d='M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.5 1.5'/>"
             "<path d='M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1.5-1.5'/>"),
    "check": "<polyline points='20 6 9 17 4 12'/>",
    "check-circle": "<circle cx='12' cy='12' r='9'/><polyline points='8 12.5 11 15.5 16.5 9'/>",
    "x": "<line x1='18' y1='6' x2='6' y2='18'/><line x1='6' y1='6' x2='18' y2='18'/>",
    "x-circle": "<circle cx='12' cy='12' r='9'/><line x1='15' y1='9' x2='9' y2='15'/><line x1='9' y1='9' x2='15' y2='15'/>",
    "alert": ("<path d='M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'/>"
              "<line x1='12' y1='9' x2='12' y2='13'/><line x1='12' y1='17' x2='12.01' y2='17'/>"),
    "alert-circle": ("<circle cx='12' cy='12' r='9'/><line x1='12' y1='8' x2='12' y2='12.5'/>"
                     "<line x1='12' y1='16' x2='12.01' y2='16'/>"),
    "shield": "<path d='M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'/>",
    "shield-check": "<path d='M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'/><polyline points='9 12 11 14 15 10'/>",
    "shield-alert": ("<path d='M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'/><line x1='12' y1='8' x2='12' y2='12'/>"
                     "<line x1='12' y1='16' x2='12.01' y2='16'/>"),
    "zap": "<polygon points='13 2 3 14 12 14 11 22 21 10 12 10 13 2'/>",
    "sparkles": ("<path d='M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z'/>"
                 "<path d='M19 16l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z'/>"),
    "clock": "<circle cx='12' cy='12' r='9'/><polyline points='12 7 12 12 15.5 14'/>",
    "ticket": "<path d='M4 7h16v3a2 2 0 0 0 0 4v3H4v-3a2 2 0 0 0 0-4z'/><line x1='13' y1='7' x2='13' y2='17'/>",
    "receipt": ("<path d='M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2z'/><line x1='9' y1='8' x2='15' y2='8'/>"
                "<line x1='9' y1='12' x2='15' y2='12'/>"),
    "clipboard": ("<rect x='6' y='4' width='12' height='17' rx='2'/><path d='M9 4V3h6v1'/>"
                  "<line x1='9' y1='10' x2='15' y2='10'/><line x1='9' y1='14' x2='13' y2='14'/>"),
    "notebook": ("<rect x='5' y='3' width='14' height='18' rx='2'/><line x1='9' y1='3' x2='9' y2='21'/>"
                 "<line x1='12' y1='8' x2='16' y2='8'/><line x1='12' y1='12' x2='16' y2='12'/>"),
    "message": "<path d='M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'/>",
    "tag": "<path d='M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z'/><circle cx='7.5' cy='7.5' r='1.2'/>",
    "radar": "<circle cx='12' cy='12' r='9'/><circle cx='12' cy='12' r='5'/><line x1='12' y1='12' x2='18.5' y2='5.5'/>",
    "compare": ("<path d='M7 7h13'/><polyline points='16 3 20 7 16 11'/><path d='M17 17H4'/>"
                "<polyline points='8 13 4 17 8 21'/>"),
    "target": "<circle cx='12' cy='12' r='9'/><circle cx='12' cy='12' r='5'/><circle cx='12' cy='12' r='1.2'/>",
    "wrench": "<path d='M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z'/>",
    "file": "<path d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/><polyline points='14 2 14 8 20 8'/>",
    "book": "<path d='M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z'/><path d='M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5'/>",
    "book-open": "<path d='M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2z'/><path d='M22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z'/>",
    "undo": "<path d='M3 12a9 9 0 1 0 3-6.7L3 8'/><polyline points='3 3 3 8 8 8'/>",
    "refresh": "<path d='M21 12a9 9 0 1 1-3-6.7L21 8'/><polyline points='21 3 21 8 16 8'/>",
    "play": "<polygon points='7 4 20 12 7 20 7 4'/>",
    "eye": "<path d='M1.5 12s4-7.5 10.5-7.5S22.5 12 22.5 12 18.5 19.5 12 19.5 1.5 12 1.5 12z'/><circle cx='12' cy='12' r='3'/>",
    "arrow-right": "<line x1='5' y1='12' x2='19' y2='12'/><polyline points='13 6 19 12 13 18'/>",
    "branch": ("<circle cx='6' cy='5' r='2'/><circle cx='6' cy='19' r='2'/><circle cx='18' cy='9' r='2'/>"
               "<path d='M6 7v10'/><path d='M18 11c0 4-6 3-11.5 6.5'/>"),
    "sliders": ("<line x1='4' y1='7' x2='20' y2='7'/><line x1='4' y1='17' x2='20' y2='17'/>"
                "<circle cx='9' cy='7' r='2.2'/><circle cx='15' cy='17' r='2.2'/>"),
    "layers": ("<polygon points='12 2 22 7 12 12 2 7 12 2'/><polyline points='2 17 12 22 22 17'/>"
               "<polyline points='2 12 12 17 22 12'/>"),
    "inbox": ("<polyline points='22 12 16 12 14 15 10 15 8 12 2 12'/>"
              "<path d='M5.5 5h13l3.5 7v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z'/>"),
    "bot": ("<rect x='4' y='8' width='16' height='12' rx='3'/><line x1='12' y1='4' x2='12' y2='8'/>"
            "<circle cx='12' cy='3.5' r='1'/><line x1='9' y1='13' x2='9' y2='15'/><line x1='15' y1='13' x2='15' y2='15'/>"),
    "equal": "<line x1='5' y1='9' x2='19' y2='9'/><line x1='5' y1='15' x2='19' y2='15'/>",
    "siren": ("<path d='M7 18v-6a5 5 0 0 1 10 0v6'/><line x1='4' y1='18' x2='20' y2='18'/><line x1='12' y1='2' x2='12' y2='4'/>"
              "<line x1='4.2' y1='5.2' x2='5.6' y2='6.6'/><line x1='19.8' y1='5.2' x2='18.4' y2='6.6'/>"),
    "bulb": ("<path d='M9 18h6'/><path d='M10 22h4'/>"
             "<path d='M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.3 1 2.1V17h6v-.2c0-.8.4-1.6 1-2.1A7 7 0 0 0 12 2z'/>"),
    "cpu": ("<rect x='5' y='5' width='14' height='14' rx='2'/><rect x='9' y='9' width='6' height='6'/>"
            "<line x1='9' y1='2' x2='9' y2='5'/><line x1='15' y1='2' x2='15' y2='5'/><line x1='9' y1='19' x2='9' y2='22'/>"
            "<line x1='15' y1='19' x2='15' y2='22'/><line x1='2' y1='9' x2='5' y2='9'/><line x1='2' y1='15' x2='5' y2='15'/>"
            "<line x1='19' y1='9' x2='22' y2='9'/><line x1='19' y1='15' x2='22' y2='15'/>"),
    "scan": ("<path d='M3 7V5a2 2 0 0 1 2-2h2'/><path d='M17 3h2a2 2 0 0 1 2 2v2'/><path d='M21 17v2a2 2 0 0 1-2 2h-2'/>"
             "<path d='M7 21H5a2 2 0 0 1-2-2v-2'/><line x1='7' y1='12' x2='17' y2='12'/>"),
    "mail": "<rect x='3' y='5' width='18' height='14' rx='2'/><polyline points='3 7 12 13 21 7'/>",
    "calendar": ("<rect x='3' y='5' width='18' height='16' rx='2'/><line x1='3' y1='10' x2='21' y2='10'/>"
                 "<line x1='8' y1='3' x2='8' y2='7'/><line x1='16' y1='3' x2='16' y2='7'/>"),
    "ban": "<circle cx='12' cy='12' r='9'/><line x1='5.6' y1='5.6' x2='18.4' y2='18.4'/>",
    "pin": "<path d='M12 17v5'/><path d='M9 3h6l-1 6 3 3v2H7v-2l3-3z'/>",
    "hash": ("<line x1='4' y1='9' x2='20' y2='9'/><line x1='4' y1='15' x2='20' y2='15'/>"
             "<line x1='10' y1='3' x2='8' y2='21'/><line x1='16' y1='3' x2='14' y2='21'/>"),
    "gauge": "<path d='M4 18a8 8 0 1 1 16 0'/><line x1='12' y1='18' x2='16' y2='11'/><circle cx='12' cy='18' r='1.2'/>",
}


def _icon_css() -> str:
    rules = []
    for name, inner in ICONS.items():
        svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' "
               f"stroke-width='1.9' stroke-linecap='round' stroke-linejoin='round'>{inner}</svg>")
        uri = "data:image/svg+xml," + quote(svg, safe=" /:=',.-")   # '<' becomes %3C: safe inside <style>
        rules.append(f'.ms-i-{name}{{-webkit-mask-image:url("{uri}");mask-image:url("{uri}")}}')
    return "\n".join(rules)


_CSS = r"""
/* ============================================================ tokens */
@property --n { syntax: '\3c integer>'; initial-value: 0; inherits: false; }
:root {
  --bg: #06070A; --surface: #0C0D12; --surface-2: #12141C; --surface-3: #181B25;
  --border: rgba(255,255,255,.07); --border-strong: rgba(255,255,255,.13);
  --text: #ECEDEE; --text-2: #A1A7B3; --text-3: #878E9A; --text-4: #6E7581;
  --accent: #6C6AF6; --accent-hi: #8E8CFF; --accent-btn: #5E5CE6; --accent-lo: rgba(108,106,246,.14);
  --success: #3DD68C; --success-lo: rgba(61,214,140,.12);
  --danger: #F0616D; --danger-lo: rgba(240,97,109,.12);
  --warning: #F5A524; --warning-lo: rgba(245,165,36,.12);
  --info: #3EA6FF; --info-lo: rgba(62,166,255,.12);
  --ft-resolution: #FF8B3E; --ft-freshness: #FACC15; --ft-recall: #3EA6FF; --ft-execution: #A1A7B3;
  --ft-missing: #F0616D; --ft-unknown: #6E7581;
  --r-sm: 8px; --r-md: 12px; --r-lg: 16px; --r-xl: 22px;
  --font-sans: Geist, Inter, ui-sans-serif, system-ui, "Segoe UI", sans-serif;
  --font-mono: "Geist Mono", "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --ease: cubic-bezier(.16,1,.3,1);
  --elev: inset 0 1px 0 rgba(255,255,255,.04), 0 10px 30px -14px rgba(0,0,0,.65);
  --ring: 0 0 0 1px rgba(142,140,255,.45), 0 0 0 4px rgba(108,106,246,.16);
}

/* ============================================================ page, chrome */
html, body { background: var(--bg); }
.stApp { background:
    radial-gradient(1100px 560px at 8% -12%, rgba(94,92,230,.17), transparent 62%),
    radial-gradient(900px 480px at 96% -8%, rgba(34,211,238,.08), transparent 60%),
    var(--bg);
  background-attachment: fixed; color: var(--text); }
.stApp::before { content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background-image: radial-gradient(rgba(255,255,255,.045) 1px, transparent 1.2px); background-size: 22px 22px;
  -webkit-mask-image: linear-gradient(180deg, rgba(0,0,0,.9), transparent 560px);
  mask-image: linear-gradient(180deg, rgba(0,0,0,.9), transparent 560px); }
header[data-testid="stHeader"] { background: transparent; }
[data-testid="stDecoration"], [data-testid="stSidebarCollapsedControl"], [data-testid="stAppDeployButton"] { display: none !important; }
.stApp [data-testid="stMainBlockContainer"] { max-width: 1360px; padding: 1.1rem 2.25rem 5rem; }
.stApp [data-testid="stMain"] { position: relative; z-index: 1; }
::selection { background: rgba(108,106,246,.35); }
.stApp p, .stApp li { line-height: 1.55; }
.stApp h1, .stApp h2, .stApp h3, .stApp h4 { letter-spacing: -.015em; }
.stApp code { font-family: var(--font-mono); }
.stApp [data-testid="stHtml"] { font-family: var(--font-sans); }
.stApp [data-testid="stCaptionContainer"] { color: var(--text-3); }

/* ============================================================ native widgets */
/* tabs: Linear-style underline */
.stApp .st-key-nav [role="tablist"] { gap: 2px; border-bottom: 1px solid var(--border); padding: 0 2px; overflow-x: auto; scrollbar-width: none; }
.stApp .st-key-nav [data-testid="stTab"] { height: 46px; padding: 0 16px; color: var(--text-3); background: transparent;
  border-radius: 10px 10px 0 0; transition: color .18s var(--ease), background .18s var(--ease); }
.stApp .st-key-nav [data-testid="stTab"] p { font-size: 14px; font-weight: 550; letter-spacing: -.005em; }
.stApp .st-key-nav [data-testid="stTab"]:hover { color: var(--text-2); background: rgba(255,255,255,.025); }
.stApp .st-key-nav [data-testid="stTab"][aria-selected="true"] { color: var(--text); }
.stApp .st-key-nav .react-aria-SelectionIndicator { background: linear-gradient(90deg, var(--accent), var(--accent-hi)) !important;
  height: 2px !important; border-radius: 2px; box-shadow: 0 0 14px rgba(142,140,255,.8); }
.stApp .st-key-nav [data-testid="stTabPanel"] { padding-top: 22px; }

/* buttons */
.stApp [data-testid="stBaseButton-primary"] { background: linear-gradient(180deg, #6D6BF7 0%, #5E5CE6 100%);
  border: 1px solid rgba(255,255,255,.14); color: #fff; font-weight: 600; letter-spacing: -.005em;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.22), 0 1px 2px rgba(0,0,0,.45), 0 10px 26px -10px rgba(94,92,230,.75);
  transition: transform .16s var(--ease), box-shadow .22s var(--ease), filter .22s var(--ease); }
.stApp [data-testid="stBaseButton-primary"]:hover { filter: brightness(1.09); transform: translateY(-1px); color: #fff;
  border-color: rgba(255,255,255,.22);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.26), 0 2px 4px rgba(0,0,0,.4), 0 14px 34px -10px rgba(108,106,246,.9); }
.stApp [data-testid="stBaseButton-primary"]:active { transform: translateY(0); filter: brightness(.98); }
.stApp [data-testid="stBaseButton-primary"]:disabled { filter: saturate(.35) brightness(.62); transform: none; box-shadow: none; }
.stApp [data-testid="stBaseButton-secondary"], .stApp [data-testid="stPopoverButton"] { background: var(--surface-2);
  border: 1px solid var(--border-strong); color: var(--text); font-weight: 520;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.04); transition: border-color .18s, background .18s, color .18s, transform .16s var(--ease); }
.stApp [data-testid="stBaseButton-secondary"]:hover, .stApp [data-testid="stPopoverButton"]:hover { border-color: rgba(142,140,255,.5);
  background: #171A26; color: #fff; }
.stApp [data-testid="stBaseButton-secondary"]:disabled { opacity: .45; }
.stApp [data-testid="stBaseButton-tertiary"] { color: var(--text-2); }
.stApp [data-testid="stBaseButton-tertiary"]:hover { color: var(--accent-hi); }
.stApp button:focus-visible { outline: 2px solid var(--accent-hi) !important; outline-offset: 2px; }

/* pills & segmented control */
.stApp [data-testid="stButtonGroup"] [role="radiogroup"] { gap: 8px; flex-wrap: wrap; }
.stApp [data-testid="stButtonGroup"] button[role="radio"] { background: rgba(255,255,255,.025); border: 1px solid var(--border-strong);
  color: var(--text-2); border-radius: 999px; min-height: 32px; padding: 4px 14px; font-size: 13px; font-weight: 520;
  transition: color .18s, border-color .18s, background .18s, box-shadow .18s; }
.stApp [data-testid="stButtonGroup"] button[role="radio"]:hover { color: var(--text); background: rgba(255,255,255,.05); border-color: rgba(255,255,255,.2); }
.stApp [data-testid="stButtonGroup"] button[role="radio"][aria-checked="true"] { color: #fff; background: rgba(108,106,246,.18);
  border-color: rgba(142,140,255,.6); box-shadow: 0 0 0 3px rgba(108,106,246,.12), inset 0 1px 0 rgba(255,255,255,.07); }
.stApp .st-key-sample button[role="radio"] { border-style: dashed; color: var(--text-2); max-width: 100%; height: auto; min-height: 32px; }
.stApp .st-key-sample button[role="radio"] * { white-space: normal !important; text-align: left; }
.stApp .st-key-sample button[role="radio"]:hover { border-style: solid; }

/* inputs */
.stApp [data-testid="stTextInputRootElement"], .stApp [data-testid="stTextAreaRootElement"] { background: var(--surface-2);
  border: 1px solid var(--border-strong); border-radius: 12px; transition: border-color .18s, box-shadow .18s; }
.stApp [data-testid="stTextInputRootElement"]:focus-within, .stApp [data-testid="stTextAreaRootElement"]:focus-within {
  border-color: rgba(142,140,255,.7); box-shadow: 0 0 0 4px rgba(108,106,246,.15); }
.stApp [data-testid="stTextInputRootElement"] input, .stApp [data-testid="stTextAreaRootElement"] textarea {
  font-family: var(--font-sans); color: var(--text); font-size: 14.5px; background: transparent; }
.stApp .st-key-question [data-testid="stTextInputRootElement"] { min-height: 46px; border-radius: 14px; }
.stApp .st-key-question input { font-size: 15px; padding-left: 14px; }
.stApp .st-key-qrow { align-items: stretch; gap: 10px; }
.stApp .st-key-qrow [data-testid="stBaseButton-primary"] { min-height: 46px; padding: 0 20px; border-radius: 14px; }
.stApp [data-testid="stWidgetLabel"] p { color: var(--text-2); font-size: 13px; font-weight: 520; }

/* expanders & status */
.stApp [data-testid="stExpander"] details { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; overflow: hidden; }
.stApp [data-testid="stExpander"] summary { color: var(--text-2); font-weight: 520; }
.stApp [data-testid="stExpander"] summary:hover { color: var(--text); background: rgba(255,255,255,.02); }

/* alerts: styled cards (st.error is the styled error card) */
.stApp [data-testid="stAlertContainer"] { border-radius: 12px; border: 1px solid var(--border); background: var(--surface); position: relative; }
.stApp [data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) { border-color: rgba(240,97,109,.4);
  background: linear-gradient(90deg, rgba(240,97,109,.13), rgba(240,97,109,.035) 55%, var(--surface));
  box-shadow: inset 3px 0 0 var(--danger), 0 12px 30px -18px rgba(240,97,109,.55); }
.stApp [data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) { border-color: rgba(245,165,36,.38);
  background: linear-gradient(90deg, rgba(245,165,36,.12), rgba(245,165,36,.03) 55%, var(--surface)); box-shadow: inset 3px 0 0 var(--warning); }
.stApp [data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) { border-color: rgba(62,166,255,.32);
  background: linear-gradient(90deg, rgba(62,166,255,.11), rgba(62,166,255,.03) 55%, var(--surface)); box-shadow: inset 3px 0 0 var(--info); }
.stApp [data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) { border-color: rgba(61,214,140,.34);
  background: linear-gradient(90deg, rgba(61,214,140,.12), rgba(61,214,140,.03) 55%, var(--surface)); box-shadow: inset 3px 0 0 var(--success); }
.stApp [data-testid="stAlertContentError"] p, .stApp [data-testid="stAlertContentError"] { color: #FFD3D7; }

/* toasts (rendered in a portal, outside .stApp) */
[data-testid="stToast"] { background: rgba(18,20,28,.92) !important; border: 1px solid var(--border-strong) !important; border-radius: 12px !important;
  box-shadow: 0 24px 60px -20px rgba(0,0,0,.85), 0 0 0 1px rgba(142,140,255,.12) !important; backdrop-filter: blur(10px); color: var(--text) !important; }

/* charts, dataframes, containers */
.stApp [data-testid="stPlotlyChart"] { animation: ms-chart-in .9s var(--ease) both; }
.stApp [data-testid="stDataFrame"] { border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.stApp .stVerticalBlock[class*="st-key-panel-"] { background: linear-gradient(180deg, rgba(255,255,255,.022), rgba(255,255,255,0) 120px), var(--surface);
  border: 1px solid var(--border); border-radius: var(--r-lg); padding: 18px 20px; box-shadow: var(--elev); }

/* clickable cards: a native button stretched invisibly over custom HTML */
.stApp .stVerticalBlock[class*="st-key-cc-"] { position: relative; gap: 0; }
.stApp .stVerticalBlock[class*="st-key-cc-"] > [data-testid="stElementContainer"]:has([data-testid="stButton"]) { position: absolute; inset: 0; z-index: 3; margin: 0; }
.stApp .stVerticalBlock[class*="st-key-cc-"] [data-testid="stButton"], .stApp .stVerticalBlock[class*="st-key-cc-"] [data-testid="stButton"] button { width: 100%; height: 100%; }
.stApp .stVerticalBlock[class*="st-key-cc-"] [data-testid="stButton"] button { opacity: 0; cursor: pointer; }
.stApp .stVerticalBlock[class*="st-key-cc-"]:hover .ms-card-click { border-color: rgba(142,140,255,.38); transform: translateY(-1px); background: #0F1118; }
.stApp .stVerticalBlock[class*="st-key-cc-"]:focus-within .ms-card-click { box-shadow: var(--ring); }

/* ============================================================ primitives */
.ms-i { display: inline-block; width: 16px; height: 16px; flex: none; background-color: currentColor; vertical-align: -3px;
  -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat; -webkit-mask-position: center; mask-position: center;
  -webkit-mask-size: contain; mask-size: contain; }
.ms-i.sm { width: 13px; height: 13px; vertical-align: -2px; }
.ms-i.lg { width: 20px; height: 20px; }
.ms-mono, .ms-id, code.ms { font-family: var(--font-mono); font-size: 12px; letter-spacing: 0; }
.ms-muted { color: var(--text-3); }
.ms-label { color: var(--text-3); font-size: 11px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; }
.ms-chip { display: inline-flex; align-items: center; gap: 6px; height: 24px; padding: 0 9px; border-radius: 999px; font-size: 12px;
  font-weight: 540; white-space: nowrap; color: var(--text-2); background: rgba(255,255,255,.04); border: 1px solid var(--border); }
.ms-chip.mono { font-family: var(--font-mono); font-size: 11.5px; }
.ms-chip.glow { box-shadow: 0 0 18px -2px currentColor; }
.ms-tone-accent { color: #B9B8FF; background: rgba(108,106,246,.12); border-color: rgba(142,140,255,.32); }
.ms-tone-success { color: #86EFBC; background: rgba(61,214,140,.10); border-color: rgba(61,214,140,.30); }
.ms-tone-danger { color: #FF9AA3; background: rgba(240,97,109,.10); border-color: rgba(240,97,109,.32); }
.ms-tone-warning { color: #FFC56B; background: rgba(245,165,36,.10); border-color: rgba(245,165,36,.32); }
.ms-tone-info { color: #8CCBFF; background: rgba(62,166,255,.10); border-color: rgba(62,166,255,.30); }
.ms-tone-neutral { color: var(--text-2); }
.ms-tone-muted { color: var(--text-3); background: transparent; }
.ms-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; flex: none; }
.ms-dot.live { animation: ms-pulse-dot 1.8s ease-out infinite; }
.ms-badge-ft { --c: var(--ft-unknown); display: inline-flex; align-items: center; gap: 7px; height: 26px; padding: 0 11px; border-radius: 999px;
  font-size: 12px; font-weight: 650; letter-spacing: .04em; text-transform: uppercase; color: var(--c);
  background: color-mix(in srgb, var(--c) 12%, transparent); border: 1px solid color-mix(in srgb, var(--c) 42%, transparent); }
.ms-badge-ft .ms-dot { background: var(--c); }
.ms-badge-ft.glow { box-shadow: 0 0 0 1px color-mix(in srgb, var(--c) 25%, transparent), 0 0 26px -4px color-mix(in srgb, var(--c) 70%, transparent);
  animation: ms-glow-breathe 3.2s ease-in-out infinite; }
.ms-ft-RESOLUTION { --c: var(--ft-resolution); } .ms-ft-FRESHNESS { --c: var(--ft-freshness); } .ms-ft-RECALL_MISS { --c: var(--ft-recall); }
.ms-ft-EXECUTION { --c: var(--ft-execution); } .ms-ft-MISSING_KNOWLEDGE { --c: var(--ft-missing); } .ms-ft-UNKNOWN { --c: var(--ft-unknown); }
.ms-status { display: inline-flex; align-items: center; gap: 6px; height: 24px; padding: 0 10px; border-radius: 999px; font-size: 12px; font-weight: 560;
  border: 1px solid var(--border); white-space: nowrap; }
.ms-status.st-rejected { text-decoration: line-through; }
.ms-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg); box-shadow: var(--elev); }
.ms-section { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin: 6px 0 12px; }
.ms-section-title { display: flex; align-items: center; gap: 9px; font-size: 15px; font-weight: 640; color: var(--text); letter-spacing: -.01em; }
.ms-section-title .ms-i { color: var(--accent-hi); }
.ms-section-sub { color: var(--text-3); font-size: 13px; margin-top: 3px; }
.ms-kicker { color: var(--text-3); font-size: 11px; font-weight: 600; letter-spacing: .09em; text-transform: uppercase; margin: 4px 0 8px; }

/* empty & skeleton */
.ms-empty { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 8px; padding: 36px 24px; border-radius: var(--r-lg);
  border: 1px dashed rgba(255,255,255,.11); background: linear-gradient(180deg, rgba(255,255,255,.015), transparent); }
.ms-empty-icon { width: 44px; height: 44px; border-radius: 14px; display: grid; place-items: center; color: var(--accent-hi);
  background: rgba(108,106,246,.1); border: 1px solid rgba(142,140,255,.25); margin-bottom: 4px; }
.ms-empty-icon .ms-i { width: 21px; height: 21px; }
.ms-empty-title { font-weight: 620; color: var(--text); font-size: 15px; }
.ms-empty-body { color: var(--text-2); font-size: 13.5px; max-width: 460px; }
.ms-empty-hint { color: var(--text-3); font-size: 12.5px; }
.ms-skel { border-radius: 10px; background: linear-gradient(90deg, rgba(255,255,255,.035) 25%, rgba(255,255,255,.075) 37%, rgba(255,255,255,.035) 63%);
  background-size: 400% 100%; animation: ms-shimmer 1.4s ease infinite; }
.ms-skel-wrap { display: grid; gap: 10px; }
.ms-skel-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }

/* ============================================================ hero */
.ms-hero { position: relative; overflow: hidden; isolation: isolate; border: 1px solid var(--border); border-radius: var(--r-xl);
  padding: 22px 26px; margin-bottom: 14px; background: linear-gradient(180deg, rgba(255,255,255,.035), rgba(255,255,255,.005)), rgba(12,13,18,.72);
  box-shadow: var(--elev); }
.ms-hero-glow { position: absolute; inset: -60% -10% -60% -10%; z-index: -1; pointer-events: none; opacity: .6; filter: blur(8px);
  background: radial-gradient(34% 46% at 18% 40%, rgba(108,106,246,.42), transparent 70%),
              radial-gradient(30% 42% at 82% 30%, rgba(34,211,238,.20), transparent 70%),
              radial-gradient(26% 36% at 58% 78%, rgba(61,214,140,.10), transparent 70%);
  animation: ms-glow-drift 18s ease-in-out infinite alternate; }
.ms-hero-line { position: absolute; left: 0; right: 0; top: 0; height: 1px; background: linear-gradient(90deg, transparent, rgba(142,140,255,.7), rgba(34,211,238,.5), transparent); }
.ms-hero-inner { display: flex; align-items: center; justify-content: space-between; gap: 18px 28px; flex-wrap: wrap; }
.ms-brand { display: flex; align-items: center; gap: 15px; min-width: 0; }
.ms-logo { width: 46px; height: 46px; border-radius: 13px; display: grid; place-items: center; color: #fff; flex: none;
  background: linear-gradient(135deg, #8584FF 0%, #5A58E0 55%, #1FB8C9 120%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.35), 0 0 0 1px rgba(255,255,255,.1), 0 12px 32px -10px rgba(108,106,246,.9); }
.ms-logo .ms-i { width: 23px; height: 23px; }
.ms-brand-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ms-title { font-size: 27px; font-weight: 720; letter-spacing: -.025em; line-height: 1.1; margin: 0;
  background: linear-gradient(90deg, #FFFFFF 0%, #DAD9FF 30%, #9C9AFF 50%, #DAD9FF 70%, #FFFFFF 100%); background-size: 200% auto;
  -webkit-background-clip: text; background-clip: text; color: transparent; animation: ms-sheen 9s linear infinite; }
.ms-tagline { color: var(--text-2); font-size: 14px; margin: 5px 0 0; }
.ms-hero-pills { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
.ms-pill { display: inline-flex; align-items: center; gap: 7px; height: 30px; padding: 0 12px; border-radius: 999px; font-size: 12.5px; font-weight: 540;
  color: var(--text-2); background: rgba(255,255,255,.03); border: 1px solid var(--border); white-space: nowrap; backdrop-filter: blur(6px); }
.ms-pill code { font-family: var(--font-mono); font-size: 11.5px; color: var(--text-3); background: none; padding: 0; }
.ms-pill b { color: var(--text); font-weight: 650; font-variant-numeric: tabular-nums; }

/* ============================================================ metrics */
.ms-metric { position: relative; overflow: hidden; height: 100%; min-height: 118px; padding: 15px 18px 14px; border-radius: var(--r-lg);
  background: linear-gradient(180deg, rgba(255,255,255,.025), rgba(255,255,255,0) 70%), var(--surface); border: 1px solid var(--border); box-shadow: var(--elev);
  animation: ms-rise .6s var(--ease) both; animation-delay: calc(var(--i, 0) * 70ms); }
.ms-metric::before { content: ""; position: absolute; left: 18px; right: 18px; top: 0; height: 1px; background: linear-gradient(90deg, transparent, var(--mc, rgba(142,140,255,.6)), transparent); }
.ms-metric-top { display: flex; align-items: center; gap: 9px; color: var(--text-2); font-size: 12.5px; font-weight: 560; }
.ms-metric-icon { width: 26px; height: 26px; border-radius: 8px; display: grid; place-items: center; border: 1px solid; }
.ms-metric-icon .ms-i { width: 14px; height: 14px; }
.ms-metric-value { margin-top: 12px; display: flex; align-items: baseline; gap: 3px; font-size: 32px; font-weight: 680; letter-spacing: -.03em;
  font-variant-numeric: tabular-nums; color: var(--text); line-height: 1; }
.ms-metric-value .unit { font-size: 18px; color: var(--text-2); font-weight: 600; }
.ms-metric-value .to { margin: 0 8px; color: var(--text-3); font-size: 18px; font-weight: 500; }
.ms-metric-value .good { color: #7BF0B6; }
.ms-metric-value .bad { color: #FF9AA3; }
.ms-metric-note { margin-top: 9px; color: var(--text-3); font-size: 12px; }
.ms-count { --n: var(--to); counter-reset: n var(--n); animation: ms-count 1.3s var(--ease) both; animation-delay: calc(var(--i, 0) * 70ms + 120ms); }
.ms-count::after { content: counter(n); }

/* ============================================================ console */
.ms-answer { position: relative; overflow: hidden; border-radius: var(--r-lg); border: 1px solid var(--border);
  background: radial-gradient(120% 90% at 0% 0%, rgba(108,106,246,.10), transparent 55%), var(--surface); box-shadow: var(--elev);
  animation: ms-rise .55s var(--ease) both; }
.ms-answer-head { display: flex; align-items: center; gap: 12px; padding: 16px 18px 0; }
.ms-avatar { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; font-size: 12.5px; font-weight: 700; color: #fff; flex: none;
  background: linear-gradient(135deg, #3B3A8F, #26254F); border: 1px solid rgba(142,140,255,.35); }
.ms-answer-who { min-width: 0; flex: 1; }
.ms-answer-cust { font-size: 12.5px; color: var(--text-3); font-weight: 560; }
.ms-answer-q { color: var(--text); font-weight: 600; font-size: 14.5px; margin-top: 1px; }
.ms-answer-body { padding: 12px 18px 4px 64px; font-size: 16px; line-height: 1.62; color: #F2F3F5; letter-spacing: -.003em; }
.ms-answer-body.reveal .w { display: inline-block; animation: ms-word .46s var(--ease) both; animation-delay: min(calc(var(--i) * 24ms), 1.8s); }
.ms-answer-foot { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 10px 18px 16px 64px; }
.ms-watch { margin: 0 18px 16px 64px; padding: 10px 12px; border-radius: 12px; display: flex; gap: 10px; align-items: flex-start;
  background: rgba(62,166,255,.07); border: 1px solid rgba(62,166,255,.25); color: #BFE2FF; font-size: 13px; }
.ms-watch .ms-i { color: var(--info); margin-top: 2px; }
.ms-mem-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 10px; }
.ms-mem { position: relative; display: flex; flex-direction: column; gap: 8px; padding: 12px 13px 11px; border-radius: 13px; background: var(--surface);
  border: 1px solid var(--border); animation: ms-rise .5s var(--ease) both; animation-delay: calc(var(--i, 0) * 60ms); transition: border-color .2s; }
.ms-mem:hover { border-color: var(--border-strong); }
.ms-mem-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.ms-src { display: inline-flex; align-items: center; gap: 6px; color: var(--text-2); font-size: 11.5px; font-weight: 600; letter-spacing: .02em; }
.ms-src .ms-i { color: var(--accent-hi); width: 14px; height: 14px; }
.ms-date { font-family: var(--font-mono); font-size: 11px; color: var(--text-3); padding: 2px 7px; border-radius: 6px; background: rgba(255,255,255,.04); border: 1px solid var(--border); }
.ms-mem-text { color: var(--text); font-size: 13.5px; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
.ms-mem-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: auto; flex-wrap: wrap; }
.ms-mem-meta { color: var(--text-3); font-size: 11.5px; }
.ms-tag { display: inline-flex; align-items: center; gap: 5px; font-family: var(--font-mono); font-size: 11px; color: var(--text-2); padding: 2px 7px; border-radius: 6px;
  background: rgba(255,255,255,.035); border: 1px solid var(--border); }
.ms-tag.foreign { color: #FFB27A; background: rgba(255,139,62,.12); border-color: rgba(255,139,62,.45); box-shadow: 0 0 16px -3px rgba(255,139,62,.6); }
.ms-id { color: var(--text-3); font-size: 11px; }
.ms-mem.culprit { border-color: rgba(240,97,109,.35); box-shadow: inset 3px 0 0 var(--danger), 0 12px 30px -20px rgba(240,97,109,.6);
  background: linear-gradient(90deg, rgba(240,97,109,.07), transparent 45%), var(--surface); }
.ms-mem.evidence { border-color: rgba(255,139,62,.28); box-shadow: inset 3px 0 0 var(--ft-resolution);
  background: linear-gradient(90deg, rgba(255,139,62,.06), transparent 45%), var(--surface); }
.ms-mem-kind { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 650; letter-spacing: .06em; text-transform: uppercase; }
.ms-mem.culprit .ms-mem-kind { color: #FF9AA3; } .ms-mem.evidence .ms-mem-kind { color: #FFB27A; }
.ms-mem-note { font-size: 12.5px; color: var(--text-2); border-top: 1px dashed var(--border); padding-top: 8px; }
.ms-mem-note q { color: #FFC9CE; }
.ms-mem.struck { opacity: .58; filter: saturate(.45); }
.ms-mem-text .t { -webkit-box-decoration-break: clone; box-decoration-break: clone; }
.ms-mem.struck .ms-mem-text .t { background: linear-gradient(var(--danger), var(--danger)) 0 58% / 100% 1.5px no-repeat; }
.ms-mem.struck.anim { animation: ms-fade-struck .9s var(--ease) both .15s; }
.ms-mem.struck.anim .ms-mem-text .t { animation: ms-strike .7s var(--ease) both .3s; }
.ms-stamp { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: #FF9AA3;
  padding: 2px 8px; border-radius: 6px; border: 1px solid rgba(240,97,109,.45); background: rgba(240,97,109,.1); }
.ms-side { display: grid; gap: 12px; }
.ms-side-card { padding: 16px; border-radius: var(--r-lg); background: var(--surface); border: 1px solid var(--border); box-shadow: var(--elev); }
.ms-side-title { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 640; color: var(--text); margin-bottom: 10px; }
.ms-side-title .ms-i { color: var(--accent-hi); }
.ms-kv { display: flex; justify-content: space-between; gap: 10px; font-size: 12.5px; color: var(--text-2); padding: 5px 0; border-bottom: 1px dashed rgba(255,255,255,.05); }
.ms-kv:last-child { border-bottom: 0; }
.ms-kv b { color: var(--text); font-weight: 600; }
.ms-tags { display: flex; flex-wrap: wrap; gap: 6px; }

/* ============================================================ agent trace */
.ms-trace { position: relative; border-radius: var(--r-lg); border: 1px solid var(--border); background: var(--surface); box-shadow: var(--elev); overflow: hidden; }
.ms-trace.live { border-color: rgba(142,140,255,.32); box-shadow: 0 0 0 1px rgba(142,140,255,.1), 0 20px 50px -24px rgba(108,106,246,.55); }
.ms-trace-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding: 14px 18px; border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, rgba(255,255,255,.025), transparent); }
.ms-trace-title { display: flex; align-items: center; gap: 10px; font-weight: 650; font-size: 14.5px; color: var(--text); }
.ms-trace-title .ms-i { color: var(--accent-hi); width: 18px; height: 18px; }
.ms-trace-sub { color: var(--text-3); font-size: 12.5px; font-weight: 500; }
.ms-live-badge { display: inline-flex; align-items: center; gap: 6px; height: 22px; padding: 0 8px; border-radius: 6px; font-size: 10.5px; font-weight: 750;
  letter-spacing: .1em; color: #FF9AA3; background: rgba(240,97,109,.12); border: 1px solid rgba(240,97,109,.35); }
.ms-live-badge .ms-dot { width: 6px; height: 6px; animation: ms-pulse-dot 1.4s ease-out infinite; }
.ms-trace-stats { display: flex; gap: 6px; flex-wrap: wrap; }
.ms-trace-badges { display: flex; gap: 8px; flex-wrap: wrap; padding: 12px 18px 0; }
.ms-steps { list-style: none; margin: 0; padding: 14px 18px 8px; }
.ms-step { position: relative; display: grid; grid-template-columns: 28px 1fr; gap: 12px; padding-bottom: 14px; }
.ms-step::before { content: ""; position: absolute; left: 13.5px; top: 30px; bottom: -2px; width: 1px;
  background: linear-gradient(180deg, rgba(255,255,255,.14), rgba(255,255,255,.05)); }
.ms-step.last::before { display: none; }
.ms-step.anim { animation: ms-rise .5s var(--ease) both; animation-delay: calc(var(--i, 0) * 80ms); }
.ms-node { width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; position: relative; z-index: 1;
  background: var(--surface-2); border: 1px solid var(--border-strong); color: var(--text-2); }
.ms-node .ms-i { width: 14px; height: 14px; }
.ms-step.done .ms-node { color: var(--success); border-color: rgba(61,214,140,.45); background: rgba(61,214,140,.1); }
.ms-step.done.anim .ms-node .ms-i { animation: ms-pop .35s var(--ease) both; }
.ms-step.running .ms-node, .ms-step.thinking .ms-node, .ms-step.verdict .ms-node { color: var(--accent-hi); border-color: rgba(142,140,255,.6);
  background: rgba(108,106,246,.16); animation: ms-pulse-ring 1.5s ease-out infinite; }
.ms-step.rejected .ms-node { color: var(--warning); border-color: rgba(245,165,36,.5); background: rgba(245,165,36,.1); }
.ms-step.invalid .ms-node, .ms-step.error .ms-node { color: var(--danger); border-color: rgba(240,97,109,.5); background: rgba(240,97,109,.1); }
.ms-step.fallback .ms-node { color: var(--warning); border-color: rgba(245,165,36,.5); background: rgba(245,165,36,.1); }
.ms-step.accepted .ms-node { color: #06170F; border-color: transparent; background: linear-gradient(135deg, #5BF0A8, #2FBF7A);
  box-shadow: 0 0 0 4px rgba(61,214,140,.14), 0 0 22px rgba(61,214,140,.55); }
.ms-step-body { min-width: 0; padding-top: 3px; }
.ms-step-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ms-step-n { font-family: var(--font-mono); font-size: 11px; color: var(--text-3); }
.ms-tool { display: inline-flex; align-items: center; gap: 6px; height: 24px; padding: 0 9px; border-radius: 7px; font-family: var(--font-mono); font-size: 12px;
  font-weight: 560; color: #C9C8FF; background: rgba(108,106,246,.12); border: 1px solid rgba(142,140,255,.3); }
.ms-tool .ms-i { width: 13px; height: 13px; }
.ms-step.rejected .ms-tool { color: #FFC56B; background: rgba(245,165,36,.1); border-color: rgba(245,165,36,.35); }
.ms-step.invalid .ms-tool, .ms-step.error .ms-tool { color: #FF9AA3; background: rgba(240,97,109,.1); border-color: rgba(240,97,109,.35); }
.ms-step.accepted .ms-tool { color: #86EFBC; background: rgba(61,214,140,.1); border-color: rgba(61,214,140,.35); }
.ms-arg { font-family: var(--font-mono); font-size: 11.5px; color: var(--text-2); padding: 2px 7px; border-radius: 6px; background: rgba(255,255,255,.035);
  border: 1px solid var(--border); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ms-arg i { font-style: normal; color: var(--text-3); }
.ms-thought { margin-top: 6px; color: var(--text); font-size: 13.5px; line-height: 1.5; }
.ms-thought.shimmer { background: linear-gradient(90deg, var(--text-3) 0%, #fff 45%, var(--text-3) 90%); background-size: 200% auto;
  -webkit-background-clip: text; background-clip: text; color: transparent; animation: ms-shimmer-text 1.6s linear infinite; }
.ms-result { margin-top: 7px; font-family: var(--font-mono); font-size: 11.5px; line-height: 1.55; color: var(--text-2); padding: 8px 10px; border-radius: 9px;
  background: rgba(0,0,0,.25); border: 1px solid var(--border); }
.ms-clamp { white-space: pre-wrap; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.ms-step.rejected .ms-result { color: #FFD9A0; border-color: rgba(245,165,36,.22); background: rgba(245,165,36,.05); font-family: var(--font-sans); font-size: 12.5px; }
.ms-verdict { margin-top: 7px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; color: var(--text); }
.ms-trace-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding: 12px 18px 14px; border-top: 1px solid var(--border);
  background: rgba(255,255,255,.012); font-size: 12.5px; color: var(--text-2); }
.ms-cand { margin: 12px 18px 0; padding: 10px 12px; border-radius: 11px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  background: rgba(255,255,255,.025); border: 1px solid var(--border); font-size: 13px; color: var(--text); animation: ms-rise .45s var(--ease) both; }
.ms-cand .ms-i { color: var(--accent-hi); }
.ms-outcome { margin: 0 18px 12px 58px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12.5px; color: var(--text-2); animation: ms-rise .4s var(--ease) both; }

/* ============================================================ incidents */
.ms-inc-card { position: relative; padding: 12px 14px; border-radius: 14px; background: var(--surface); border: 1px solid var(--border);
  transition: border-color .2s, transform .18s var(--ease), background .2s; }
.ms-inc-card.active { border-color: rgba(142,140,255,.55); background: linear-gradient(90deg, rgba(108,106,246,.12), rgba(108,106,246,.02) 70%), var(--surface);
  box-shadow: inset 3px 0 0 var(--accent-hi), 0 12px 30px -18px rgba(108,106,246,.7); }
.ms-inc-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.ms-inc-id { font-family: var(--font-mono); font-size: 12.5px; font-weight: 600; color: var(--text); }
.ms-inc-cust { margin-top: 6px; font-size: 13.5px; font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ms-inc-meta { margin-top: 7px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 11.5px; color: var(--text-3); }
.ms-inc-meta .ms-badge-ft { height: 20px; padding: 0 7px; font-size: 10px; }
.ms-rail-gap { height: 8px; }
.ms-case-head { position: relative; overflow: hidden; padding: 18px 20px; border-radius: var(--r-lg); border: 1px solid var(--border); box-shadow: var(--elev);
  background: radial-gradient(90% 140% at 100% 0%, color-mix(in srgb, var(--c, #6C6AF6) 14%, transparent), transparent 60%), var(--surface); }
.ms-case-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ms-case-id { font-family: var(--font-mono); font-size: 22px; font-weight: 650; letter-spacing: -.02em; color: var(--text); }
.ms-case-cust { margin-top: 8px; font-size: 15px; color: var(--text-2); }
.ms-case-cust b { color: var(--text); font-weight: 620; }
.ms-case-meta { margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
.ms-www { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.ms-www-card { padding: 13px 14px; border-radius: 13px; background: var(--surface); border: 1px solid var(--border); animation: ms-rise .5s var(--ease) both;
  animation-delay: calc(var(--i, 0) * 70ms); }
.ms-www-card .ms-label { display: flex; align-items: center; gap: 6px; margin-bottom: 7px; }
.ms-www-text { color: var(--text); font-size: 13.5px; line-height: 1.5; }
.ms-www-card.wrong { background: linear-gradient(180deg, rgba(240,97,109,.08), transparent 70%), var(--surface); border-color: rgba(240,97,109,.28); }
.ms-www-card.wrong .ms-label { color: #FF9AA3; }
.ms-www-card.wrong.healed .ms-www-text { text-decoration: line-through; text-decoration-color: rgba(240,97,109,.8); color: var(--text-2); }
.ms-www-card.truth { background: linear-gradient(180deg, rgba(61,214,140,.08), transparent 70%), var(--surface); border-color: rgba(61,214,140,.26); }
.ms-www-card.truth .ms-label { color: #86EFBC; }
.ms-banner { display: flex; align-items: center; gap: 12px; padding: 13px 16px; border-radius: 13px; font-size: 13.5px; }
.ms-banner .ms-i { width: 18px; height: 18px; }
.ms-banner.success { background: linear-gradient(90deg, rgba(61,214,140,.12), rgba(61,214,140,.03)); border: 1px solid rgba(61,214,140,.3); color: #C9F7DE; }
.ms-banner.success .ms-i { color: var(--success); }
.ms-banner.warning { background: linear-gradient(90deg, rgba(245,165,36,.12), rgba(245,165,36,.03)); border: 1px solid rgba(245,165,36,.32); color: #FFE2B3; }
.ms-banner.warning .ms-i { color: var(--warning); }
.ms-banner.info { background: linear-gradient(90deg, rgba(62,166,255,.1), rgba(62,166,255,.02)); border: 1px solid rgba(62,166,255,.28); color: #CDE8FF; }
.ms-banner.info .ms-i { color: var(--info); }
.ms-idl { position: relative; padding: 16px; border-radius: var(--r-lg); border: 1px solid rgba(255,139,62,.22);
  background: radial-gradient(60% 120% at 50% 0%, rgba(255,139,62,.08), transparent 70%), var(--surface); box-shadow: var(--elev); }
.ms-idl-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(150px, 230px) minmax(0, 1fr); align-items: center; gap: 0; }
.ms-entity { padding: 13px 14px; border-radius: 13px; background: var(--surface-2); border: 1px solid var(--border-strong); min-width: 0; animation: ms-rise .5s var(--ease) both; }
.ms-entity.b { border-color: rgba(255,139,62,.45); box-shadow: 0 0 26px -10px rgba(255,139,62,.6); animation-delay: .12s; }
.ms-entity-kind { display: flex; align-items: center; gap: 6px; color: var(--text-3); font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; }
.ms-entity-name { margin-top: 5px; font-size: 14.5px; font-weight: 640; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ms-entity .ms-tag { margin-top: 8px; }
.ms-conn { position: relative; height: 44px; display: grid; place-items: center; }
.ms-conn::before { content: ""; position: absolute; left: 0; right: 0; top: 50%; height: 2px; transform: translateY(-50%);
  background: linear-gradient(90deg, rgba(142,140,255,.15), rgba(142,140,255,.95), rgba(255,139,62,.95), rgba(255,139,62,.15));
  background-size: 200% 100%; animation: ms-flow 2.2s linear infinite; border-radius: 2px; }
.ms-conn::after { content: ""; position: absolute; left: 6%; right: 6%; top: 50%; height: 2px; transform: translateY(-50%);
  background: repeating-linear-gradient(90deg, rgba(255,255,255,.85) 0 3px, transparent 3px 14px); opacity: .35; animation: ms-dash 1.1s linear infinite; }
.ms-conn-node { position: relative; z-index: 1; display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 12px; border-radius: 999px;
  background: #15131F; border: 1px solid rgba(255,139,62,.55); color: #FFD2B0; font-size: 13px; font-weight: 720; font-variant-numeric: tabular-nums;
  white-space: nowrap; box-shadow: 0 0 0 4px rgba(255,139,62,.08), 0 0 26px -4px rgba(255,139,62,.75); animation: ms-glow-breathe 2.8s ease-in-out infinite; }
.ms-conn-cap { position: absolute; left: 0; right: 0; top: calc(50% + 20px); text-align: center; font-size: 10.5px; font-weight: 650;
  letter-spacing: .08em; text-transform: uppercase; color: #FFB27A; opacity: .85; white-space: nowrap; }
.ms-conn.diff .ms-conn-node { border-color: rgba(255,255,255,.25); color: var(--text-2); box-shadow: none; animation: none; }
.ms-conn.diff::before { background: rgba(255,255,255,.12); animation: none; }
.ms-quote { margin-top: 12px; padding: 10px 12px; border-radius: 10px; border-left: 2px solid rgba(255,139,62,.6); background: rgba(255,255,255,.02); color: var(--text); font-size: 13px; }
.ms-quote .ms-mono { color: #FFC08F; }
.ms-idl-reason { margin-top: 8px; color: var(--text-3); font-size: 12.5px; }
.ms-blast { height: 100%; padding: 16px; border-radius: var(--r-lg); border: 1px solid var(--border); background: radial-gradient(80% 100% at 100% 0%, rgba(240,97,109,.1), transparent 60%), var(--surface);
  box-shadow: var(--elev); display: flex; flex-direction: column; gap: 6px; }
.ms-blast-n { font-size: 44px; font-weight: 720; letter-spacing: -.04em; line-height: 1; color: #FFB0B7; font-variant-numeric: tabular-nums; }
.ms-blast-label { color: var(--text-2); font-size: 13px; }
.ms-plan { padding: 16px 18px; border-radius: var(--r-lg); border: 1px solid var(--border); background: var(--surface); box-shadow: var(--elev); }
.ms-plan ol { list-style: none; margin: 10px 0 0; padding: 0; display: grid; gap: 8px; }
.ms-plan li { display: grid; grid-template-columns: 26px 1fr; gap: 10px; align-items: start; color: var(--text); font-size: 13.5px; }
.ms-plan-n { width: 22px; height: 22px; border-radius: 7px; display: grid; place-items: center; font-family: var(--font-mono); font-size: 11px; color: var(--accent-hi);
  background: rgba(108,106,246,.12); border: 1px solid rgba(142,140,255,.3); }
.ms-plan-policy { margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.ms-heal { position: relative; overflow: hidden; display: flex; align-items: center; gap: 14px; padding: 16px 18px; border-radius: var(--r-lg);
  border: 1px solid rgba(61,214,140,.4); background: radial-gradient(90% 160% at 0% 50%, rgba(61,214,140,.18), transparent 60%), var(--surface);
  box-shadow: 0 0 0 1px rgba(61,214,140,.08), 0 20px 50px -26px rgba(61,214,140,.75); }
.ms-heal.anim { animation: ms-heal .75s var(--ease) both; }
.ms-heal-icon { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; color: #06170F; flex: none;
  background: linear-gradient(135deg, #6BF5B2, #29B873); box-shadow: 0 0 26px rgba(61,214,140,.6); }
.ms-heal-icon .ms-i { width: 20px; height: 20px; }
.ms-heal.anim .ms-heal-icon { animation: ms-pop .6s var(--ease) both .2s; }
.ms-heal-title { font-weight: 680; color: #D6FBE8; font-size: 15px; }
.ms-heal-sub { color: #9FE3C1; font-size: 13px; margin-top: 2px; }
.ms-checks { display: grid; gap: 8px; margin-top: 10px; }
.ms-check { display: grid; grid-template-columns: 30px 1fr auto; gap: 12px; align-items: center; padding: 11px 13px; border-radius: 12px; background: var(--surface); border: 1px solid var(--border); }
.ms-check-q { color: var(--text); font-size: 13.5px; font-weight: 540; }
.ms-check-r { color: var(--text-3); font-size: 12px; margin-top: 2px; }
.ms-flip { width: 28px; height: 28px; perspective: 500px; }
.ms-flip-in { position: relative; width: 100%; height: 100%; transform-style: preserve-3d; transform: rotateY(180deg); }
.ms-flip.anim .ms-flip-in { animation: ms-flip .75s var(--ease) both; animation-delay: calc(.35s + var(--i, 0) * .25s); }
.ms-flip.fail .ms-flip-in { transform: none; animation: none; }
.ms-face { position: absolute; inset: 0; border-radius: 50%; display: grid; place-items: center; backface-visibility: hidden; -webkit-backface-visibility: hidden; }
.ms-face .ms-i { width: 15px; height: 15px; }
.ms-face.front { color: var(--danger); background: rgba(240,97,109,.14); border: 1px solid rgba(240,97,109,.5); }
.ms-face.back { color: #06170F; background: linear-gradient(135deg, #6BF5B2, #29B873); transform: rotateY(180deg); box-shadow: 0 0 16px rgba(61,214,140,.5); }
.ms-rollback { padding: 14px 16px; border-radius: 13px; border: 1px solid rgba(245,165,36,.38); background: linear-gradient(90deg, rgba(245,165,36,.1), transparent 70%), var(--surface);
  box-shadow: inset 3px 0 0 var(--warning); animation: ms-rise .5s var(--ease) both; }
.ms-rollback + .ms-rollback { margin-top: 8px; }
.ms-rb-title { display: flex; align-items: center; gap: 8px; font-weight: 640; color: #FFD9A0; font-size: 13.5px; }
.ms-rb-title .ms-i { color: var(--warning); }
.ms-rb-body { margin-top: 5px; color: var(--text-2); font-size: 12.5px; }
.ms-rb-next { margin-top: 8px; display: flex; align-items: center; gap: 8px; color: #FFE2B3; font-size: 12.5px; }
.ms-ba { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.ms-ba-card { padding: 14px 15px; border-radius: 13px; border: 1px solid var(--border); background: var(--surface); }
.ms-ba-card.before { border-color: rgba(240,97,109,.28); background: linear-gradient(180deg, rgba(240,97,109,.07), transparent 70%), var(--surface); }
.ms-ba-card.after { border-color: rgba(61,214,140,.32); background: linear-gradient(180deg, rgba(61,214,140,.08), transparent 70%), var(--surface); animation: ms-rise .55s var(--ease) both .1s; }
.ms-ba-card .ms-label { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.ms-ba-text { color: var(--text); font-size: 13.5px; line-height: 1.55; }
.ms-actions { display: grid; gap: 6px; }
.ms-action { display: grid; grid-template-columns: 30px 1fr auto; gap: 10px; align-items: center; padding: 9px 12px; border-radius: 11px; background: var(--surface); border: 1px solid var(--border); font-size: 13px; color: var(--text); }
.ms-action-ic { width: 26px; height: 26px; border-radius: 8px; display: grid; place-items: center; color: var(--accent-hi); background: rgba(108,106,246,.1); border: 1px solid rgba(142,140,255,.25); }

/* ============================================================ autonomy */
.ms-policy { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.ms-feed { position: relative; list-style: none; margin: 0; padding: 4px 0 0; }
.ms-feed-item { position: relative; display: grid; grid-template-columns: 30px 1fr auto; gap: 12px; padding: 10px 0; }
.ms-feed-item.anim { animation: ms-rise .45s var(--ease) both; animation-delay: calc(var(--i, 0) * 45ms); }
.ms-feed-item::before { content: ""; position: absolute; left: 14.5px; top: 40px; bottom: -10px; width: 1px; background: rgba(255,255,255,.07); }
.ms-feed-item:last-child::before { display: none; }
.ms-feed-ic { width: 30px; height: 30px; border-radius: 10px; display: grid; place-items: center; border: 1px solid; position: relative; z-index: 1; }
.ms-feed-ic .ms-i { width: 15px; height: 15px; }
.ms-feed-title { color: var(--text); font-size: 13.5px; font-weight: 560; }
.ms-feed-detail { color: var(--text-3); font-size: 12.5px; margin-top: 2px; }
.ms-feed-time { color: var(--text-3); font-size: 11.5px; font-family: var(--font-mono); white-space: nowrap; padding-top: 3px; }
.ms-finding { display: grid; grid-template-columns: 34px 1fr auto; gap: 12px; align-items: start; padding: 13px 14px; border-radius: 13px; background: var(--surface);
  border: 1px solid var(--border); animation: ms-rise .45s var(--ease) both; animation-delay: calc(var(--i, 0) * 60ms); }
.ms-finding + .ms-finding { margin-top: 8px; }
.ms-finding.prevented { border-color: rgba(61,214,140,.3); } .ms-finding.pending { border-color: rgba(245,165,36,.35); } .ms-finding.dismissed { opacity: .88; }
.ms-finding-ic { width: 34px; height: 34px; border-radius: 11px; display: grid; place-items: center; border: 1px solid; }
.ms-finding-title { color: var(--text); font-weight: 620; font-size: 14px; }
.ms-finding-sub { margin-top: 5px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.ms-finding-reason { margin-top: 7px; color: var(--text-2); font-size: 12.5px; }
.ms-approval { padding: 15px 16px; border-radius: 14px; border: 1px solid rgba(245,165,36,.36); background: linear-gradient(90deg, rgba(245,165,36,.09), transparent 60%), var(--surface);
  box-shadow: inset 3px 0 0 var(--warning); }
.ms-approval-title { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; font-weight: 640; color: var(--text); font-size: 14px; }
.ms-approval-body { margin-top: 7px; color: var(--text-2); font-size: 13px; }
.ms-proposal { padding: 14px 16px; border-radius: 14px; border: 1px solid var(--border); background: var(--surface); }
.ms-proposal.prevented { border-color: rgba(61,214,140,.3); } .ms-proposal.rejected { opacity: .7; }

/* ============================================================ learning */
.ms-chart-title { display: flex; align-items: center; gap: 8px; font-weight: 640; font-size: 14px; color: var(--text); }
.ms-chart-title .ms-i { color: var(--accent-hi); }
.ms-chart-sub { color: var(--text-3); font-size: 12.5px; margin-top: 3px; }
.ms-rules { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 10px; }
.ms-rule-more summary { list-style: none; cursor: pointer; }
.ms-rule-more summary::-webkit-details-marker { display: none; }
.ms-rule-more[open] summary .ms-rule-text { display: none; }
.ms-rule-text.full { -webkit-line-clamp: unset; display: block; }
.ms-more { display: inline-block; margin-top: 6px; font-size: 12px; font-weight: 600; color: var(--accent-hi); }
.ms-rule-more[open] .ms-more { display: none; }
.ms-rule { position: relative; padding: 15px 16px; border-radius: 14px; background: radial-gradient(100% 120% at 0% 0%, rgba(108,106,246,.12), transparent 55%), var(--surface);
  border: 1px solid rgba(142,140,255,.25); box-shadow: var(--elev); animation: ms-rise .5s var(--ease) both; animation-delay: calc(var(--i, 0) * 70ms); }
.ms-rule-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.ms-rule-id { font-family: var(--font-mono); font-size: 12.5px; font-weight: 600; color: #C9C8FF; }
.ms-rule-text { margin-top: 9px; color: var(--text); font-size: 13px; line-height: 1.55; display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden; }
.ms-rule-foot { margin-top: 10px; display: flex; gap: 6px; flex-wrap: wrap; }
.ms-exc { padding: 13px 15px; border-radius: 13px; background: var(--surface); border: 1px solid rgba(240,97,109,.22); box-shadow: inset 3px 0 0 rgba(240,97,109,.6); }
.ms-exc + .ms-exc { margin-top: 8px; }
.ms-exc-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ms-exc-text { margin-top: 7px; color: var(--text-2); font-size: 12.5px; }
.ms-obs { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); }
.ms-obs-item { display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: start; padding: 11px 13px; border-radius: 12px; background: var(--surface); border: 1px solid var(--border); color: var(--text); font-size: 13px; }
.ms-proof { display: inline-flex; align-items: center; gap: 5px; height: 22px; padding: 0 8px; border-radius: 999px; font-size: 11.5px; font-weight: 650; color: #B9B8FF;
  background: rgba(108,106,246,.12); border: 1px solid rgba(142,140,255,.3); font-variant-numeric: tabular-nums; white-space: nowrap; }
.ms-diff { border-radius: 12px; border: 1px solid var(--border); background: #08090D; overflow: hidden; }
.ms-diff-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 12px; border-bottom: 1px solid var(--border); font-size: 12px; color: var(--text-2); }
.ms-diff-body { max-height: 360px; overflow: auto; padding: 6px 0; font-family: var(--font-mono); font-size: 11.5px; line-height: 1.6; }
.ms-dl { padding: 0 12px; white-space: pre-wrap; word-break: break-word; color: var(--text-3); }
.ms-dl.add { color: #9DF3C8; background: rgba(61,214,140,.08); box-shadow: inset 2px 0 0 var(--success); }
.ms-dl.del { color: #FFB0B7; background: rgba(240,97,109,.08); box-shadow: inset 2px 0 0 var(--danger); }
.ms-dl.hunk { color: var(--accent-hi); background: rgba(108,106,246,.07); }

/* ============================================================ review fixes */
.ms-trace-divider { display: flex; align-items: center; gap: 8px; margin: 10px 18px 0; padding: 8px 12px; border-radius: 10px;
  font-size: 12.5px; font-weight: 600; color: #FFD9A0; background: rgba(245,165,36,.07); border: 1px dashed rgba(245,165,36,.35); }
.ms-folded { display: inline-flex; align-items: center; gap: 7px; margin: 10px 18px 0 58px; padding: 4px 10px; border-radius: 999px; font-size: 12px;
  color: var(--text-3); background: rgba(255,255,255,.03); border: 1px solid var(--border); }
.ms-trace-note { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 14px 18px; color: var(--text-2); font-size: 13px; }
.ms-blast-n.zero { color: #86EFBC; }
.ms-plan-policy .ms-chip { white-space: normal; height: auto; min-height: 24px; padding-top: 3px; padding-bottom: 3px; line-height: 1.35; max-width: 100%; }
.stApp .st-key-feedback-row [data-testid="stElementContainer"]:has(.ms-kicker) { flex: 0 0 auto; width: auto; }
.stApp .st-key-feedback-row .ms-kicker { margin: 0 6px 0 0; }
.ms-inc-meta { flex-wrap: nowrap; white-space: nowrap; overflow: hidden; }
.ms-inc-meta > span + span::before { content: "·"; margin-right: 6px; color: var(--text-4); }
.stApp .stVerticalBlock[class*="st-key-cc-"]:focus-within .ms-card-click { box-shadow: none; }
.stApp .stVerticalBlock[class*="st-key-cc-"]:has(button:focus-visible) .ms-card-click { box-shadow: var(--ring); }
@media (min-width: 901px) {
  .stApp [data-testid="stColumn"]:has([class*="st-key-cc-inc-"]) { position: sticky; top: 12px; align-self: flex-start; }
}
/* playbook: an inset reading pane with the app's type scale */
.stApp .stVerticalBlock.st-key-pb-scroll { background: #08090D; border: 1px solid var(--border); border-radius: 12px; padding: 4px 16px; }
.stApp .st-key-pb-scroll h1 { font-size: 18px; margin: 6px 0 8px; }
.stApp .st-key-pb-scroll h2 { font-size: 15px; font-weight: 640; margin: 18px 0 6px; }
.stApp .st-key-pb-scroll h3, .stApp .st-key-pb-scroll h4 { font-size: 13.5px; font-weight: 640; margin: 14px 0 4px; }
.stApp .st-key-pb-scroll p, .stApp .st-key-pb-scroll li { font-size: 13.5px; color: var(--text-2); }
.stApp .st-key-pb-scroll code { color: #C9C8FF; background: rgba(108,106,246,.12); }
/* the report panel hands its frame to the live trace card */
.stApp .stVerticalBlock.st-key-panel-report:has(.ms-trace) { background: none; border: 0; padding: 0; box-shadow: none; }
/* equal-height chart panels */
.stApp .stVerticalBlock[class*="st-key-panel-chart-"] { height: 100%; }

/* ============================================================ tones (win over component bases: specificity 0,2,0) */
[class*="ms-"].ms-tone-accent { color: #B9B8FF; background: rgba(108,106,246,.12); border-color: rgba(142,140,255,.34); }
[class*="ms-"].ms-tone-success { color: #86EFBC; background: rgba(61,214,140,.10); border-color: rgba(61,214,140,.32); }
[class*="ms-"].ms-tone-danger { color: #FF9AA3; background: rgba(240,97,109,.10); border-color: rgba(240,97,109,.34); }
[class*="ms-"].ms-tone-warning { color: #FFC56B; background: rgba(245,165,36,.10); border-color: rgba(245,165,36,.34); }
[class*="ms-"].ms-tone-info { color: #8CCBFF; background: rgba(62,166,255,.10); border-color: rgba(62,166,255,.32); }
[class*="ms-"].ms-tone-muted { color: var(--text-3); background: transparent; }
.ms-feed-scroll { padding-right: 4px; }
.stApp .stVerticalBlock.st-key-feed-scroll { scrollbar-width: thin; scrollbar-color: rgba(255,255,255,.12) transparent; }

/* ============================================================ motion */
@keyframes ms-rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes ms-glow-drift { 0% { transform: translate3d(-3%, 1%, 0) scale(1); } 100% { transform: translate3d(3%, -3%, 0) scale(1.07); } }
@keyframes ms-sheen { to { background-position: -200% center; } }
@keyframes ms-pulse-dot { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, currentColor 60%, transparent); } 70% { box-shadow: 0 0 0 7px transparent; } 100% { box-shadow: 0 0 0 0 transparent; } }
@keyframes ms-pulse-ring { 0% { box-shadow: 0 0 0 0 rgba(142,140,255,.55); } 70% { box-shadow: 0 0 0 9px rgba(142,140,255,0); } 100% { box-shadow: 0 0 0 0 rgba(142,140,255,0); } }
@keyframes ms-glow-breathe { 0%, 100% { filter: brightness(1); } 50% { filter: brightness(1.18); } }
@keyframes ms-count { from { --n: var(--from, 0); } to { --n: var(--to); } }
@keyframes ms-word { from { opacity: 0; filter: blur(5px); transform: translateY(3px); } to { opacity: 1; filter: none; transform: none; } }
@keyframes ms-shimmer { 0% { background-position: 100% 50%; } 100% { background-position: 0 50%; } }
@keyframes ms-shimmer-text { to { background-position: -200% center; } }
@keyframes ms-flow { to { background-position: -200% 0; } }
@keyframes ms-dash { to { background-position: 14px 0; } }
@keyframes ms-strike { from { background-size: 0 1.5px; } to { background-size: 100% 1.5px; } }
@keyframes ms-fade-struck { from { opacity: 1; filter: none; } to { opacity: .58; filter: saturate(.45); } }
@keyframes ms-heal { 0% { opacity: 0; transform: scale(.97); box-shadow: 0 0 0 0 rgba(61,214,140,.5); } 60% { opacity: 1; transform: scale(1.005); box-shadow: 0 0 0 10px rgba(61,214,140,0); } 100% { transform: none; } }
@keyframes ms-flip { from { transform: rotateY(0deg); } to { transform: rotateY(180deg); } }
@keyframes ms-pop { 0% { transform: scale(.35); opacity: 0; } 70% { transform: scale(1.12); opacity: 1; } 100% { transform: scale(1); } }
@keyframes ms-chart-in { from { opacity: 0; clip-path: inset(0 100% 0 0); } to { opacity: 1; clip-path: inset(0 0 0 0); } }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; scroll-behavior: auto !important; }
}

/* ============================================================ responsive */
@media (max-width: 640px) {
  .stApp [data-testid="stHorizontalBlock"]:has(.ms-metric) { flex-wrap: wrap; gap: 8px; }
  .stApp [data-testid="stHorizontalBlock"]:has(.ms-metric) > [data-testid="stColumn"] { flex: 1 1 calc(33.333% - 6px) !important;
    min-width: calc(33.333% - 6px) !important; width: auto !important; }
  .stApp [data-testid="stHorizontalBlock"]:has(.ms-metric) > [data-testid="stColumn"]:first-child { flex-basis: 100% !important; min-width: 100% !important; }
  .ms-metric { min-height: 0; padding: 11px 12px; } .ms-metric-value { font-size: 22px; margin-top: 7px; } .ms-metric-note { display: none; }
  .ms-metric-value .unit, .ms-metric-value .to { font-size: 13px; } .ms-metric-top { font-size: 11.5px; }
  .ms-hero { padding: 14px 16px; margin-bottom: 10px; } .ms-tagline { display: none; } .ms-hero-pills .ms-pill code { display: none; }
  .ms-logo { width: 38px; height: 38px; } .ms-title { font-size: 21px; }
  .stApp .st-key-nav [data-testid="stTab"] { padding: 0 9px; } .stApp .st-key-nav [data-testid="stTab"] p { font-size: 13px; }
  .ms-chip { white-space: normal; height: auto; min-height: 24px; padding-top: 3px; padding-bottom: 3px; line-height: 1.35; max-width: 100%; }
  .stApp [class*="st-key-approve-row-"], .stApp [class*="st-key-prop-row-"] { flex-wrap: wrap; }
  .stApp [class*="st-key-approve-row-"] [data-testid="stElementContainer"]:has(input),
  .stApp [class*="st-key-prop-row-"] [data-testid="stElementContainer"]:has(input) { flex: 1 1 100%; min-width: 100%; }
}
@media (max-width: 900px) {
  .stApp [data-testid="stMainBlockContainer"] { padding: .75rem 1rem 4rem; }
  .ms-hero { padding: 18px; } .ms-title { font-size: 23px; } .ms-hero-pills { justify-content: flex-start; }
  .ms-www, .ms-ba { grid-template-columns: 1fr; }
  .ms-idl-row { grid-template-columns: 1fr; gap: 8px; }
  .ms-conn { height: 64px; }
  .ms-conn::before { left: 50%; right: auto; top: 0; bottom: 0; width: 2px; height: auto; transform: translateX(-50%);
    background: linear-gradient(180deg, rgba(142,140,255,.15), rgba(142,140,255,.95), rgba(255,139,62,.95), rgba(255,139,62,.15)); }
  .ms-conn::after { display: none; }
  .ms-conn-cap { top: auto; bottom: 22px; left: calc(50% + 56px); right: auto; text-align: left; }
  .ms-answer-body, .ms-answer-foot { padding-left: 18px; } .ms-watch { margin-left: 18px; }
  .ms-outcome { margin-left: 18px; }
}
"""

COMPACT_CSS = r"""
.ms-hero { padding: 12px 18px; margin-bottom: 10px; } .ms-logo { width: 34px; height: 34px; border-radius: 10px; }
.ms-logo .ms-i { width: 18px; height: 18px; } .ms-title { font-size: 20px; } .ms-tagline { display: none; }
.ms-metric { min-height: 0; padding: 10px 14px; } .ms-metric-value { font-size: 22px; margin-top: 6px; }
.ms-metric-value .unit, .ms-metric-value .to { font-size: 13px; } .ms-metric-note { display: none; }
"""

_BAD = re.compile(r"<[A-Za-z/!?]")


def css() -> str:
    """The full stylesheet. Never contains '<' + letter (DOMPurify would drop the whole <style>)."""
    text = _CSS + "\n" + _icon_css()
    bad = _BAD.search(text)
    assert bad is None, f"stylesheet contains {text[bad.start():bad.start() + 20]!r}; escape '<' as \\3c"
    return text


_STYLE_TAG = None


def inject() -> None:
    """Inject the stylesheet (one style-only st.html; takes no layout space). Call once at the top of every run."""
    global _STYLE_TAG
    if _STYLE_TAG is None:
        _STYLE_TAG = f"<style>{css()}</style>"
    st.html(_STYLE_TAG)


def inject_compact(compact: bool) -> None:
    """A compact hero + KPI strip on the working tabs, done with CSS only (the hero/KPI HTML stays identical)."""
    assert _BAD.search(COMPACT_CSS) is None
    st.html(f"<style>{COMPACT_CSS}</style>" if compact else "<style>.ms-compact-off{}</style>")


def style_fig(fig, height: int = 300, legend: bool = True):
    """Dark, quiet Plotly styling that matches the design system."""
    t = TOKENS
    fig.update_layout(
        height=height, margin={"l": 8, "r": 8, "t": 28 if legend else 12, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"family": t["font_sans"], "size": 12, "color": t["text2"]},
        hoverlabel={"bgcolor": t["surface2"], "bordercolor": "rgba(142,140,255,.4)",
                    "font": {"family": t["font_sans"], "color": t["text"], "size": 12}},
        showlegend=legend,
        legend={"orientation": "h", "x": 0, "y": 1.12, "xanchor": "left", "yanchor": "bottom",
                "bgcolor": "rgba(0,0,0,0)", "font": {"size": 11.5, "color": t["text2"]}},
        transition={"duration": 500, "easing": "cubic-in-out"},
        bargap=0.34, bargroupgap=0.12,
    )
    axis = {"gridcolor": "rgba(255,255,255,0.05)", "zeroline": False, "linecolor": "rgba(255,255,255,0.08)",
            "tickfont": {"color": t["text3"], "size": 11.5}, "title": {"font": {"color": t["text3"], "size": 11.5}},
            "automargin": True}
    fig.update_xaxes(**axis, showgrid=False)
    fig.update_yaxes(**axis)
    return fig
