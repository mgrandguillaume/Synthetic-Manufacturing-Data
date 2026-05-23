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
    page_icon  = "🏭",
    layout     = "wide",
)


# ── Home page content ──────────────────────────────────────────────────────────
def _home() -> None:
    st.title("🏭 Assembly Factory")
    st.markdown(
        "A synthetic discrete-time manufacturing simulation. "
        "Use the **sidebar** to navigate between tools."
    )
    st.divider()

    st.subheader("Session status")
    st.caption("Tracks what has been run in the current browser session.")

    gen_done   = "gen_result"       in st.session_state
    sim_done   = "sim_result"       in st.session_state
    sweep_done = st.session_state.get("sweep_done",    False)
    val_done   = st.session_state.get("validate_done", False)
    avail_done = st.session_state.get("avail_done",    False)

    def _badge(done: bool) -> str:
        return "Done" if done else "Pending"

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Generate",    _badge(gen_done))
    c2.metric("Simulate",    _badge(sim_done))
    c3.metric("Sweep",       _badge(sweep_done))
    c4.metric("Validate",    _badge(val_done))
    c5.metric("Availability", _badge(avail_done))

    st.divider()
    st.subheader("Quick start")
    st.markdown("""
1. **Configure** — review and adjust the factory parameters in `config.yaml`.
2. **Generate** — build a factory structure from the config (or custom values).
3. **Simulate** — run a discrete-time simulation on the generated factory.
4. *Sweep** — sweep the parameter grid defined in `config.yaml → sweep:`.
5. *Validate** — run conservation, boundary, monotonicity, and statistical checks.
6. *Availability** — compute theoretical vs Monte Carlo system availability.
""")


# ── Navigation ─────────────────────────────────────────────────────────────────
pg = st.navigation(
    {
        "": [
            st.Page(_home,                    title="Home",        icon="🏠", default=True),
            st.Page("pages/0_Configure.py",   title="Configure",   icon="⚙️"),
        ],
        "Engine": [
            st.Page("pages/1_Generate.py",    title="Generate",    icon="🏗️"),
            st.Page("pages/2_Simulate.py",    title="Simulate",    icon="▶️"),
        ],
        "Analyse": [
            st.Page("pages/3_Sweep.py",       title="Sweep",       icon="📊"),
            st.Page("pages/4_Validate.py",    title="Validate",    icon="✅"),
            st.Page("pages/5_Availability.py",title="Availability", icon="📈"),
        ],
    }
)
pg.run()
