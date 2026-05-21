#!/usr/bin/env python3
"""
Section 3 — The Alpha model closes both gaps.

Reads existing sweep output from the Alpha model and produces five charts:

  Row 1  (2 columns) : ① Working % vs α
                     | ② Starved % and Blocked % vs α
                       (both depth = 3, averaged over sharing ratio and ticks)
  Row 2  (2 columns) : ③ Makespan vs α  (one line per BOM depth)
                     | ④ Cost breakdown vs α  (depth = 3, stacked)
  Row 3  (full width): ⑤ Lead time distribution vs α  (depth = 2, box plots)

All charts are annotated with dashed lines marking where Rafael's two discrete
topology options (parallel ≈ α→0, linear = α=1) sit on the continuous axis.

Run
---
  uv run src/rafael_vs_lopes/visualize_section3_alpha.py

Dependencies
------------
  pip install pandas plotly
"""

import os

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Paths ──────────────────────────────────────────────────────────────────────

_HERE      = os.path.dirname(os.path.abspath(__file__))
_ALPHA_DIR = os.path.normpath(
    os.path.join(_HERE, "..", "models", "2026-04-29_alpha_model", "sweep", "sweep_output")
)

# ── Theme ──────────────────────────────────────────────────────────────────────

_BG      = "#0d1117"
_SURFACE = "#161b22"
_BORDER  = "#21262d"
_TEXT    = "#e6edf3"
_SUBTEXT = "#8b949e"

_C_WORKING = "#58a6ff"
_C_STARVED = "#a371f7"
_C_BLOCKED = "#f78166"
_C_RAFAEL  = "#3fb950"

_DEPTH_COLORS = {1: "#58a6ff", 2: "#3fb950", 3: "#d29922", 4: "#f78166", 5: "#a371f7"}

_AXIS_STYLE = dict(
    gridcolor=_BORDER,
    zerolinecolor=_BORDER,
    tickcolor=_SUBTEXT,
    tickfont=dict(color=_SUBTEXT, size=11),
    linecolor=_BORDER,
    title_font=dict(color=_SUBTEXT, size=11),
)

_RAFAEL_LINE = dict(line_dash="dot", line_color=_C_RAFAEL, line_width=1.5)


def _rafael_vlines(fig, row, col):
    """Add dashed vertical lines marking Rafael's two topology positions."""
    for x in [0.05, 1.0]:
        fig.add_vline(x=x, row=row, col=col, **_RAFAEL_LINE)


# ── Data loading ───────────────────────────────────────────────────────────────

def _load():
    ss  = pd.read_csv(os.path.join(_ALPHA_DIR, "state_summary.csv"))
    tp  = pd.read_csv(os.path.join(_ALPHA_DIR, "throughput.csv"))
    cst = pd.read_csv(os.path.join(_ALPHA_DIR, "costs.csv"))
    return ss, tp, cst


# ── Chart builders ─────────────────────────────────────────────────────────────

def _chart_working(fig, ss, row, col):
    """Working % vs α (depth=3, averaged over sharing_ratio and ticks)."""
    per_run = (
        ss.groupby(["RunID", "alpha", "depth", "sharing_ratio"])["WorkingPct"]
        .mean()
        .reset_index()
    )
    d3 = (
        per_run[per_run["depth"] == 3]
        .groupby("alpha")["WorkingPct"]
        .mean()
        .reset_index()
        .sort_values("alpha")
    )

    fig.add_trace(go.Scatter(
        x=d3["alpha"], y=d3["WorkingPct"],
        mode="lines+markers",
        name="Working",
        line=dict(color=_C_WORKING, width=2.5),
        marker=dict(color=_C_WORKING, size=6),
        legendgroup="working",
        hovertemplate="α = %{x:.3f}<br>Working = %{y:.1f}%<extra></extra>",
    ), row=row, col=col)

    _rafael_vlines(fig, row, col)
    _annotate_rafael(fig, row, col, y_frac=0.92)


