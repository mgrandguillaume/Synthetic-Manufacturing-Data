#!/usr/bin/env python3
# Validation diagnostic charts for the Assembly Factory model.
#
# Runs three targeted simulations, saves their output to CSV files in
# validation_output/, then renders the results as a single figure:
#
#   1. Cumulative orders completed over time  (step chart)
#   2. Buffer levels over time per component  (line chart)
#   3. Observed vs. theoretical availability  (bar + reference line)
#
# Run standalone:  python visualize_validation.py
#   → re-generates data and shows charts in one go.
# Or call generate_data() + show() separately from validate.py / run.py.
# Shared style:    theme.py (model root) — colours, palette, apply_axis_style()
# Dependencies:    pip install pandas plotly

from __future__ import annotations

import os
import sys

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Path setup ─────────────────────────────────────────────────────────────────
_MODEL_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, _MODEL_ROOT)

from generate.generate import generate_from_params   # noqa: E402
from simulate.simulate import simulate               # noqa: E402
import theme                                         # noqa: E402

_DEFAULT_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "validation_output"
)

# ── Simulation parameters for the diagnostic charts ───────────────────────────
_GEN = {
    "n_products":              1,
    "depth":                   2,
    "workstations_count":      4,
    "sharing_ratio":           0.0,
    "branching":               [2, 2],
    "quantity":                [1, 1],
    "producers_per_component": [2, 2],
    "processing_time":         [0.2, 0.2],
    "setup_time":              [0.5, 0.5],
    "setup_cost":              [100, 100],
    "operating_cost":          [5,   5  ],
    "flow_capacity":           [100, 100],
    "transport_cost":          [1.0, 1.0],
    "seed":                    42,
}

_BUFFER_CAPACITY = 20
_WEIBULL_LAMBDA  = 20.0   # hours  (mean TTF for β=1)
_MTTR            = 4.0    # hours  (mean repair duration)
_AVAIL_THEORY    = _WEIBULL_LAMBDA / (_WEIBULL_LAMBDA + _MTTR)


# ── Data generation ────────────────────────────────────────────────────────────

def _gen_orders_data() -> pd.DataFrame:
    gen    = generate_from_params(_GEN)
    result = simulate(gen, n_orders=15, tick_duration=0.05,
                      buffer_capacity=_BUFFER_CAPACITY, order_interarrival=5,
                      n_ticks=6000, log_buffers=False, failures_enabled=False, seed=42)
    tp = result["throughput"]
    if tp.empty:
        return pd.DataFrame(columns=["Time", "CumulativeOrders"])
    times  = [0.0] + tp["Time"].tolist()
    counts = list(range(len(times)))
    return pd.DataFrame({"Time": times, "CumulativeOrders": counts})


def _gen_buffer_data() -> pd.DataFrame:
    gen    = generate_from_params(_GEN)
    result = simulate(gen, n_orders=10, tick_duration=0.05,
                      buffer_capacity=_BUFFER_CAPACITY, order_interarrival=5,
                      n_ticks=4000, log_buffers=True, failures_enabled=False, seed=42)
    buf = result["buffers"]
    if buf.empty:
        return pd.DataFrame(columns=["Time", "Component", "Stock", "BufferCapacity"])
    out = buf[["Time", "Component", "Stock"]].copy()
    out["BufferCapacity"] = _BUFFER_CAPACITY
    return out


def _gen_availability_data() -> pd.DataFrame:
    gen    = generate_from_params(_GEN)
    result = simulate(gen, n_orders=20, tick_duration=0.05,
                      buffer_capacity=50, order_interarrival=5, n_ticks=10_000,
                      log_buffers=False, failures_enabled=True,
                      weibull_beta_range=[1.0, 1.0],
                      weibull_lambda_range=[_WEIBULL_LAMBDA, _WEIBULL_LAMBDA],
                      mttr_range=[_MTTR, _MTTR], repair_cost_range=[0.0, 0.0], seed=42)
    util = result["utilization"]
    if "FailedPct" not in util.columns:
        return pd.DataFrame(
            columns=["Workstation", "ObservedAvailability", "TheoreticalAvailability"])
    return pd.DataFrame({
        "Workstation":             util["Workstation"].astype(str),
        "ObservedAvailability":    1.0 - util["FailedPct"] / 100.0,
        "TheoreticalAvailability": _AVAIL_THEORY,
    })


