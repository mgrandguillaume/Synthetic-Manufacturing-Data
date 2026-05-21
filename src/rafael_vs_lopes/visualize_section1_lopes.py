#!/usr/bin/env python3
"""
Section 1 — What the Lopes model does well and where it falls short.

Runs the Lopes model in-memory for several (n, s) configurations and
produces three charts:

  Row 1  (3 columns) : Machine state % over ticks for s = 0.1, 0.5, 0.9
                       (n = 10 fixed).  Shows how topology shifts the
                       starvation / blocking balance.
  Row 2  left        : Mean working % vs seriality s for three values of n.
                       Shows that the whole parameter space has only two knobs.
  Row 2  right       : Total production per tick as a histogram.
                       Shows there is a single undifferentiated output unit —
                       no products, no BOM, no variety.

Run
---
  uv run src/rafael_vs_lopes/visualize_section1_lopes.py

Dependencies
------------
  pip install numpy plotly  (igraph installed via: uv add python-igraph)
"""

import io
import os
import sys

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Lopes model imports ────────────────────────────────────────────────────────

_HERE   = os.path.dirname(os.path.abspath(__file__))
_LOPES  = os.path.normpath(os.path.join(_HERE, "..", "models", "2026-04-25_lopes_model"))
sys.path.insert(0, _LOPES)

from generate import ModelGenerator          # noqa: E402
from simulate import DynamicManufacturing    # noqa: E402
import igraph                                # noqa: E402

# ── Theme ──────────────────────────────────────────────────────────────────────

_BG      = "#0d1117"
_SURFACE = "#161b22"
_BORDER  = "#21262d"
_TEXT    = "#e6edf3"
_SUBTEXT = "#8b949e"

_C_WORKING = "#58a6ff"
_C_STARVED = "#a371f7"
_C_BLOCKED = "#f78166"

_SMOOTH = 20

_AXIS_STYLE = dict(
    gridcolor=_BORDER,
    zerolinecolor=_BORDER,
    tickcolor=_SUBTEXT,
    tickfont=dict(color=_SUBTEXT, size=11),
    linecolor=_BORDER,
    title_font=dict(color=_SUBTEXT, size=11),
)

# ── Simulation helper ──────────────────────────────────────────────────────────

def _run(n: int, s: float, n_ticks: int = 400, seed: int = 42) -> tuple:
    """
    Run one Lopes simulation.

    Returns
    -------
    df          : DataFrame with per-tick Starved / Blocked / Working /
                  TotalProduction and their % columns
    prod_rate   : production rate per workstation per tick
    n_steps     : number of production steps
    """
    gen = ModelGenerator(n=n, s=s, failure_rate=0.05, buffer_size=5)
    ws, edges, edge_attr, vertex_attr = gen.generate_graph()

    node_to_step = {node: step for step, nodes in ws.items() for node in nodes}

    g = igraph.Graph(n=n, directed=True)
    g.add_edges(edges)
    g.vs["label"]           = vertex_attr["label"]
    g.vs["production_rate"] = vertex_attr["production_rate"]
    g.vs["failure_rate"]    = vertex_attr["failure_rate"]
    g.vs["production_step"] = [node_to_step[i] for i in range(n)]
    g.vs["buffer_size"]     = [5] * n
    g.es["buffer_size"]     = edge_attr["buffer_size"]

    sim   = DynamicManufacturing(network=g, seed=seed)
    dummy = io.StringIO()
    rows  = []

    for tick in range(n_ticks):
        tp, ns, nb, nw, _ = sim.iterate(dummy, write2file=False)
        rows.append({
            "Tick":            tick + 1,
            "Starved":         ns,
            "Blocked":         nb,
            "Working":         nw,
            "TotalProduction": tp,
        })

    df    = pd.DataFrame(rows)
    total = df["Working"] + df["Starved"] + df["Blocked"]
    df["WorkingPct"] = df["Working"] / total * 100
    df["StarvedPct"] = df["Starved"] / total * 100
    df["BlockedPct"] = df["Blocked"] / total * 100

    return df, gen.production_rate, len(ws)


