"""Simulate page — run a DTS simulation on the generated factory."""

import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml

# ── Path setup ─────────────────────────────────────────────────────────────────
_UI_DIR     = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_MODEL_ROOT = os.path.normpath(os.path.join(_UI_DIR, ".."))
if _UI_DIR     not in sys.path: sys.path.insert(0, _UI_DIR)
if _MODEL_ROOT not in sys.path: sys.path.insert(0, _MODEL_ROOT)

import state
state.setup_path()

from engine.simulate.simulate import simulate
from shared_utils import theme

# ── Page ───────────────────────────────────────────────────────────────────────
st.title("▶️ Simulate")

# ── Prerequisite check ─────────────────────────────────────────────────────────
if state.get("gen_result") is None:
    st.warning("Run **🏗️ Generate** first to create a factory.")
    st.stop()

# ── Load config defaults ───────────────────────────────────────────────────────
with open(state.CONFIG_PATH) as f:
    cfg = yaml.safe_load(f)
sim_cfg  = cfg.get("simulation", {})
fail_cfg = cfg.get("failures",   {})

# ── Simulation parameters ──────────────────────────────────────────────────────
st.subheader("Parameters")
c1, c2, c3 = st.columns(3)
n_orders          = c1.number_input("Orders",               value=int(sim_cfg.get("n_orders",           10)),   step=1,   min_value=1)
n_ticks           = c2.number_input("Max ticks",            value=int(sim_cfg.get("n_ticks",           3000)),  step=100, min_value=100)
tick_duration     = c3.number_input("Tick duration (h)",    value=float(sim_cfg.get("tick_duration",   0.05)),  step=0.01,format="%.4f", min_value=0.001)
buffer_capacity   = c1.number_input("Buffer capacity",      value=int(sim_cfg.get("buffer_capacity",    20)),   step=1,   min_value=1)
order_interarrival= c2.number_input("Interarrival (ticks)", value=int(sim_cfg.get("order_interarrival", 10)),   step=1,   min_value=1)
log_buffers       = c3.toggle("Log buffer levels", value=True)

st.divider()
failures_enabled = st.toggle("Enable machine failures", value=bool(fail_cfg.get("enabled", False)))

if failures_enabled:
    fc1, fc2 = st.columns(2)
    beta_lo  = fc1.number_input("Weibull β min", value=float(fail_cfg.get("weibull_beta",   [1.5, 3.0])[0]), step=0.1)
    beta_hi  = fc2.number_input("Weibull β max", value=float(fail_cfg.get("weibull_beta",   [1.5, 3.0])[1]), step=0.1)
    lam_lo   = fc1.number_input("Weibull λ min (h)", value=float(fail_cfg.get("weibull_lambda", [20, 50])[0]), step=1.0)
    lam_hi   = fc2.number_input("Weibull λ max (h)", value=float(fail_cfg.get("weibull_lambda", [20, 50])[1]), step=1.0)
    mttr_lo  = fc1.number_input("MTTR min (h)",  value=float(fail_cfg.get("mttr",           [0.5, 4.0])[0]), step=0.1)
    mttr_hi  = fc2.number_input("MTTR max (h)",  value=float(fail_cfg.get("mttr",           [0.5, 4.0])[1]), step=0.1)
    rc_lo    = fc1.number_input("Repair cost min", value=float(fail_cfg.get("repair_cost",  [100, 500])[0]), step=10.0)
    rc_hi    = fc2.number_input("Repair cost max", value=float(fail_cfg.get("repair_cost",  [100, 500])[1]), step=10.0)
else:
    beta_lo = beta_hi = 2.0
    lam_lo  = lam_hi  = 100.0
    mttr_lo = mttr_hi = 1.0
    rc_lo   = rc_hi   = 0.0

seed_val = int(cfg.get("metadata", {}).get("seed") or 0)

# ── Run button ─────────────────────────────────────────────────────────────────
st.divider()
if st.button("▶️ Run simulation", type="primary", use_container_width=True):
    with st.spinner("Simulating…"):
        results = simulate(
            state.get("gen_result"),
            n_orders             = int(n_orders),
            tick_duration        = float(tick_duration),
            buffer_capacity      = int(buffer_capacity),
            order_interarrival   = int(order_interarrival),
            n_ticks              = int(n_ticks),
            log_buffers          = bool(log_buffers),
            failures_enabled     = bool(failures_enabled),
            weibull_beta_range   = [float(beta_lo), float(beta_hi)],
            weibull_lambda_range = [float(lam_lo),  float(lam_hi)],
            mttr_range           = [float(mttr_lo), float(mttr_hi)],
            repair_cost_range    = [float(rc_lo),   float(rc_hi)],
            seed                 = int(seed_val) if seed_val != 0 else None,
        )
    state.set("sim_result", results)
    st.success("Simulation complete.")

# ── Display results ────────────────────────────────────────────────────────────
results = state.get("sim_result")
if results is None:
    st.info("Click **Run simulation** to start.")
    st.stop()

st.divider()
tp = results["throughput"]
util = results["utilization"]

# Summary metrics
m1, m2, m3, m4 = st.columns(4)
m1.metric("Orders completed", len(tp))
m2.metric("Total time (h)",   f"{tp['Time'].max():.2f}"  if not tp.empty else "—")
m3.metric("Mean lead time (h)",f"{tp['LeadTime'].mean():.2f}" if not tp.empty else "—")
m4.metric("Mean busy %",      f"{util['BusyPct'].mean():.1f}%")

