"""Availability analysis page — theoretical vs Monte Carlo system availability."""

import os
import sys

import streamlit as st
import yaml

# ── Path setup ─────────────────────────────────────────────────────────────────
_UI_DIR     = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_MODEL_ROOT = os.path.normpath(os.path.join(_UI_DIR, ".."))
if _UI_DIR     not in sys.path: sys.path.insert(0, _UI_DIR)
if _MODEL_ROOT not in sys.path: sys.path.insert(0, _MODEL_ROOT)

import state
import ui_theme
state.setup_path()

from engine.generate.generate import generate_simple_assembly
from analysis.use_cases.availability_analysis import theoretical, theoretical_integrated, experimental
from analysis.use_cases.availability_analysis.availability import _show_plots

# ── Page ───────────────────────────────────────────────────────────────────────
ui_theme.apply(
    title   = "Availability analysis",
    eyebrow = "analyse · availability",
)
st.caption("Compares theoretical (RBD) and experimental (Monte Carlo) system availability.")

# ── Config check ───────────────────────────────────────────────────────────────
with open(state.CONFIG_PATH) as f:
    cfg = yaml.safe_load(f)

fail_cfg = cfg.get("failures", {})
if not fail_cfg.get("enabled", False):
    st.error(
        "**Machine failures are disabled in `config.yaml`.** "
        "Go to Configure → Failures, enable them, and save before running this analysis."
    )
    st.stop()

# ── Parameters ─────────────────────────────────────────────────────────────────
st.markdown("## Monte Carlo parameters")
c1, c2, c3 = st.columns(3)
n_replications = c1.number_input("Replications",    value=200,    step=50,   min_value=10,
                                  help="More replications → tighter CI but slower (~1 min per 200).")
horizon_hours  = c2.number_input("Horizon (h)",     value=2000.0, step=500.0, min_value=100.0,
                                  help="Must be >> expected MTTF so many failure-repair cycles occur.")
warmup_hours   = c3.number_input("Warm-up (h)",     value=200.0,  step=50.0,  min_value=0.0,
                                  help="Discarded transient at the start of each replication.")
n_timepoints   = 5_000
seed           = 42

# ── Run button ─────────────────────────────────────────────────────────────────
st.divider()
if st.button("Run availability analysis", type="primary", use_container_width=True):
    with st.spinner("Generating factory…"):
        gen_result = generate_simple_assembly(state.CONFIG_PATH, export_csv=False)

    with st.spinner("Computing theoretical availability (midpoint)…"):
        theo_mid = theoretical.compute(gen_result, fail_cfg)

    with st.spinner("Computing theoretical availability (integrated)…"):
        theo_int = theoretical_integrated.compute(gen_result, fail_cfg)

    with st.spinner(f"Running Monte Carlo ({int(n_replications)} replications × {horizon_hours:.0f} h)…"):
        exp = experimental.run(
            gen_result,
            fail_cfg,
            n_replications = int(n_replications),
            horizon_hours  = float(horizon_hours),
            warmup_hours   = float(warmup_hours),
            n_timepoints   = n_timepoints,
            seed           = seed,
        )

    state.set("avail_done",   True)
    state.set("avail_theo_mid", theo_mid)
    state.set("avail_theo_int", theo_int)
    state.set("avail_exp",      exp)
    state.set("avail_gen",      gen_result)
    state.set("avail_n_reps",   int(n_replications))
    st.success("Analysis complete.")

# ── Results ────────────────────────────────────────────────────────────────────
if not state.get("avail_done"):
    st.info("Click Run availability analysis to start.")
    st.stop()

theo_mid   = state.get("avail_theo_mid")
theo_int   = state.get("avail_theo_int")
exp        = state.get("avail_exp")
gen_result = state.get("avail_gen")
n_reps     = state.get("avail_n_reps")

ci_lo, ci_hi = exp["A_sys_ci95"]

st.divider()
st.markdown("## Results")

# Summary table
m1, m2, m3 = st.columns(3)
m1.metric("Midpoint A_sys",     f"{theo_mid['A_sys']*100:.3f}%")
m2.metric("Integrated A_sys",   f"{theo_int['A_sys']*100:.3f}%")
m3.metric("Experimental A_sys", f"{exp['A_sys_mean']*100:.3f}%",
          delta=f"95% CI [{ci_lo*100:.2f}%, {ci_hi*100:.2f}%]")

# Weibull parameters
with st.expander("Weibull parameters used"):
    st.json({
        "beta_rep":    round(theo_mid["beta_rep"],   3),
        "lambda_rep":  round(theo_mid["lambda_rep"], 2),
        "MTTF_h":      round(theo_mid["MTTF_h"],     2),
        "MTTR_h":      round(theo_mid["MTTR_h"],     2),
        "A_ws_midpoint":   f"{theo_mid['A_ws']*100:.3f}%",
        "A_ws_integrated": f"{theo_int['A_ws']*100:.3f}%",
    })

# Bottlenecks table
st.markdown("## Component bottlenecks  ·  top 10 weakest")
import pandas as pd
bottleneck_rows = []
comp_n_producers = {}
for c in gen_result["configurations"]:
    comp_n_producers[c.component] = comp_n_producers.get(c.component, 0) + 1

for comp_id, A_c in theo_int["bottlenecks"][:10]:
    n_cap = comp_n_producers.get(comp_id, 0)
    bottleneck_rows.append({
        "Component":  comp_id,
        "A_comp (%)": round(A_c * 100, 4),
        "Producers":  n_cap,
        "Risk":       "SPOF" if n_cap == 1 else ("Limited" if n_cap == 2 else "OK"),
    })
st.dataframe(pd.DataFrame(bottleneck_rows), use_container_width=True, hide_index=True)

# ── Charts ─────────────────────────────────────────────────────────────────────
st.divider()
with st.spinner("Rendering charts…"):
    fig = _show_plots(theo_mid, theo_int, exp, gen_result, n_replications=n_reps)
st.plotly_chart(fig, use_container_width=True)