def _chart_starved_blocked(fig, ss, row, col):
    """Starved % and Blocked % vs α on the same axes (depth=3)."""
    per_run = (
        ss.groupby(["RunID", "alpha", "depth", "sharing_ratio"])
        [["StarvedPct", "BlockedPct"]]
        .mean()
        .reset_index()
    )
    d3 = (
        per_run[per_run["depth"] == 3]
        .groupby("alpha")[["StarvedPct", "BlockedPct"]]
        .mean()
        .reset_index()
        .sort_values("alpha")
    )

    for col_name, color, label in [
        ("StarvedPct", _C_STARVED, "Starved"),
        ("BlockedPct", _C_BLOCKED, "Blocked"),
    ]:
        fig.add_trace(go.Scatter(
            x=d3["alpha"], y=d3[col_name],
            mode="lines+markers",
            name=label,
            line=dict(color=color, width=2.5),
            marker=dict(color=color, size=6),
            legendgroup=f"sb_{label}",
            hovertemplate=f"<b>{label}</b><br>α = %{{x:.3f}}<br>%{{y:.1f}}%<extra></extra>",
        ), row=row, col=col)

    _rafael_vlines(fig, row, col)
    _annotate_rafael(fig, row, col, y_frac=0.92)


def _chart_makespan(fig, tp, row, col):
    """Makespan vs α, one line per BOM depth."""
    makespan = (
        tp.groupby(["RunID", "alpha", "depth", "sharing_ratio"])["Time"]
        .max()
        .reset_index()
    )
    ms = (
        makespan.groupby(["alpha", "depth"])["Time"]
        .mean()
        .reset_index()
        .sort_values(["depth", "alpha"])
    )

    for depth in sorted(ms["depth"].unique()):
        sub   = ms[ms["depth"] == depth]
        color = _DEPTH_COLORS.get(int(depth), _SUBTEXT)
        fig.add_trace(go.Scatter(
            x=sub["alpha"], y=sub["Time"],
            mode="lines+markers",
            name=f"depth {int(depth)}",
            line=dict(color=color, width=2.2),
            marker=dict(color=color, size=5),
            legendgroup=f"depth_{depth}",
            legendgrouptitle_text="BOM depth" if depth == ms["depth"].min() else "",
            hovertemplate=(
                f"depth {int(depth)}<br>α = %{{x:.3f}}<br>"
                "makespan = %{y:.1f} h<extra></extra>"
            ),
        ), row=row, col=col)

    _rafael_vlines(fig, row, col)
    _annotate_rafael(fig, row, col, y_frac=0.92)


def _chart_cost(fig, cst, row, col):
    """Stacked setup / operating / transport cost vs α (depth=3)."""
    cst3 = cst[cst["depth"] == 3].copy()

    for cost_col, color, label in [
        ("SetupCost",     "#d29922", "Setup"),
        ("OperatingCost", _C_WORKING, "Operating"),
        ("TransportCost", _C_RAFAEL,  "Transport"),
    ]:
        per_run = cst3.groupby(["RunID", "alpha"])[cost_col].sum().reset_index()
        avg     = (
            per_run.groupby("alpha")[cost_col]
            .mean()
            .reset_index()
            .sort_values("alpha")
        )
        fig.add_trace(go.Scatter(
            x=avg["alpha"], y=avg[cost_col],
            mode="lines",
            name=f"{label} cost",
            fill="tonexty" if label != "Setup" else "tozeroy",
            line=dict(color=color, width=1.5),
            stackgroup="cost",
            legendgroup=f"cost_{label}",
            legendgrouptitle_text="Cost type" if label == "Setup" else "",
            hovertemplate=(
                f"<b>{label}</b><br>α = %{{x:.3f}}<br>%{{y:.0f}}<extra></extra>"
            ),
        ), row=row, col=col)

    _rafael_vlines(fig, row, col)
    _annotate_rafael(fig, row, col, y_frac=0.92)


def _chart_leadtime(fig, tp, row, col):
    """
    Lead time distribution vs α as box plots (depth=2).
    Shows how spread and median shift as the factory moves from parallel to serial.
    """
    lt = tp[tp["depth"] == 2][["alpha", "LeadTime"]].copy()

    # Plot one box per unique alpha value
    for alpha_val in sorted(lt["alpha"].unique()):
        vals = lt[lt["alpha"] == alpha_val]["LeadTime"].values
        fig.add_trace(go.Box(
            x=[round(float(alpha_val), 4)] * len(vals),
            y=vals,
            name=f"α={alpha_val:.2f}",
            marker_color=_C_WORKING,
            line=dict(color=_C_WORKING),
            fillcolor="rgba(88,166,255,0.25)",
            showlegend=False,
            boxmean=True,
            hovertemplate=(
                "α = %{x:.3f}<br>"
                "Lead time: %{y:.1f} h<extra></extra>"
            ),
        ), row=row, col=col)

    _rafael_vlines(fig, row, col)
    _annotate_rafael(fig, row, col, y_frac=0.94)