def generate_data(output_dir: str = _DEFAULT_OUTPUT_DIR) -> None:
    """
    Run the three diagnostic simulations and save results as CSVs.

    Files written to output_dir
    ---------------------------
    val_orders.csv       — cumulative orders over time
    val_buffers.csv      — buffer stock per component over time
    val_availability.csv — observed vs. theoretical workstation availability
    """
    os.makedirs(output_dir, exist_ok=True)

    print("  [viz] Generating cumulative-orders data…")
    _gen_orders_data().to_csv(os.path.join(output_dir, "val_orders.csv"), index=False)

    print("  [viz] Generating buffer-level data…")
    _gen_buffer_data().to_csv(os.path.join(output_dir, "val_buffers.csv"), index=False)

    print("  [viz] Generating availability data…")
    _gen_availability_data().to_csv(
        os.path.join(output_dir, "val_availability.csv"), index=False)

    print(f"  [viz] Chart data saved to {output_dir}")


# ── Legend helper ─────────────────────────────────────────────────────────────

def _legend_style(y: float) -> dict:
    """Return a right-aligned legend positioned at paper y for one subplot."""
    return dict(
        x=0.99, y=y, xanchor="right", yanchor="top",
        bgcolor=theme.SURFACE, bordercolor=theme.BORDER, borderwidth=1,
        font=dict(color=theme.SUBTEXT, size=10),
    )


# ── Chart rendering ────────────────────────────────────────────────────────────

