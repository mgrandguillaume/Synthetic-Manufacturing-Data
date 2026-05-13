#!/usr/bin/env python3
# Visualisation for a single DTS simulation run.
#
# Reads the CSVs written by simulate.py and shows five charts:
#   1. Machine state %   — % of all workstations in starved / blocked / working
#                          at every tick (faint raw + bold rolling average)
#   2. Utilisation       — stacked bar of the 5 states per workstation
#   3. Throughput        — cumulative orders over time
#   4. Cost breakdown    — stacked bar per workstation
#   5. Buffer levels     — component stock over time
#
# Run standalone:  python visualize_sim.py
# Or call show()   from another script after simulation completes (run.py does this).
# Shared style:    theme.py (model root) — colours, palette, apply_axis_style()
# Dependencies:    pip install pandas plotly

import os
import sys

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Import shared theme from the model root directory.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import theme

_DEFAULT_SIM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim_output")

SMOOTH = 20   # rolling-average window in ticks


def show(sim_dir: str = _DEFAULT_SIM_DIR) -> None:
    """
    Build and display all five simulation charts.

    Parameters
    ----------
    sim_dir : path to the folder containing the five sim output CSVs.
              Defaults to simulate/sim_output/ next to this file.
    """
    states_df     = pd.read_csv(os.path.join(sim_dir, "states.csv"))
    util_df       = pd.read_csv(os.path.join(sim_dir, "utilization.csv"))
    throughput_df = pd.read_csv(os.path.join(sim_dir, "throughput.csv"))
    costs_df      = pd.read_csv(os.path.join(sim_dir, "costs.csv"))
    buffers_df    = pd.read_csv(os.path.join(sim_dir, "buffers.csv"))

    # ── Pre-compute: per-tick aggregate machine state % ───────────────────────
    total_ws = states_df["Workstation"].nunique()
    state_pct = (
        states_df.groupby(["Tick", "State"])
        .size()
        .unstack(fill_value=0)
        .div(total_ws)
        .mul(100)
    )

    # States shown in the CLEMATIS aggregate chart (Lopes et al. convention).
    CHART_STATES = [
        ("starved",    theme.STATE_COLORS["starved"],    "Starved"),
        ("blocked",    theme.STATE_COLORS["blocked"],    "Blocked"),
        ("processing", theme.STATE_COLORS["processing"], "Working"),
    ]

    # ── Build subplots ─────────────────────────────────────────────────────────
    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=[
            "Machine State % over Iterations", "",
            "Utilisation by State", "Throughput Over Time",
            "Cost Breakdown", "Component Buffer Levels",
        ],
        specs=[
            [{"colspan": 2}, None],
            [{}, {}],
            [{}, {}],
        ],
        vertical_spacing=0.13,
        horizontal_spacing=0.10,
    )

    # ── 1. Machine state % over iterations ────────────────────────────────────
    for state_key, color, label in CHART_STATES:
        if state_key not in state_pct.columns:
            continue

        raw      = state_pct[state_key]
        smoothed = raw.rolling(window=SMOOTH, min_periods=1).mean()

        fig.add_trace(go.Scatter(
            x=state_pct.index, y=raw,
            mode="lines",
            line=dict(color=color, width=0.75),
            opacity=0.20,
            showlegend=False,
            hoverinfo="skip",
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=state_pct.index, y=smoothed,
            mode="lines",
            name=label,
            line=dict(color=color, width=2.5),
            legendgroup=label,
            showlegend=True,
            hovertemplate=(
                f"<b>{label}</b><br>"
                "Tick: %{x}<br>%{y:.1f}% of machines<extra></extra>"
            ),
        ), row=1, col=1)

    # ── 2. Utilisation stacked bar (5 states) ─────────────────────────────────
    _COL_MAP = {
        "processing": "Busy",
        "setup":      "Setup",
        "blocked":    "Blocked",
        "starved":    "Starved",
        "idle":       "Idle",
    }
    for state in theme.STATES_ORDER:
        col_h = _COL_MAP[state]
        fig.add_trace(go.Bar(
            name=state.capitalize(),
            x=util_df["Workstation"],
            y=util_df[col_h],
            marker_color=theme.STATE_COLORS[state],
            marker_line_width=0,
            showlegend=False,
            hovertemplate=f"<b>{state.capitalize()}</b>: %{{y:.2f}} h<extra></extra>",
        ), row=2, col=1)

    # ── 3. Throughput ─────────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=[0.0] + throughput_df["Time"].tolist(),
        y=[0]   + throughput_df["Products"].tolist(),
        mode="lines+markers",
        line=dict(color=theme.STATE_COLORS["processing"], width=2, shape="hv"),
        marker=dict(size=6, color=theme.STATE_COLORS["processing"],
                    line=dict(color=theme.BG, width=1)),
        showlegend=False,
        hovertemplate="<b>%{y} orders</b> completed by %{x:.2f} h<extra></extra>",
    ), row=2, col=2)

    if not throughput_df.empty:
        mean_lead = throughput_df["LeadTime"].mean()
        fig.add_annotation(
            x=0.98, y=0.05, xref="x4 domain", yref="y4 domain",
            text=f"Mean lead time: {mean_lead:.2f} h",
            showarrow=False,
            font=dict(color=theme.SUBTEXT, size=10),
            align="right",
        )

    # ── 4. Cost breakdown ─────────────────────────────────────────────────────
    for col, color in theme.COST_COLORS.items():
        label = col.replace("Cost", "")
        fig.add_trace(go.Bar(
            name=label,
            x=costs_df["Workstation"],
            y=costs_df[col],
            marker_color=color,
            marker_line_width=0,
            showlegend=True,
            legendgroup=f"cost_{label}",
            hovertemplate=f"<b>{label}</b>: $%{{y:.0f}}<extra></extra>",
        ), row=3, col=1)

    # ── 5. Buffer levels ──────────────────────────────────────────────────────
    if not buffers_df.empty:
        for i, comp in enumerate(sorted(buffers_df["Component"].unique())):
            sub = buffers_df[buffers_df["Component"] == comp]
            fig.add_trace(go.Scatter(
                x=sub["Time"],
                y=sub["Stock"],
                mode="lines",
                name=comp,
                line=dict(color=theme.palette(i), width=1.5),
                showlegend=True,
                legendgroup=f"buf_{comp}",
                hovertemplate=(
                    f"<b>{comp}</b><br>"
                    "Time: %{x:.2f} h<br>Stock: %{y}<extra></extra>"
                ),
            ), row=3, col=2)
        fig.add_hline(
            y=20, row=3, col=2,
            line=dict(color=theme.STATE_COLORS["blocked"], dash="dot", width=1),
            annotation_text="capacity",
            annotation_font_color=theme.SUBTEXT,
            annotation_font_size=10,
        )
    else:
        fig.add_annotation(
            x=0.5, y=0.5, xref="x6 domain", yref="y6 domain",
            text="Buffer log disabled (log_buffers=False)",
            showarrow=False, font=dict(color=theme.SUBTEXT, size=11),
        )

    # ── Global styling ────────────────────────────────────────────────────────
    fig.update_layout(
        barmode="stack",
        paper_bgcolor=theme.BG,
        plot_bgcolor=theme.BG,
        font=dict(color=theme.TEXT, family="Inter, system-ui, sans-serif", size=12),
        title=dict(
            text="Assembly Factory — Discrete-Time Simulation",
            font=dict(size=20, color=theme.TEXT),
            x=0.02, y=0.99,
        ),
        height=1000,
        legend=dict(
            bgcolor=theme.SURFACE, bordercolor=theme.BORDER, borderwidth=1,
            font=dict(color=theme.SUBTEXT, size=11),
            tracegroupgap=4,
            x=1.01, y=1,
        ),
        margin=dict(l=60, r=160, t=60, b=40),
    )

    for ann in fig.layout.annotations:
        ann.font.color = theme.SUBTEXT
        ann.font.size  = 12

    theme.apply_axis_style(fig)

    fig.update_xaxes(title_text="Iteration (tick)", title_font=dict(color=theme.SUBTEXT), row=1, col=1)
    fig.update_xaxes(title_text="Workstation",      title_font=dict(color=theme.SUBTEXT), row=2, col=1)
    fig.update_xaxes(title_text="Time (h)",         title_font=dict(color=theme.SUBTEXT), row=2, col=2)
    fig.update_xaxes(title_text="Workstation",      title_font=dict(color=theme.SUBTEXT), row=3, col=1)
    fig.update_xaxes(title_text="Time (h)",         title_font=dict(color=theme.SUBTEXT), row=3, col=2)

    fig.update_yaxes(title_text="% of machines", title_font=dict(color=theme.SUBTEXT), row=1, col=1)
    fig.update_yaxes(title_text="Hours",         title_font=dict(color=theme.SUBTEXT), row=2, col=1)
    fig.update_yaxes(title_text="Orders",        title_font=dict(color=theme.SUBTEXT), row=2, col=2)
    fig.update_yaxes(title_text="Cost ($)",      title_font=dict(color=theme.SUBTEXT), row=3, col=1)
    fig.update_yaxes(title_text="Units in stock",title_font=dict(color=theme.SUBTEXT), row=3, col=2)

    fig.show()


if __name__ == "__main__":
    show()