def _annotate_rafael(fig, row, col, y_frac=0.9):
    """Add small text labels next to the Rafael vlines."""
    # These use paper-space annotations placed inside the subplot.
    # We skip per-call axis ref calculation and rely on the vlines being visible.
    pass   # vlines already added — labels added globally after layout is set


# ── Entry point ────────────────────────────────────────────────────────────────

def show() -> None:
    ss, tp, cst = _load()

    fig = make_subplots(
        rows=3, cols=2,
        specs=[
            [{}, {}],
            [{}, {}],
            [{"colspan": 2}, None],
        ],
        subplot_titles=[
            "① Working % vs α  (depth = 3)",
            "② Starved % and Blocked % vs α  (depth = 3)",
            "③ Makespan vs α  (by BOM depth)",
            "④ Cost breakdown vs α  (depth = 3)",
            "⑤ Lead time distribution vs α  (depth = 2)",
        ],
        vertical_spacing=0.10,
        horizontal_spacing=0.10,
        row_heights=[0.28, 0.28, 0.44],
    )

    _chart_working(fig, ss, row=1, col=1)
    _chart_starved_blocked(fig, ss, row=1, col=2)
    _chart_makespan(fig, tp, row=2, col=1)
    _chart_cost(fig, cst, row=2, col=2)
    _chart_leadtime(fig, tp, row=3, col=1)

    # ── Layout ────────────────────────────────────────────────────────────────
    fig.update_layout(
        paper_bgcolor=_BG,
        plot_bgcolor=_BG,
        font=dict(color=_TEXT, family="Inter, system-ui, sans-serif", size=12),
        height=1300,
        title=dict(
            text="Section 3 — Alpha model: closing the gap between Lopes and Rafael",
            font=dict(size=18, color=_TEXT),
            x=0.02, y=0.99,
        ),
        legend=dict(
            bgcolor=_SURFACE, bordercolor=_BORDER, borderwidth=1,
            font=dict(color=_SUBTEXT, size=11),
            tracegroupgap=12, x=1.02, y=0.98,
        ),
        margin=dict(l=65, r=200, t=72, b=60),
        boxmode="overlay",
    )

    fig.update_xaxes(**_AXIS_STYLE)
    fig.update_yaxes(**_AXIS_STYLE)

    # Per-axis labels
    fig.update_xaxes(title_text="α = depth / workstations_count", row=1, col=1)
    fig.update_yaxes(title_text="% of machines", row=1, col=1)
    fig.update_xaxes(title_text="α = depth / workstations_count", row=1, col=2)
    fig.update_yaxes(title_text="% of machines", row=1, col=2)
    fig.update_xaxes(title_text="α = depth / workstations_count", row=2, col=1)
    fig.update_yaxes(title_text="Makespan (h)", row=2, col=1)
    fig.update_xaxes(title_text="α = depth / workstations_count", row=2, col=2)
    fig.update_yaxes(title_text="Total cost", row=2, col=2)
    fig.update_xaxes(title_text="α = depth / workstations_count", row=3, col=1)
    fig.update_yaxes(title_text="Lead time (h)", row=3, col=1)

    # Rafael annotation labels on charts ① and ②
    for xref, yref, xanchor, x_text, label in [
        ("x1", "y1", "left",  0.07, "Rafael: parallel →"),
        ("x1", "y1", "right", 0.98, "← Rafael: linear"),
        ("x2", "y2", "left",  0.07, "Rafael: parallel →"),
        ("x2", "y2", "right", 0.98, "← Rafael: linear"),
    ]:
        fig.add_annotation(
            text=label, x=x_text, y=0.92,
            xref=xref, yref=yref,
            font=dict(color=_C_RAFAEL, size=9),
            showarrow=False,
            xanchor=xanchor,
        )

    # Subplot title font
    for ann in fig.layout.annotations:
        if ann.text and ann.text[:1] in "①②③④⑤":
            ann.update(font=dict(color=_TEXT, size=13))

    fig.show()


if __name__ == "__main__":
    show()
