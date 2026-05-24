"""
Server-side state store for the Assembly Factory Dash UI.

Replaces Streamlit's st.session_state. A plain dict is used since this
is a single-user research tool — no authentication or multi-tenancy needed.

Usage
-----
    import store

    store.set("gen_result", result)
    result = store.get("gen_result")
"""
import os
import sys

_UI_DIR     = os.path.dirname(os.path.abspath(__file__))
_MODEL_ROOT = os.path.normpath(os.path.join(_UI_DIR, ".."))
if _UI_DIR     not in sys.path: sys.path.insert(0, _UI_DIR)
if _MODEL_ROOT not in sys.path: sys.path.insert(0, _MODEL_ROOT)

# ── Public paths ───────────────────────────────────────────────────────────────
MODEL_ROOT  = _MODEL_ROOT
CONFIG_PATH = os.path.join(MODEL_ROOT, "config.yaml")

# ── State dict ─────────────────────────────────────────────────────────────────
_store: dict = {
    "gen_result":      None,  # dict returned by generate_from_params / generate_simple_assembly
    "sim_result":      None,  # dict of DataFrames from simulate()
    "sim_figures":     None,  # cached Plotly figure dicts (avoids rebuilding on page revisit)
    "sim_params":      None,  # last-used simulate() parameters (restored on page revisit)
    "sweep_done":      False,
    "validate_done":   False,
    "validate_passed": None,
    "avail_done":      False,
    "avail_theo_mid":  None,
    "avail_theo_int":  None,
    "avail_exp":       None,
    "avail_gen":       None,
    "avail_n_reps":    None,
}


def get(key: str, default=None):
    return _store.get(key, default)


def set(key: str, value) -> None:
    _store[key] = value
