"""Sweep page — run the parameter sweep defined in config.yaml."""

import os
import sys
import itertools

import streamlit as st
import yaml

# ── Path setup ─────────────────────────────────────────────────────────────────
_UI_DIR     = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_MODEL_ROOT = os.path.normpath(os.path.join(_UI_DIR, ".."))
if _UI_DIR     not in sys.path: sys.path.insert(0, _UI_DIR)
if _MODEL_ROOT not in sys.path: sys.path.insert(0, _MODEL_ROOT)

import state
state.setup_path()

from analysis.sweep.sweep          import main as run_sweep
from analysis.sweep.visualize_sweep import show as sweep_show

_SWEEP_DIR = os.path.join(_MODEL_ROOT, "analysis", "sweep", "sweep_output")

# ── Page ───────────────────────────────────────────────────────────────────────
st.title("📊 Parameter Sweep")
st.caption("Reads sweep grid from `config.yaml → sweep:` and simulation parameters from `config.yaml → simulation:`.")

# ── Sweep grid preview ─────────────────────────────────────────────────────────
with open(state.CONFIG_PATH) as f:
    cfg = yaml.safe_load(f)

sweep_cfg = cfg.get("sweep", {})

def _expand(val):
    if isinstance(val, dict):
        start, stop, step = val["min"], val["max"], val["step"]
        out, v = [], start
        while v <= stop + step * 1e-9:
            out.append(round(v, 10))
            v += step
        return out
    elif isinstance(val, list):
        return val
    else:
        return [val]

expanded = {k: _expand(v) for k, v in sweep_cfg.items()}
n_combinations = len(list(itertools.product(*expanded.values()))) if expanded else 0

st.subheader("Sweep grid")
col1, col2 = st.columns([2, 1])
with col1:
    rows = [{"Parameter": k, "Values": str(vals), "Count": len(vals)}
            for k, vals in expanded.items()]
    import pandas as pd
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
with col2:
    st.metric("Total combinations", f"{n_combinations:,}")
    st.caption("Each combination runs generate + simulate once.")

# ── Run button ─────────────────────────────────────────────────────────────────
st.divider()
if st.button("📊 Run sweep", type="primary", use_container_width=True):
    with st.spinner(f"Running {n_combinations:,} combinations — this may take several minutes…"):
        run_sweep()
    state.set("sweep_done", True)
    st.success("Sweep complete.")

# ── Display charts ─────────────────────────────────────────────────────────────
if state.get("sweep_done"):
    csv_files = [os.path.join(_SWEEP_DIR, f)
                 for f in ["gen_stats.csv","state_summary.csv","utilization.csv",
                            "throughput.csv","costs.csv"]]
    if all(os.path.exists(p) for p in csv_files):
        with st.spinner("Rendering sweep charts…"):
            fig = sweep_show(_SWEEP_DIR)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Click **Run sweep** to generate results.")
elif os.path.isdir(_SWEEP_DIR) and os.path.exists(os.path.join(_SWEEP_DIR, "gen_stats.csv")):
    st.info("Previous sweep output found on disk. Click **Run sweep** to refresh, or expand to view existing charts.")
    if st.button("📈 Show existing charts"):
        state.set("sweep_done", True)
        st.rerun()
else:
    st.info("Click **Run sweep** to generate results.")