# ── Entry point ────────────────────────────────────────────────────────────────

def show() -> None:
    N       = 10
    CONFIGS = [(N, 0.1), (N, 0.5), (N, 0.9)]

    # ── Run simulations ────────────────────────────────────────────────────────
    print("Running simulations for chart 1...")
    sim_data = {}
    for (n, s) in CONFIGS:
        df, rate, n_steps = _run(n, s, n_ticks=400)
        sim_data[(n, s)] = (df, rate, n_steps)
        print(f"  n={n}  s={s}  ->  {n_steps} step(s)  production_rate={rate:.3f}")

    # Alpha sweep (chart ②): n=20 fixed, s=0.05..1.0, compute actual α=p_steps/n
    # The theoretical formula (bottleneck analysis) gives working% = α for p_steps>1.
    print("Running alpha sweep for chart 2  (n=20, 20 s-values, 2000 ticks each)...")
    N_SWEEP   = 20
    alpha_exp = []   # experimental: actual α values
    work_exp  = []   # experimental: mean working %
    for k in range(1, N_SWEEP + 1):
        s      = round(k * (1.0 / N_SWEEP), 2)
        df, actual_alpha, _ = _run(N_SWEEP, s, n_ticks=2000)
        alpha_exp.append(actual_alpha)
        work_exp.append(df["WorkingPct"].mean() / 100.0)   # convert to 0–1
    print(f"  done ({N_SWEEP} runs)")

    # ── Build figure ───────────────────────────────────────────────────────────
    # Row 1: 3 machine-state charts (one per (n,s) config)
    # Row 2: colspan-2 Working% sweep  |  col-3 production histogram

    p_steps_labels = {
        0.1: "1 step — fully parallel",
        0.5: "5 steps — mixed",
        0.9: "9 steps — near-serial",
    }

    fig = make_subplots(
        rows=2, cols=3,
        specs=[
            [{}, {}, {}],
            [{"colspan": 2}, None, {}],
        ],
        subplot_titles=[
            f"① n={N}, s=0.1  ({p_steps_labels[0.1]})",
            f"① n={N}, s=0.5  ({p_steps_labels[0.5]})",
            f"① n={N}, s=0.9  ({p_steps_labels[0.9]})",
            "② Working % vs α  (bottleneck analysis + simulation,  n=20)",
            "③ Total production per tick  (one material type)",
        ],
        vertical_spacing=0.16,
        horizontal_spacing=0.08,
    )

    # ── Chart ①: machine state % over ticks (3 subplots) ──────────────────────
    for (n, s), col in zip(CONFIGS, [1, 2, 3]):
        df, _, _ = sim_data[(n, s)]
        for pct_col, color, label in [
            ("WorkingPct", _C_WORKING, "Working"),
            ("StarvedPct", _C_STARVED, "Starved"),
            ("BlockedPct", _C_BLOCKED, "Blocked"),
        ]:
            raw      = df[pct_col]
            smoothed = raw.rolling(window=_SMOOTH, min_periods=1).mean()

            # Faint raw line
            fig.add_trace(go.Scatter(
                x=df["Tick"], y=raw,
                mode="lines",
                line=dict(color=color, width=0.8),
                opacity=0.15,
                showlegend=False,
                hoverinfo="skip",
            ), row=1, col=col)

            # Bold rolling average
            fig.add_trace(go.Scatter(
                x=df["Tick"], y=smoothed,
                mode="lines",
                name=label,
                line=dict(color=color, width=2.5),
                legendgroup=f"state_{label}",
                showlegend=(col == 1),
                hovertemplate=(
                    f"<b>{label}</b><br>Tick: %{{x}}<br>%{{y:.1f}}%<extra></extra>"
                ),
            ), row=1, col=col)

    # ── Chart ②: working % vs α  (bottleneck analysis + experimental) ───────────
    # Theoretical line: working%_theory = α
    # Derived from flow conservation: in steady state each production step passes
    # the same throughput, so average working% = p_steps/n = α.
    alpha_theory = [round(k * (1.0 / N_SWEEP), 2) for k in range(1, N_SWEEP + 1)]
    work_theory  = list(alpha_theory)   # working%_theory = α

    # Theoretical line
    fig.add_trace(go.Scatter(
        x=alpha_theory,
        y=work_theory,
        mode="lines",
        name="Bottleneck analysis",
        line=dict(color="#f78166", width=2.5),
        legendgroup="theory",
        hovertemplate="α = %{x:.2f}<br>theory = %{y:.2f}<extra>Bottleneck analysis</extra>",
    ), row=2, col=1)

    # Experimental dots
    fig.add_trace(go.Scatter(
        x=alpha_exp,
        y=work_exp,
        mode="markers",
        name="Experimental",
        marker=dict(color=_C_WORKING, size=9, symbol="circle",
                    line=dict(color=_BORDER, width=1)),
        legendgroup="experiment",
        hovertemplate="α = %{x:.2f}<br>working = %{y:.2f}<extra>Experimental</extra>",
    ), row=2, col=1)

    # ── Chart ③: total production histogram ───────────────────────────────────
    df_mid = sim_data[(N, 0.5)][0]
    fig.add_trace(go.Histogram(
        x=df_mid["TotalProduction"],
        nbinsx=25,
        marker_color=_C_WORKING,
        opacity=0.85,
        name="Production  (n=10, s=0.5)",
        showlegend=False,
        hovertemplate="Value: %{x:.3f}<br>Ticks: %{y}<extra></extra>",
    ), row=2, col=3)

    # Annotate: no product types
    fig.add_annotation(
        text=(
            "All output is a single undifferentiated unit.<br>"
            "No products  ·  No BOM  ·  No costs"
        ),
        x=0.5, y=-0.20,
        xref="x5 domain", yref="y5 domain",
        xanchor="center",
        font=dict(color=_SUBTEXT, size=10),
        showarrow=False,
    )

    # ── Layout ────────────────────────────────────────────────────────────────
    fig.update_layout(
        paper_bgcolor=_BG,
        plot_bgcolor=_BG,
        font=dict(color=_TEXT, family="Inter, system-ui, sans-serif", size=12),
        height=880,
        title=dict(
            text=(
                "Section 1 — Lopes model: what it does well and where it falls short"
            ),
            font=dict(size=18, color=_TEXT),
            x=0.02, y=0.99,
        ),
        legend=dict(
            bgcolor=_SURFACE,
            bordercolor=_BORDER,
            borderwidth=1,
            font=dict(color=_SUBTEXT, size=11),
            tracegroupgap=12,
            x=1.02,
            y=0.98,
        ),
        margin=dict(l=65, r=190, t=72, b=60),
        bargap=0.1,
    )

    # Apply axis theme globally then set per-axis labels
    fig.update_xaxes(**_AXIS_STYLE)
    fig.update_yaxes(**_AXIS_STYLE)

    # Row 1: all three machine-state charts
    for col in [1, 2, 3]:
        fig.update_xaxes(title_text="Tick", row=1, col=col)
        fig.update_yaxes(range=[0, 100], row=1, col=col)
    fig.update_yaxes(title_text="% of machines", row=1, col=1)

    # Row 2
    fig.update_xaxes(title_text="α  (production steps / machines)", row=2, col=1)
    fig.update_yaxes(title_text="% Working machines", range=[0, 1.05], row=2, col=1)
    fig.update_xaxes(title_text="Units produced per tick", row=2, col=3)
    fig.update_yaxes(title_text="Number of ticks", row=2, col=3)

    # Subplot title font
    for ann in fig.layout.annotations:
        if ann.text and ann.text[0] in "①②③":
            ann.update(font=dict(color=_TEXT, size=13))

    fig.show()


if __name__ == "__main__":
    show()