tab_util, tab_tp, tab_costs, tab_buf = st.tabs(
    ["Utilization", "Throughput", "Costs", "Buffers"])

# ── Utilization chart ──────────────────────────────────────────────────────────
with tab_util:
    STATE_COLS  = ["BusyPct", "SetupPct", "BlockedPct", "StarvedPct", "IdlePct", "FailedPct"]
    STATE_NAMES = ["Processing", "Setup", "Blocked", "Starved", "Idle", "Failed"]
    STATE_KEYS  = ["processing", "setup", "blocked", "starved", "idle", "failed"]

    fig_u = go.Figure()
    for col, name, key in zip(STATE_COLS, STATE_NAMES, STATE_KEYS):
        fig_u.add_trace(go.Bar(
            x=util["Workstation"], y=util[col], name=name,
            marker_color=theme.STATE_COLORS.get(key, theme.palette(STATE_KEYS.index(key))),
        ))
    fig_u.update_layout(
        barmode="stack", height=420,
        paper_bgcolor=theme.BG, plot_bgcolor=theme.BG,
        font=dict(color=theme.TEXT, family="Inter, system-ui, sans-serif"),
        legend=dict(bgcolor=theme.SURFACE, bordercolor=theme.BORDER, borderwidth=1,
                    font=dict(color=theme.SUBTEXT)),
        xaxis_title="Workstation", yaxis_title="Time (%)",
        margin=dict(l=50, r=20, t=30, b=40),
    )
    theme.apply_axis_style(fig_u)
    st.plotly_chart(fig_u, use_container_width=True)

# ── Throughput chart ───────────────────────────────────────────────────────────
with tab_tp:
    if tp.empty:
        st.warning("No orders completed.")
    else:
        times  = [0.0] + tp["Time"].tolist()
        counts = list(range(len(times)))
        fig_tp = go.Figure(go.Scatter(
            x=times, y=counts, mode="lines",
            line=dict(shape="hv", color=theme.palette(0), width=2),
            hovertemplate="Time: %{x:.2f} h<br>Orders: %{y}<extra></extra>",
        ))
        fig_tp.update_layout(
            height=350, paper_bgcolor=theme.BG, plot_bgcolor=theme.BG,
            font=dict(color=theme.TEXT, family="Inter, system-ui, sans-serif"),
            xaxis_title="Simulation time (h)", yaxis_title="Cumulative orders",
            margin=dict(l=50, r=20, t=30, b=40),
        )
        theme.apply_axis_style(fig_tp)
        st.plotly_chart(fig_tp, use_container_width=True)
        st.dataframe(tp, use_container_width=True)

# ── Costs table ────────────────────────────────────────────────────────────────
with tab_costs:
    costs = results["costs"].copy()
    costs["TotalCost"] = (costs["SetupCost"] + costs["OperatingCost"]
                          + costs["TransportCost"] + costs["RepairCost"])
    cost_cols = ["SetupCost", "OperatingCost", "TransportCost", "RepairCost"]
    fig_c = go.Figure()
    for i, col in enumerate(cost_cols):
        fig_c.add_trace(go.Bar(
            x=costs["Workstation"], y=costs[col],
            name=col.replace("Cost", ""), marker_color=theme.palette(i),
        ))
    fig_c.update_layout(
        barmode="stack", height=380,
        paper_bgcolor=theme.BG, plot_bgcolor=theme.BG,
        font=dict(color=theme.TEXT, family="Inter, system-ui, sans-serif"),
        xaxis_title="Workstation", yaxis_title="Cost",
        legend=dict(bgcolor=theme.SURFACE, bordercolor=theme.BORDER, borderwidth=1,
                    font=dict(color=theme.SUBTEXT)),
        margin=dict(l=50, r=20, t=30, b=40),
    )
    theme.apply_axis_style(fig_c)
    st.plotly_chart(fig_c, use_container_width=True)
    st.dataframe(costs.style.format({c: "{:.2f}" for c in cost_cols + ["TotalCost"]}),
                 use_container_width=True)

# ── Buffers chart ──────────────────────────────────────────────────────────────
with tab_buf:
    buf_df = results["buffers"]
    if buf_df.empty:
        st.info("Buffer logging was disabled for this run. Re-run with **Log buffer levels** enabled.")
    else:
        fig_b = go.Figure()
        for i, comp in enumerate(buf_df["Component"].unique()):
            sub = buf_df[buf_df["Component"] == comp].sort_values("Time")
            fig_b.add_trace(go.Scatter(
                x=sub["Time"], y=sub["Stock"], mode="lines",
                name=str(comp), line=dict(color=theme.palette(i), width=1),
                hovertemplate=f"{comp}<br>Time: %{{x:.2f}} h<br>Stock: %{{y}}<extra></extra>",
            ))
        fig_b.update_layout(
            height=420, paper_bgcolor=theme.BG, plot_bgcolor=theme.BG,
            font=dict(color=theme.TEXT, family="Inter, system-ui, sans-serif"),
            xaxis_title="Simulation time (h)", yaxis_title="Stock (units)",
            legend=dict(bgcolor=theme.SURFACE, bordercolor=theme.BORDER, borderwidth=1,
                        font=dict(color=theme.SUBTEXT, size=9)),
            margin=dict(l=50, r=20, t=30, b=40),
        )
        theme.apply_axis_style(fig_b)
        st.plotly_chart(fig_b, use_container_width=True)
