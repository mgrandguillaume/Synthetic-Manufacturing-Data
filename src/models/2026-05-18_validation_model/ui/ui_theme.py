"""
Engineering-style theme for the Assembly Factory Streamlit UI.

Drop this file at  ui/ui_theme.py  and call `ui_theme.apply()` at the very top
of every page (right after `st.set_page_config` in home.py, or right after the
imports in each pages/*.py).

Provides
--------
apply(title=None, eyebrow=None)
    Inject the CSS overrides. Optionally render a top-of-page title block.

section(name, meta=None)
    Render a small schematic section header  ──  used in place of `st.subheader`
    when you want the engineering look.

kv(pairs)
    Render a key/value block (monospace, two columns). Pass a list of
    (key, value) tuples.
"""

from typing import Iterable, Optional, Tuple

import streamlit as st


# ── CSS ──────────────────────────────────────────────────────────────────────
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --af-ink:    #1c1c1c;
  --af-ink-2:  #3a3a3a;
  --af-ink-3:  #6a6a6a;
  --af-ink-4:  #9a9a9a;
  --af-paper:  #ffffff;
  --af-paper-2:#f7f7f5;
  --af-rule:   #d9d9d4;
  --af-ok:     #2f7a3f;
  --af-warn:   #b8541a;
  --af-sans:   "IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --af-mono:   "JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace;
}

/* Base typography ---------------------------------------------------------- */
html, body, .stApp, [class*="css"] {
  font-family: var(--af-sans) !important;
  -webkit-font-smoothing: antialiased;
  color: var(--af-ink);
}
.stApp h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.01em; margin: 0 0 14px; }
.stApp h2 { font-size: 16px; font-weight: 600; margin: 22px 0 8px;
            padding-bottom: 6px; border-bottom: 1px solid var(--af-rule); }
.stApp h3 { font-size: 14px; font-weight: 600; margin: 16px 0 6px; }

/* Captions = monospace eyebrow */
[data-testid="stCaptionContainer"], .stCaption {
  font-family: var(--af-mono) !important;
  font-size: 11px !important;
  letter-spacing: 0.05em !important;
  color: var(--af-ink-3) !important;
}

code, kbd, samp, pre,
.stCodeBlock, [data-testid="stCodeBlock"] { font-family: var(--af-mono) !important; }

/* Page container ----------------------------------------------------------- */
.main .block-container,
[data-testid="stMain"] .block-container {
  padding-top: 2rem;
  padding-bottom: 4rem;
  max-width: 1280px;
}
[data-testid="stToolbar"], #MainMenu, footer { visibility: hidden; }
[data-testid="stHeader"] { background: transparent !important; }

/* Sidebar — DARK ----------------------------------------------------------- */
[data-testid="stSidebar"] {
  background-color: #161616 !important;
  border-right: 1px solid var(--af-ink);
}
[data-testid="stSidebar"] * { color: #eaeaea !important; }
[data-testid="stSidebar"] a,
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] {
  color: #c8c8c8 !important;
  font-family: var(--af-sans) !important;
  font-size: 13px !important;
  padding: 6px 14px !important;
  border-left: 2px solid transparent !important;
  border-radius: 0 !important;
}
[data-testid="stSidebar"] a[aria-current="page"],
[data-testid="stSidebar"] a:hover {
  background: #1f1f1f !important;
  color: #ffffff !important;
  border-left-color: #ffffff !important;
}
/* Sidebar section headings ("Engine" / "Analyse") */
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] [data-testid="stSidebarNavSection"] > div:first-child {
  font-family: var(--af-mono) !important;
  font-size: 10px !important;
  letter-spacing: 0.10em !important;
  text-transform: uppercase !important;
  color: #6a6a6a !important;
  font-weight: 500 !important;
  border: none !important;
  padding: 14px 16px 4px !important;
  margin: 0 !important;
}
/* Hide nav icons (we removed emoji anyway, but keep slot collapsed) */
[data-testid="stSidebarNavIcon"],
[data-testid="stSidebarNavLink"] svg { display: none !important; }

