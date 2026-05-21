#!/usr/bin/env python3
"""
Section 4 — Direct head-to-head comparison.

Four charts arranged in two rows that make the argument visually explicit:

  Row 1 (2 columns) : ① Lopes machine state % over ticks (n=10, s=0.5)
                    | ② Alpha machine state % over ticks (alpha=0.5, depth=2)
                      Same metric on the same scale — Alpha adds BOM structure
                      without losing any simulation fidelity.

  Row 2 (2 columns) : ③ Parameter space coverage
                        x = topology (α-equivalent), y = BOM depth.
                        Lopes: horizontal band at depth=1 (no BOM).
                        Rafael: two discrete points (parallel / linear).
                        Alpha: full 2-D scatter of every sweep run.
                    | ④ Capability matrix (table)
                        Rows = models, columns = features,
                        green ✓ / red ✗ cells.

Run
---
  uv run src/rafael_vs_lopes/visualize_section4_comparison.py

Dependencies
------------
  pip install pandas plotly
"""

import os
import sys

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Paths ──────────────────────────────────────────────────────────────────────

_HERE       = os.path.dirname(os.path.abspath(__file__))
_LOPES_DIR  = os.path.normpath(os.path.join(_HERE, "..", "models", "2026-04-25_lopes_model"))
_ALPHA_DIR  = os.path.normpath(
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
_C_ALPHA   = "#d29922"
_C_LOPES   = "#58a6ff"

_SMOOTH = 15

_AXIS_STYLE = dict(
    gridcolor=_BORDER,
    zerolinecolor=_BORDER,
    tickcolor=_SUBTEXT,
    tickfont=dict(color=_SUBTEXT, size=11),
    linecolor=_BORDER,
    title_font=dict(color=_SUBTEXT, size=11),
)

# ── Data loading ───────────────────────────────────────────────────────────────

def _load():
    lopes = pd.read_csv(os.path.join(_LOPES_DIR, "sim_output", "states.csv"))
    ss    = pd.read_csv(os.path.join(_ALPHA_DIR, "state_summary.csv"))
    gs    = pd.read_csv(os.path.join(_ALPHA_DIR, "gen_stats.csv"))
    return lopes, ss, gs


# ── Chart ①: Lopes machine state % ─────────────────────────────────────────────

def _chart_lopes_states(fig, lopes, row, col):
    """
    Rolling-average machine state % for the Lopes run (n=10, s=0.5).
    Converts raw counts → percentage and smooths with a rolling window.
    """
    total      = lopes["Working"] + lopes["Starved"] + lopes["Blocked"]
    lopes      = lopes.copy()
    lopes["WorkingPct"] = lopes["Working"] / total * 100
    lopes["StarvedPct"] = lopes["Starved"] / total * 100
    lopes["BlockedPct"] = lopes["Blocked"] / total * 100

    first = True
    for pct_col, color, label in [
        ("WorkingPct", _C_WORKING, "Working"),
        ("StarvedPct", _C_STARVED, "Starved"),
        ("BlockedPct", _C_BLOCKED, "Blocked"),
    ]:
        raw      = lopes[pct_col]
        smoothed = raw.rolling(window=_SMOOTH, min_periods=1).mean()

        # Faint raw line
        fig.add_trace(go.Scatter(
            x=lopes["Tick"], y=raw,
            mode="lines",
            line=dict(color=color, width=0.8),
            opacity=0.15,
            showlegend=False,
            hoverinfo="skip",
        ), row=row, col=col)

        # Bold smoothed line
        fig.add_trace(go.Scatter(
            x=lopes["Tick"], y=smoothed,
            mode="lines",
            name=label,
            line=dict(color=color, width=2.5),
            legendgroup=f"state_{label}",
            showlegend=True,
            hovertemplate=(
                f"<b>{label}</b><br>Tick: %{{x}}<br>%{{y:.1f}}%<extra>Lopes</extra>"
            ),
        ), row=row, col=col)

        first = False

    # Annotation: what is absent
    fig.add_annotation(
        text="No BOM  ·  Homogeneous machines  ·  No costs",
        x=0.5, y=-0.18,
        xref="x domain", yref="y domain",
        xanchor="center",
        font=dict(color=_C_BLOCKED, size=9),
        showarrow=False,
    )


# ── Chart ②: Alpha machine state % ─────────────────────────────────────────────

def _chart_alpha_states(fig, ss, row, col):
    """
    Rolling-average machine state % for Alpha run at alpha=0.5, depth=2
    (RunID=68, sharing_ratio=0.5 — representative mid-point run).
    """
    run = ss[(ss["RunID"] == 68)].sort_values("Tick")

    for pct_col, color, label in [
        ("WorkingPct", _C_WORKING, "Working"),
        ("StarvedPct", _C_STARVED, "Starved"),
        ("BlockedPct", _C_BLOCKED, "Blocked"),
    ]:
        raw      = run[pct_col]
        smoothed = raw.rolling(window=_SMOOTH, min_periods=1).mean()

        fig.add_trace(go.Scatter(
            x=run["Tick"], y=raw,
            mode="lines",
            line=dict(color=color, width=0.8),
            opacity=0.15,
            showlegend=False,
            hoverinfo="skip",
        ), row=row, col=col)

        fig.add_trace(go.Scatter(
            x=run["Tick"], y=smoothed,
            mode="lines",
            name=label,
            line=dict(color=color, width=2.5),
            legendgroup=f"state_{label}",
            showlegend=False,       # legend already added by chart ①
            hovertemplate=(
                f"<b>{label}</b><br>Tick: %{{x}}<br>%{{y:.1f}}%<extra>Alpha</extra>"
            ),
        ), row=row, col=col)

    # Annotation: what is present
    fig.add_annotation(
        text="BOM depth 2  ·  alpha = 0.5  ·  20 products  ·  costs tracked",
        x=0.5, y=-0.18,
        xref="x2 domain", yref="y2 domain",
        xanchor="center",
        font=dict(color=_C_RAFAEL, size=9),
        showarrow=False,
    )


# ── Chart ③: Parameter space coverage ─────────────────────────────────────────

def _chart_param_space(fig, gs, row, col):
    """
    x = alpha (0 → parallel, 1 → serial)
    y = BOM depth (1 → flat, 5 → deep hierarchy)

    Lopes:  horizontal band at depth=1, alpha spans 0→1 (s is continuous).
            Drawn as a shaded region + label.
    Rafael: two discrete markers at (alpha≈0, depth=varies) and (alpha=1, depth=varies).
            Represented as markers along x=0.05 and x=1.0 for depth 1-5.
    Alpha:  scatter of all 270 sweep runs (each unique combo is shown once).
    """
    # ── Alpha: all unique (alpha, depth) combinations ─────────────────────────
    unique_runs = gs[["alpha", "depth"]].drop_duplicates().sort_values(["depth", "alpha"])
    fig.add_trace(go.Scatter(
        x=unique_runs["alpha"],
        y=unique_runs["depth"],
        mode="markers",
        name="Alpha model",
        marker=dict(
            color=_C_ALPHA,
            size=8,
            opacity=0.75,
            symbol="circle",
            line=dict(color=_BG, width=0.5),
        ),
        legendgroup="alpha_ps",
        hovertemplate="alpha = %{x:.2f}<br>BOM depth = %{y}<extra>Alpha</extra>",
    ), row=row, col=col)

    # ── Rafael: 2 discrete topology options, shown for depth 1-5 ──────────────
    rafael_x = [0.05, 1.0]
    rafael_labels = ["parallel", "linear"]
    for xval, lbl in zip(rafael_x, rafael_labels):
        fig.add_trace(go.Scatter(
            x=[xval] * 5,
            y=list(range(1, 6)),
            mode="markers",
            name=f"Rafael ({lbl})" if xval == 0.05 else f"Rafael ({lbl})",
            marker=dict(
                color=_C_RAFAEL,
                size=11,
                symbol="diamond",
                line=dict(color=_TEXT, width=1),
            ),
            legendgroup=f"rafael_{lbl}",
            hovertemplate=(
                f"Rafael: {lbl}<br>BOM depth = %{{y}}<extra></extra>"
            ),
        ), row=row, col=col)

    # ── Lopes: shaded band at y = 0.5..1.5 (no real BOM depth) ───────────────
    fig.add_trace(go.Scatter(
        x=[0.0, 1.0, 1.0, 0.0],
        y=[0.6, 0.6, 1.4, 1.4],
        fill="toself",
        fillcolor="rgba(88,166,255,0.10)",
        line=dict(color=_C_LOPES, width=1.5, dash="dot"),
        mode="lines",
        name="Lopes model",
        legendgroup="lopes_ps",
        hoverinfo="skip",
    ), row=row, col=col)

    fig.add_annotation(
        text="Lopes: continuous s, no BOM",
        x=0.5, y=1.0,
        xref="x3", yref="y3",
        font=dict(color=_C_LOPES, size=9),
        showarrow=False,
    )

    # Dashed vlines for Rafael positions
    for xval, lbl in zip([0.05, 1.0], ["parallel", "linear"]):
        fig.add_vline(
            x=xval, row=row, col=col,
            line_dash="dot", line_color=_C_RAFAEL, line_width=1.2,
        )


def _subplot_xref(row, col):
    """Return the axis number for a given subplot position (2-col layout)."""
    # Row 1: axes 1,2; Row 2: axes 3,4
    idx = (row - 1) * 2 + col
    return "" if idx == 1 else str(idx)


# ── Chart ④: Capability matrix ─────────────────────────────────────────────────

def _chart_capability(fig, row, col):
    """
    A go.Table capability matrix:
      rows    = Lopes, Rafael, Alpha
      columns = 8 features
    """
    features = [
        "Simulation\n(machine states)",
        "Starvation /\nblocking dynamics",
        "Bill of Materials\n(product hierarchy)",
        "Heterogeneous\nmachines",
        "Continuous\ntopology",
        "Setup / operating\ncosts",
        "Lead time\ntracking",
        "Parameter-space\ncoverage",
    ]

    data = {
        #               Lopes   Rafael  Alpha
        features[0]: [  True,   False,  True  ],
        features[1]: [  True,   False,  True  ],
        features[2]: [  False,  True,   True  ],
        features[3]: [  False,  True,   True  ],
        features[4]: [  True,   False,  True  ],
        features[5]: [  False,  False,  True  ],
        features[6]: [  False,  False,  True  ],
        features[7]: [  False,  False,  True  ],
    }

    TICK  = "✓"
    CROSS = "✗"

    header_vals = ["Feature", "Lopes", "Rafael", "Alpha"]
    rows_data   = [[], [], [], []]  # [feature, lopes, rafael, alpha]
    fill_colors = [[], [], [], []]

    _HEADER_FILL  = "#1c2128"
    _GREEN_FILL   = "rgba(63,185,80,0.18)"
    _RED_FILL     = "rgba(247,129,102,0.18)"
    _FEAT_FILL    = "#161b22"

    for feat, (lopes_v, rafael_v, alpha_v) in data.items():
        rows_data[0].append(feat)
        rows_data[1].append(TICK  if lopes_v  else CROSS)
        rows_data[2].append(TICK  if rafael_v else CROSS)
        rows_data[3].append(TICK  if alpha_v  else CROSS)

        fill_colors[0].append(_FEAT_FILL)
        fill_colors[1].append(_GREEN_FILL if lopes_v  else _RED_FILL)
        fill_colors[2].append(_GREEN_FILL if rafael_v else _RED_FILL)
        fill_colors[3].append(_GREEN_FILL if alpha_v  else _RED_FILL)

    # Font colours matching fill
    def _font_col(vals, model_vals):
        return [
            "#3fb950" if v == TICK else "#f78166"
            for v in vals
        ]

    fig.add_trace(go.Table(
        header=dict(
            values=[f"<b>{h}</b>" for h in header_vals],
            fill_color=_HEADER_FILL,
            font=dict(color=_TEXT, size=12),
            align="center",
            height=32,
            line=dict(color=_BORDER, width=1),
        ),
        cells=dict(
            values=rows_data,
            fill_color=fill_colors,
            font=dict(
                color=[
                    [_SUBTEXT] * len(rows_data[0]),
                    _font_col(rows_data[1], rows_data[1]),
                    _font_col(rows_data[2], rows_data[2]),
                    _font_col(rows_data[3], rows_data[3]),
                ],
                size=12,
            ),
            align=["left", "center", "center", "center"],
            height=30,
            line=dict(color=_BORDER, width=1),
        ),
        columnwidth=[3.5, 1, 1, 1],
    ), row=row, col=col)


# ── Entry point ────────────────────────────────────────────────────────────────

def show() -> None:
    lopes, ss, gs = _load()

    fig = make_subplots(
        rows=2, cols=2,
        specs=[
            [{}, {}],
            [{}, {"type": "table"}],
        ],
        subplot_titles=[
            "① Lopes — machine state %  (n=10, s=0.5)",
            "② Alpha — machine state %  (α=0.5, depth=2, 20 products)",
            "③ Parameter space coverage",
            "④ Capability matrix",
        ],
        vertical_spacing=0.16,
        horizontal_spacing=0.10,
        row_heights=[0.45, 0.55],
    )

    _chart_lopes_states(fig, lopes, row=1, col=1)
    _chart_alpha_states(fig, ss,    row=1, col=2)
    _chart_param_space(fig, gs,     row=2, col=1)
    _chart_capability(fig,          row=2, col=2)

    # ── Layout ────────────────────────────────────────────────────────────────
    fig.update_layout(
        paper_bgcolor=_BG,
        plot_bgcolor=_BG,
        font=dict(color=_TEXT, family="Inter, system-ui, sans-serif", size=12),
        height=1050,
        title=dict(
            text="Section 4 — Direct head-to-head comparison",
            font=dict(size=18, color=_TEXT),
            x=0.02, y=0.99,
        ),
        legend=dict(
            bgcolor=_SURFACE, bordercolor=_BORDER, borderwidth=1,
            font=dict(color=_SUBTEXT, size=11),
            tracegroupgap=10, x=1.02, y=0.98,
        ),
        margin=dict(l=65, r=190, t=72, b=60),
    )

    fig.update_xaxes(**_AXIS_STYLE)
    fig.update_yaxes(**_AXIS_STYLE)

    # Per-axis labels
    fig.update_xaxes(title_text="Tick",                              row=1, col=1)
    fig.update_yaxes(title_text="% of machines", range=[0, 100],    row=1, col=1)
    fig.update_xaxes(title_text="Tick",                              row=1, col=2)
    fig.update_yaxes(title_text="% of machines", range=[0, 100],    row=1, col=2)
    fig.update_xaxes(
        title_text="α = depth / workstations  (0 = parallel, 1 = serial)",
        range=[-0.05, 1.10], row=2, col=1,
    )
    fig.update_yaxes(
        title_text="BOM depth",
        tickvals=list(range(1, 6)),
        ticktext=[str(d) for d in range(1, 6)],
        range=[0.2, 5.6], row=2, col=1,
    )

    # Subplot title font
    for ann in fig.layout.annotations:
        if ann.text and ann.text[:1] in "①②③④⑤":
            ann.update(font=dict(color=_TEXT, size=13))

    fig.show()


if __name__ == "__main__":
    show()
