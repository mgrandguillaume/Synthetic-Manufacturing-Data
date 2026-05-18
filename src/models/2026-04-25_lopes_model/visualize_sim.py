#!/usr/bin/env python3
# Visualisation for a single Lopes / CLEMATIS simulation run.
#
# Reads sim_output/states.csv written by run.py and shows one chart:
#
#   Machine State % over Ticks  — % of all workstations starved / blocked /
#                                 working at every tick (faint raw + bold
#                                 rolling average).  This is the core
#                                 CLEMATIS output chart.
#
# Run standalone:  python visualize_sim.py
# Or call show()   from another script after run.py completes.
# Dependencies:    pip install pandas plotly

import os

import pandas as pd
import plotly.graph_objects as go

_BG      = "#0d1117"
_SURFACE = "#161b22"
_BORDER  = "#21262d"
_TEXT    = "#e6edf3"
_SUBTEXT = "#8b949e"

_STATE_COLORS = {
    "working": "#58a6ff",
    "blocked": "#f78166",
    "starved": "#a371f7",
}

_DEFAULT_SIM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim_output")

SMOOTH = 20   # rolling-average window in ticks


def show(sim_dir: str = _DEFAULT_SIM_DIR) -> None:
    """
    Build and display the Machine State % chart.

    Parameters
    ----------
    sim_dir : path to the folder containing states.csv.
              Defaults to sim_output/ next to this file.
    """
    df = pd.read_csv(os.path.join(sim_dir, "states.csv"))

    df["N"]          = df["Working"] + df["Starved"] + df["Blocked"]
    df["WorkingPct"] = df["Working"] / df["N"] * 100
    df["StarvedPct"] = df["Starved"] / df["N"] * 100
    df["BlockedPct"] = df["Blocked"] / df["N"] * 100

    n_ws   = int(df["N"].iloc[0])
    n_tick = len(df)

    fig = go.Figure()

    _series = [
        ("WorkingPct", _STATE_COLORS["working"], "Working"),
        ("StarvedPct", _STATE_COLORS["starved"],  "Starved"),
        ("BlockedPct", _STATE_COLORS["blocked"],  "Blocked"),
    ]

    for col, color, label in _series:
        raw      = df[col]
        smoothed = raw.rolling(window=SMOOTH, min_periods=1).mean()

        # Faint raw line
        fig.add_trace(go.Scatter(
            x=df["Tick"], y=raw,
            mode="lines",
            line=dict(color=color, width=0.75),
            opacity=0.20,
            showlegend=False,
            hoverinfo="skip",
        ))

        # Bold smoothed line
        fig.add_trace(go.Scatter(
            x=df["Tick"], y=smoothed,
            mode="lines",
            name=label,
            line=dict(color=color, width=2.5),
            legendgroup=label,
            hovertemplate=(
                f"<b>{label}</b><br>"
                "Tick: %{x}<br>%{y:.1f}% of machines<extra></extra>"
            ),
        ))

    fig.update_layout(
        paper_bgcolor=_BG,
        plot_bgcolor=_BG,
        font=dict(color=_TEXT, family="Inter, system-ui, sans-serif", size=12),
        title=dict(
            text=f"CLEMATIS / Lopes Model — Machine State %  (n={n_ws}, {n_tick} ticks)",
            font=dict(size=20, color=_TEXT),
            x=0.02, y=0.99,
        ),
        height=500,
        xaxis=dict(
            title="Tick", title_font=dict(color=_SUBTEXT),
            gridcolor=_BORDER, zerolinecolor=_BORDER,
            tickcolor=_SUBTEXT, tickfont=dict(color=_SUBTEXT, size=11),
            linecolor=_BORDER,
        ),
        yaxis=dict(
            title="% of machines", title_font=dict(color=_SUBTEXT),
            gridcolor=_BORDER, zerolinecolor=_BORDER,
            tickcolor=_SUBTEXT, tickfont=dict(color=_SUBTEXT, size=11),
            linecolor=_BORDER,
            range=[0, 100],
        ),
        legend=dict(
            bgcolor=_SURFACE, bordercolor=_BORDER, borderwidth=1,
            font=dict(color=_SUBTEXT, size=11),
            x=1.01, y=1,
        ),
        margin=dict(l=60, r=140, t=60, b=50),
    )

    fig.show()


if __name__ == "__main__":
    show()