/* Buttons ----------------------------------------------------------------- */
.stButton > button,
.stDownloadButton > button,
.stFormSubmitButton > button {
  font-family: var(--af-sans) !important;
  font-weight: 500;
  font-size: 13px;
  padding: 6px 14px;
  border: 1px solid var(--af-ink) !important;
  border-radius: 2px !important;
  background: var(--af-paper);
  color: var(--af-ink);
  box-shadow: none !important;
  transition: background 0.1s;
}
.stButton > button:hover { background: var(--af-paper-2) !important; color: var(--af-ink) !important; }
.stButton > button[kind="primary"],
.stButton > button[data-testid="baseButton-primary"],
.stFormSubmitButton > button[kind="primary"] {
  background: var(--af-ink) !important;
  color: #ffffff !important;
  border-color: var(--af-ink) !important;
}
.stButton > button[kind="primary"]:hover { background: #000 !important; }

/* Metrics ----------------------------------------------------------------- */
[data-testid="stMetric"] {
  border: 1px solid var(--af-rule);
  border-radius: 2px;
  padding: 10px 14px;
  background: var(--af-paper);
}
[data-testid="stMetricLabel"] p,
[data-testid="stMetricLabel"] {
  font-family: var(--af-mono) !important;
  font-size: 10px !important;
  letter-spacing: 0.08em !important;
  text-transform: uppercase !important;
  color: var(--af-ink-3) !important;
}
[data-testid="stMetricValue"] {
  font-family: var(--af-mono) !important;
  font-size: 20px !important;
  font-weight: 500 !important;
  color: var(--af-ink) !important;
  letter-spacing: -0.01em;
}
[data-testid="stMetricDelta"] {
  font-family: var(--af-mono) !important;
  font-size: 10px !important;
}

/* Tabs -------------------------------------------------------------------- */
.stTabs [data-baseweb="tab-list"] {
  gap: 0 !important;
  border-bottom: 1px solid var(--af-ink) !important;
}
.stTabs [data-baseweb="tab"] {
  font-family: var(--af-mono) !important;
  font-size: 11px !important;
  letter-spacing: 0.04em !important;
  color: var(--af-ink-3) !important;
  background: var(--af-paper-2) !important;
  border: 1px solid var(--af-rule) !important;
  border-bottom: none !important;
  border-radius: 2px 2px 0 0 !important;
  padding: 6px 14px !important;
  margin-right: 0 !important;
  height: auto !important;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
  background: var(--af-paper) !important;
  color: var(--af-ink) !important;
  font-weight: 500 !important;
  border-color: var(--af-ink) !important;
  margin-bottom: -1px !important;
}
.stTabs [data-baseweb="tab-highlight"] { display: none !important; }

/* Inputs ------------------------------------------------------------------ */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-baseweb="select"] > div {
  font-family: var(--af-mono) !important;
  border-radius: 2px !important;
  background: var(--af-paper-2) !important;
  border-color: var(--af-rule) !important;
}

/* Widget labels = uppercase monospace eyebrow */
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] {
  font-family: var(--af-mono) !important;
  font-size: 10px !important;
  letter-spacing: 0.06em !important;
  text-transform: uppercase !important;
  color: var(--af-ink-3) !important;
  font-weight: 500 !important;
}

/* Divider ----------------------------------------------------------------- */
hr, [data-testid="stDivider"] {
  border: none !important;
  border-top: 1px solid var(--af-ink) !important;
  margin: 18px 0 !important;
}

/* Alerts ------------------------------------------------------------------ */
[data-testid="stAlert"] {
  border-radius: 2px !important;
  border: 1px solid var(--af-rule) !important;
  font-family: var(--af-sans) !important;
  font-size: 13px !important;
}
[data-testid="stAlert"] [data-testid="stMarkdownContainer"] p { margin: 0 !important; }

/* DataFrame --------------------------------------------------------------- */
[data-testid="stDataFrame"] {
  border: 1px solid var(--af-rule);
  border-radius: 2px;
}

/* Expander ---------------------------------------------------------------- */
[data-testid="stExpander"] {
  border: 1px solid var(--af-rule) !important;
  border-radius: 2px !important;
  background: var(--af-paper) !important;
}
[data-testid="stExpander"] summary {
  font-family: var(--af-sans) !important;
  font-weight: 500 !important;
  font-size: 13px !important;
}

/* Custom section header (af-section) -------------------------------------- */
.af-section-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 8px 12px;
  background: var(--af-paper-2);
  border: 1px solid var(--af-rule);
  border-bottom: none;
  border-radius: 2px 2px 0 0;
}
.af-section-head .h {
  font-family: var(--af-sans);
  font-size: 13px;
  font-weight: 600;
  color: var(--af-ink);
}
.af-section-head .meta {
  font-family: var(--af-mono);
  font-size: 10px;
  letter-spacing: 0.04em;
  color: var(--af-ink-3);
}

/* Custom KV block --------------------------------------------------------- */
.af-kv {
  font-family: var(--af-mono);
  font-size: 12px;
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 4px 18px;
  border: 1px solid var(--af-rule);
  border-radius: 2px;
  padding: 12px 14px;
  background: var(--af-paper);
}
.af-kv .k { color: var(--af-ink-3); }
.af-kv .v { color: var(--af-ink); }

/* Custom eyebrow ---------------------------------------------------------- */
.af-eyebrow {
  font-family: var(--af-mono);
  font-size: 11px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--af-ink-3);
  margin: 0 0 8px 0;
}
</style>
"""


def apply(title: Optional[str] = None, eyebrow: Optional[str] = None) -> None:
    """Inject the engineering CSS. Optionally render an eyebrow + H1.

    Use once per page, right after the page's imports / state.setup_path().
    """
    st.markdown(_CSS, unsafe_allow_html=True)
    if eyebrow is not None:
        st.markdown(f'<div class="af-eyebrow">{eyebrow}</div>', unsafe_allow_html=True)
    if title is not None:
        st.markdown(f"# {title}")


def section(name: str, meta: Optional[str] = None) -> None:
    """Schematic section header — bar with name on left, optional meta on right."""
    meta_html = f'<span class="meta">{meta}</span>' if meta else ""
    st.markdown(
        f'<div class="af-section-head"><span class="h">{name}</span>{meta_html}</div>',
        unsafe_allow_html=True,
    )


def kv(pairs: Iterable[Tuple[str, str]]) -> None:
    """Monospace key/value block."""
    rows = "".join(
        f'<span class="k">{k}</span><span class="v">{v}</span>'
        for k, v in pairs
    )
    st.markdown(f'<div class="af-kv">{rows}</div>', unsafe_allow_html=True)