def show(output_dir: str = _DEFAULT_OUTPUT_DIR) -> None:
    """
    Build and display all three validation charts in one figure.

    Reads the CSVs previously written by generate_data().  Run
    generate_data() first if the CSVs do not exist yet.
    """
    orders_path       = os.path.join(output_dir, "val_orders.csv")
    buffers_path      = os.path.join(output_dir, "val_buffers.csv")
    availability_path = os.path.join(output_dir, "val_availability.csv")

    for p in (orders_path, buffers_path, availability_path):
        if not os.path.exists(p):
            raise FileNotFoundError(
                f"{os.path.basename(p)} not found in {output_dir}.\n"
                "Run validation first:  python run.py --validate"
            )

    orders_df       = pd.read_csv(orders_path)
    buffers_df      = pd.read_csv(buffers_path)
    availability_df = pd.read_csv(availability_path)

    # 3 rows, vertical_spacing=0.10
    # subplot height = (1 - 2×0.10) / 3 ≈ 0.267
    # row tops in paper coords: row1≈1.00, row2≈0.63, row3≈0.27
    fig = make_subplots(
        rows=3, cols=1,
        subplot_titles=[
            "Cumulative Orders Completed over Time",
            "Buffer Levels over Time",
            f"Observed vs. Theoretical Availability  (β=1, theory={_AVAIL_THEORY:.3f})",
        ],
        vertical_spacing=0.10,
    )

    # ── Row 1: Cumulative orders ───────────────────────────────────────────────
    if not orders_df.empty:
        fig.add_trace(go.Scatter(
            x=orders_df["Time"], y=orders_df["CumulativeOrders"],
            mode="lines", line=dict(shape="hv", color=theme.palette(0), width=2),
            name="Orders completed", legend="legend",
            hovertemplate="Time: %{x:.2f} h<br>Completed: %{y}<extra></extra>",
        ), row=1, col=1)

    # ── Row 2: Buffer levels ───────────────────────────────────────────────────
    if not buffers_df.empty:
        buffer_capacity = int(buffers_df["BufferCapacity"].iloc[0])
        max_time        = float(buffers_df["Time"].max())

        for i, comp in enumerate(buffers_df["Component"].unique()):
            sub = buffers_df[buffers_df["Component"] == comp].sort_values("Time")
            fig.add_trace(go.Scatter(
                x=sub["Time"], y=sub["Stock"], mode="lines",
                name=str(comp), legend="legend2",
                line=dict(color=theme.palette(i), width=1),
                hovertemplate=f"{comp}<br>Time: %{{x:.2f}} h<br>Stock: %{{y}}<extra></extra>",
            ), row=2, col=1)

        fig.add_trace(go.Scatter(
            x=[0.0, max_time], y=[buffer_capacity, buffer_capacity],
            mode="lines", name=f"Capacity ({buffer_capacity})", legend="legend2",
            line=dict(color=theme.STATE_COLORS["blocked"], dash="dash", width=1),
            hovertemplate=f"Capacity: {buffer_capacity}<extra></extra>",
        ), row=2, col=1)

    # ── Row 3: Availability ────────────────────────────────────────────────────
    if not availability_df.empty:
        a_theory  = float(availability_df["TheoreticalAvailability"].iloc[0])
        ws_labels = availability_df["Workstation"].tolist()
        a_obs     = availability_df["ObservedAvailability"].tolist()

        fig.add_trace(go.Bar(
            x=ws_labels, y=a_obs, name="Observed availability", legend="legend3",
            marker=dict(color=theme.palette(0), opacity=0.85),
            hovertemplate="%{x}<br>Observed: %{y:.3f}<extra></extra>",
        ), row=3, col=1)

        fig.add_trace(go.Scatter(
            x=ws_labels, y=[a_theory] * len(ws_labels),
            mode="lines", name=f"Theory  λ/(λ+MTTR) = {a_theory:.3f}", legend="legend3",
            line=dict(color=theme.STATE_COLORS["failed"], dash="dash", width=2),
            hovertemplate=f"Theory: {a_theory:.3f}<extra></extra>",
        ), row=3, col=1)

    # ── Axis labels ────────────────────────────────────────────────────────────
    _sf = dict(color=theme.SUBTEXT)
    fig.update_xaxes(title_text="Simulation time (h)", title_font=_sf, row=1, col=1)
    fig.update_xaxes(title_text="Simulation time (h)", title_font=_sf, row=2, col=1)
    fig.update_xaxes(title_text="Workstation",         title_font=_sf, row=3, col=1)
    fig.update_yaxes(title_text="Orders completed",    title_font=_sf, row=1, col=1)
    fig.update_yaxes(title_text="Stock (units)",       title_font=_sf, row=2, col=1)
    fig.update_yaxes(title_text="Availability",        title_font=_sf,
                     range=[0.0, 1.0],                                 row=3, col=1)

    # ── Global styling ─────────────────────────────────────────────────────────
    fig.update_layout(
        title=dict(text="Validation Diagnostics — Assembly Factory",
                   font=dict(size=20, color=theme.TEXT), x=0.02, y=0.99),
        paper_bgcolor = theme.BG,
        plot_bgcolor  = theme.BG,
        font          = dict(color=theme.TEXT, family="Inter, system-ui, sans-serif", size=12),
        height        = 1200,
        barmode       = "group",
        margin        = dict(l=60, r=40, t=100, b=40),
        legend  = _legend_style(0.97),   # row 1
        legend2 = _legend_style(0.63),   # row 2
        legend3 = _legend_style(0.27),   # row 3
    )

    for ann in fig.layout.annotations:
        ann.font.color = theme.SUBTEXT
        ann.font.size  = 12

    theme.apply_axis_style(fig)
    fig.show()


# ── Standalone entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    generate_data()
    show()
