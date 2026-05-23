"""
Assembly Factory — Streamlit UI entry point.

Run with:  streamlit run ui/home.py
           (from the model root directory)
"""

import os
import sys

import streamlit as st

# ── Path setup ─────────────────────────────────────────────────────────────────
_UI_DIR     = os.path.dirname(os.path.abspath(__file__))
_MODEL_ROOT = os.path.normpath(os.path.join(_UI_DIR, ".."))
if _UI_DIR     not in sys.path: sys.path.insert(0, _UI_DIR)
if _MODEL_ROOT not in sys.path: sys.path.insert(0, _MODEL_ROOT)

# ── Global page config (set once here, not in individual pages) ────────────────
st.set_page_config(
    page_title = "Assembly Factory",
    layout     = "wide",
)

import ui_theme


# ── Home page content ──────────────────────────────────────────────────────────
def _home() -> None:
    ui_theme.apply(
        title   = "Assembly Factory",
        eyebrow = "project · overview",
    )
    st.markdown(
        "A synthetic discrete-time manufacturing simulation. "
        "Use the sidebar to navigate."
    )

    # ── Session status ─────────────────────────────────────────────────────────
    gen_done   = "gen_result"       in st.session_state
    sim_done   = "sim_result"       in st.session_state
    sweep_done = st.session_state.get("sweep_done",    False)
    val_done   = st.session_state.get("validate_done", False)
    avail_done = st.session_state.get("avail_done",    False)

    def _badge(done: bool) -> str:
        return "Done" if done else "—"

    st.markdown("## Session status")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Generate",     _badge(gen_done))
    c2.metric("Simulate",     _badge(sim_done))
    c3.metric("Sweep",        _badge(sweep_done))
    c4.metric("Validate",     _badge(val_done))
    c5.metric("Availability", _badge(avail_done))

    # ── Pipeline ──────────────────────────────────────────────────────────────
    st.markdown("## Pipeline")
    ui_theme.section("Steps", meta="6 stages")
    st.markdown(
        """
<div style="border:1px solid var(--af-rule); border-top:none; border-radius:0 0 2px 2px;
            padding:0; font-family: var(--af-mono); font-size:12px;">
  <div style="display:grid; grid-template-columns: 28px 1fr 90px; gap:0;
              padding:8px 14px; border-bottom:1px solid var(--af-rule);">
    <span style="color:var(--af-ink-3)">01</span>
    <span><b style="font-family:var(--af-sans); font-size:13px;">Configure</b> &nbsp;
          <span style="color:var(--af-ink-3)">review &amp; adjust config.yaml</span></span>
    <span style="text-align:right; color:var(--af-ink-3)">READY</span>
  </div>
  <div style="display:grid; grid-template-columns: 28px 1fr 90px; gap:0;
              padding:8px 14px; border-bottom:1px solid var(--af-rule);">
    <span style="color:var(--af-ink-3)">02</span>
    <span><b style="font-family:var(--af-sans); font-size:13px;">Generate</b> &nbsp;
          <span style="color:var(--af-ink-3)">build a factory from the config</span></span>
    <span style="text-align:right; color:var(--af-ink-3)">READY</span>
  </div>
  <div style="display:grid; grid-template-columns: 28px 1fr 90px; gap:0;
              padding:8px 14px; border-bottom:1px solid var(--af-rule);">
    <span style="color:var(--af-ink-3)">03</span>
    <span><b style="font-family:var(--af-sans); font-size:13px;">Simulate</b> &nbsp;
          <span style="color:var(--af-ink-3)">run a discrete-time simulation</span></span>
    <span style="text-align:right; color:var(--af-ink-3)">READY</span>
  </div>
  <div style="display:grid; grid-template-columns: 28px 1fr 90px; gap:0;
              padding:8px 14px; border-bottom:1px solid var(--af-rule);">
    <span style="color:var(--af-ink-3)">04</span>
    <span><b style="font-family:var(--af-sans); font-size:13px;">Sweep</b> &nbsp;
          <span style="color:var(--af-ink-3)">scan the parameter grid</span></span>
    <span style="text-align:right; color:var(--af-ink-3)">READY</span>
  </div>
  <div style="display:grid; grid-template-columns: 28px 1fr 90px; gap:0;
              padding:8px 14px; border-bottom:1px solid var(--af-rule);">
    <span style="color:var(--af-ink-3)">05</span>
    <span><b style="font-family:var(--af-sans); font-size:13px;">Validate</b> &nbsp;
          <span style="color:var(--af-ink-3)">conservation, boundary, monotonicity, statistical checks</span></span>
    <span style="text-align:right; color:var(--af-ink-3)">READY</span>
  </div>
  <div style="display:grid; grid-template-columns: 28px 1fr 90px; gap:0;
              padding:8px 14px;">
    <span style="color:var(--af-ink-3)">06</span>
    <span><b style="font-family:var(--af-sans); font-size:13px;">Availability</b> &nbsp;
          <span style="color:var(--af-ink-3)">theoretical vs Monte Carlo system availability</span></span>
    <span style="text-align:right; color:var(--af-ink-3)">READY</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


# ── Navigation ─────────────────────────────────────────────────────────────────
pg = st.navigation(
    {
        "": [
            st.Page(_home,                     title="Home",         default=True),
            st.Page("pages/0_Configure.py",    title="Configure"),
        ],
        "Engine": [
            st.Page("pages/1_Generate.py",     title="Generate"),
            st.Page("pages/2_Simulate.py",     title="Simulate"),
        ],
        "Analyse": [
            st.Page("pages/3_Sweep.py",        title="Sweep"),
            st.Page("pages/4_Validate.py",     title="Validate"),
            st.Page("pages/5_Availability.py", title="Availability"),
        ],
    }
)
pg.run()
