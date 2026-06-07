#!/usr/bin/env python3
# Sweep visualisation for the Simple Assembly Factory model.
#
# Reads the aggregated CSVs produced by sweep.py and organises the charts
# into two visual sections:
#
#   Generation Graphs  — properties of the generated factory structure
#                        (component counts, raw materials, configuration density)
#
#   Simulation Graphs  — DTS performance metrics across the parameter space
#                        (makespan, utilisation, cost, lead time, state %)
#
# Run standalone:  python visualize_sweep.py
# Or call show()   from another script after the sweep completes (sweep.py does this).
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

_DEFAULT_SWEEP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep_output")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _group_mean(df: pd.DataFrame, x_col: str, y_col: str,
                split_col: str | None = None) -> list[dict]:
    """Return a list of {label, x, y} dicts, one per split group."""
    groups = [None] if split_col is None else sorted(df[split_col].unique())
    series = []
    for grp in groups:
        subset = df if grp is None else df[df[split_col] == grp]
        agg    = subset.groupby(x_col)[y_col].mean().reset_index()
        series.append({
            "label": str(grp) if grp is not None else y_col,
            "x":     agg[x_col].tolist(),
            "y":     agg[y_col].tolist(),
        })
    return series


def _legend_style(x: float, y: float, title: str) -> dict:
    """Return a positioned legend dict using the shared theme colours."""
    return dict(
        x=x, y=y, xanchor="right", yanchor="top",
        bgcolor=theme.SURFACE, bordercolor=theme.BORDER, borderwidth=1,
        font=dict(color=theme.SUBTEXT, size=10),
        title=dict(text=f"<b>{title}</b>", font=dict(color=theme.SUBTEXT, size=10)),
    )


# Cost-share series: (display label, fraction column, colour)
_COST_SHARE_SERIES = [
    ("Setup",     "SetupFrac", theme.STATE_COLORS["setup"]),
    ("Operating", "OpFrac",    theme.STATE_COLORS["processing"]),
    ("Transport", "TransFrac", theme.SUBTEXT),
]


def show(sweep_dir: str = _DEFAULT_SWEEP_DIR) -> None:
    """
    Build and display all twelve sweep charts.

    Parameters
    ----------
    sweep_dir : path to the folder containing the five sweep output CSVs.
                Defaults to sweep/sweep_output/ next to this file.
    """

    # ── Load data ──────────────────────────────────────────────────────────────
    gen_stats_df     = pd.read_csv(os.path.join(sweep_dir, "gen_stats.csv"))
    state_summary_df = pd.read_csv(os.path.join(sweep_dir, "state_summary.csv"))
    throughput_df    = pd.read_csv(os.path.join(sweep_dir, "throughput.csv"))
    utilization_df   = pd.read_csv(os.path.join(sweep_dir, "utilization.csv"))
    costs_df         = pd.read_csv(os.path.join(sweep_dir, "costs.csv"))

    # ── Compute per-run simulation metrics ─────────────────────────────────────
    makespan = (
        throughput_df.groupby("RunID")["Time"].max()
        .reset_index().rename(columns={"Time": "Makespan"})
    )
    mean_util = (
        utilization_df.groupby("RunID")["BusyPct"].mean()
        .reset_index().rename(columns={"BusyPct": "MeanBusyPct"})
    )
    mean_starved = (
        utilization_df.groupby("RunID")["StarvedPct"].mean()
        .reset_index().rename(columns={"StarvedPct": "MeanStarvedPct"})
    )
    mean_setup_pct = (
        utilization_df.groupby("RunID")["SetupPct"].mean()
        .reset_index().rename(columns={"SetupPct": "MeanSetupPct"})
    )

    costs_df["TotalCost"] = (
        costs_df["SetupCost"] + costs_df["OperatingCost"] + costs_df["TransportCost"]
    )
    total_cost = costs_df.groupby("RunID")["TotalCost"].sum().reset_index()

    mean_lead = (
        throughput_df.groupby("RunID")["LeadTime"].mean()
        .reset_index().rename(columns={"LeadTime": "MeanLeadTime"})
    )

    sweep_params_cols = ["RunID", "alpha", "n_products", "depth",
                         "workstations_count", "sharing_ratio"]
    run_params = throughput_df[sweep_params_cols].drop_duplicates("RunID")

    sim_metrics = (
        run_params
        .merge(makespan,       on="RunID")
        .merge(mean_util,      on="RunID")
        .merge(mean_starved,   on="RunID")
        .merge(total_cost,     on="RunID")
        .merge(mean_lead,      on="RunID")
        .merge(mean_setup_pct, on="RunID")
    )

    # ── Cost share per sharing ratio ───────────────────────────────────────────
    cost_share_run = (
        costs_df.groupby("RunID")[["SetupCost", "OperatingCost", "TransportCost"]]
        .sum().reset_index()
    )
    cost_share_run["Total"] = (
        cost_share_run["SetupCost"]
        + cost_share_run["OperatingCost"]
        + cost_share_run["TransportCost"]
    )
    cost_share_run["SetupFrac"] = cost_share_run["SetupCost"]     / cost_share_run["Total"] * 100
    cost_share_run["OpFrac"]    = cost_share_run["OperatingCost"] / cost_share_run["Total"] * 100
    cost_share_run["TransFrac"] = cost_share_run["TransportCost"] / cost_share_run["Total"] * 100
    cost_share_run = cost_share_run.merge(run_params[["RunID", "sharing_ratio"]], on="RunID")
    cost_share_by_ratio = (
        cost_share_run.groupby("sharing_ratio")[["SetupFrac", "OpFrac", "TransFrac"]]
        .mean().reset_index()
    )

    # ── Sweep-wide mean state % per tick (CLEMATIS summary) ───────────────────
    state_mean_tick = (
        state_summary_df
        .groupby("Tick")[["WorkingPct", "StarvedPct", "BlockedPct"]]
        .mean()
        .reset_index()
    )

    # ── Legend positions ───────────────────────────────────────────────────────
    # 6 rows × 2 cols, vertical_spacing=0.10
    # Row tops (paper y): 1.00, 0.817, 0.633, 0.450, 0.267, 0.083
    # Col right edges:    col1≈0.44, col2≈0.99
    _L = {
        "legend":   _legend_style(0.44, 0.97, "products"),   # row 1, col 1
        "legend2":  _legend_style(0.99, 0.97, "depth"),      # row 1, col 2
        "legend3":  _legend_style(0.44, 0.80, "products"),   # row 2, col 1
        "legend4":  _legend_style(0.99, 0.80, "depth"),      # row 2, col 2
        "legend5":  _legend_style(0.44, 0.61, "products"),   # row 3, col 1
        "legend6":  _legend_style(0.99, 0.61, "sharing"),    # row 3, col 2
        "legend7":  _legend_style(0.44, 0.42, "products"),   # row 4, col 1
        "legend8":  _legend_style(0.99, 0.42, "depth"),      # row 4, col 2
        "legend9":  _legend_style(0.44, 0.24, "cost type"),  # row 5, col 1
        "legend10": _legend_style(0.99, 0.24, "depth"),      # row 5, col 2
        "legend11": _legend_style(0.44, 0.06, "state"),      # row 6, col 1
        "legend12": _legend_style(0.99, 0.06, "depth"),      # row 6, col 2
    }

    # ── Build subplots ─────────────────────────────────────────────────────────
    fig = make_subplots(
        rows=6, cols=2,
        subplot_titles=[
            # Row 1 — Generation Graphs
            "Component Count vs BOM Depth",
            "Configuration Count vs Workstations",
            # Row 2 — last gen + first sim
            "Raw Material Count vs BOM Depth",
            "Makespan vs Alpha",
            # Row 3 — Simulation Graphs
            "Mean Busy Utilisation vs Sharing Ratio",
            "Mean Lead Time vs n_products",
            # Row 4
            "Total Cost vs BOM Depth",
            "Setup Time Fraction vs Sharing Ratio",
            # Row 5
            "Cost Share vs Sharing Ratio",
            "Starved % vs Alpha",
            # Row 6
            "Mean State % over Iterations  (sweep-wide avg)",
            "% Working Machines vs Alpha",
        ],
        specs=[[{}, {}]] * 6,
        vertical_spacing=0.10,
        horizontal_spacing=0.10,
    )

    # ── Section header annotations ─────────────────────────────────────────────
    # "Generation Graphs" sits above row 1 (y > 1.0 paper).
    # "Simulation Graphs" sits in the gap between rows 2 and 3 (y ≈ 0.68).
    SECTION_FONT = dict(color=theme.TEXT, size=13)

    fig.add_annotation(
        x=0.5, y=1.03, xref="paper", yref="paper",
        text="<b>── Generation Graphs ──────────────────────────────────────────</b>",
        showarrow=False, font=SECTION_FONT, align="center",
    )
    fig.add_annotation(
        x=0.5, y=0.68, xref="paper", yref="paper",
        text="<b>── Simulation Graphs ──────────────────────────────────────────</b>",
        showarrow=False, font=SECTION_FONT, align="center",
    )

    # ── Row 1 — Generation: component count & config count ────────────────────
    for i, s in enumerate(_group_mean(gen_stats_df, "depth", "n_components", "n_products")):
        fig.add_trace(go.Scatter(
            x=s["x"], y=s["y"], mode="lines+markers", name=s["label"],
            line=dict(color=theme.palette(i), width=2),
            marker=dict(size=7, color=theme.palette(i)),
            legend="legend",
            hovertemplate=f"products={s['label']}<br>Depth: %{{x}}<br>Components: %{{y:.1f}}<extra></extra>",
        ), row=1, col=1)

    for i, s in enumerate(_group_mean(gen_stats_df, "workstations_count", "n_configs", "depth")):
        fig.add_trace(go.Scatter(
            x=s["x"], y=s["y"], mode="lines+markers", name=s["label"],
            line=dict(color=theme.palette(i), width=2),
            marker=dict(size=7, color=theme.palette(i)),
            legend="legend2",
            hovertemplate=f"depth={s['label']}<br>Workstations: %{{x}}<br>Configs: %{{y:.1f}}<extra></extra>",
        ), row=1, col=2)

    # ── Row 2 — Generation: raw material count | Simulation: makespan ─────────
    for i, s in enumerate(_group_mean(gen_stats_df, "depth", "n_raw", "n_products")):
        fig.add_trace(go.Scatter(
            x=s["x"], y=s["y"], mode="lines+markers", name=s["label"],
            line=dict(color=theme.palette(i), width=2),
            marker=dict(size=7, color=theme.palette(i)),
            legend="legend3",
            hovertemplate=f"products={s['label']}<br>Depth: %{{x}}<br>Raw materials: %{{y:.1f}}<extra></extra>",
        ), row=2, col=1)

    for i, s in enumerate(_group_mean(sim_metrics, "alpha", "Makespan", "depth")):
        fig.add_trace(go.Scatter(
            x=s["x"], y=s["y"], mode="lines+markers", name=s["label"],
            line=dict(color=theme.palette(i), width=2),
            marker=dict(size=7, color=theme.palette(i)),
            legend="legend4",
            hovertemplate=f"depth={s['label']}<br>α: %{{x:.3f}}<br>Makespan: %{{y:.2f}} h<extra></extra>",
        ), row=2, col=2)

    # ── Row 3 — Busy % vs sharing ratio | Lead time vs n_products ────────────
    for i, s in enumerate(_group_mean(sim_metrics, "sharing_ratio", "MeanBusyPct", "n_products")):
        fig.add_trace(go.Scatter(
            x=s["x"], y=s["y"], mode="lines+markers", name=s["label"],
            line=dict(color=theme.palette(i), width=2),
            marker=dict(size=7, color=theme.palette(i)),
            legend="legend5",
            hovertemplate=f"products={s['label']}<br>Sharing: %{{x}}<br>Busy: %{{y:.1f}}%<extra></extra>",
        ), row=3, col=1)

    for i, s in enumerate(_group_mean(sim_metrics, "n_products", "MeanLeadTime", "sharing_ratio")):
        fig.add_trace(go.Scatter(
            x=s["x"], y=s["y"], mode="lines+markers", name=s["label"],
            line=dict(color=theme.palette(i), width=2, dash="dot"),
            marker=dict(size=7, color=theme.palette(i)),
            legend="legend6",
            hovertemplate=f"sharing={s['label']}<br>Products: %{{x}}<br>Lead time: %{{y:.2f}} h<extra></extra>",
        ), row=3, col=2)

    # ── Row 4 — Total cost vs depth | Setup fraction vs sharing ratio ──────────
    for i, s in enumerate(_group_mean(sim_metrics, "depth", "TotalCost", "n_products")):
        fig.add_trace(go.Bar(
            x=s["x"], y=s["y"], name=s["label"],
            marker_color=theme.palette(i), marker_line_width=0, opacity=0.85,
            legend="legend7",
            hovertemplate=f"products={s['label']}<br>Depth: %{{x}}<br>Cost: $%{{y:.0f}}<extra></extra>",
        ), row=4, col=1)

    for i, s in enumerate(_group_mean(sim_metrics, "sharing_ratio", "MeanSetupPct", "depth")):
        fig.add_trace(go.Scatter(
            x=s["x"], y=s["y"], mode="lines+markers", name=s["label"],
            line=dict(color=theme.palette(i), width=2),
            marker=dict(size=7, color=theme.palette(i)),
            legend="legend8",
            hovertemplate=f"depth={s['label']}<br>Sharing: %{{x}}<br>Setup: %{{y:.1f}}%<extra></extra>",
        ), row=4, col=2)

    # ── Row 5 — Cost share vs sharing ratio | Starved % vs alpha ─────────────
    for label, col, color in _COST_SHARE_SERIES:
        fig.add_trace(go.Scatter(
            x=cost_share_by_ratio["sharing_ratio"].tolist(),
            y=cost_share_by_ratio[col].tolist(),
            mode="lines+markers", name=label,
            line=dict(color=color, width=2),
            marker=dict(size=7, color=color),
            legend="legend9",
            hovertemplate=f"<b>{label}</b><br>Sharing: %{{x}}<br>Share: %{{y:.1f}}%<extra></extra>",
        ), row=5, col=1)

    for i, s in enumerate(_group_mean(sim_metrics, "alpha", "MeanStarvedPct", "depth")):
        fig.add_trace(go.Scatter(
            x=s["x"], y=s["y"], mode="lines+markers", name=s["label"],
            line=dict(color=theme.palette(i), width=2, dash="dash"),
            marker=dict(size=7, color=theme.palette(i)),
            legend="legend10",
            hovertemplate=f"depth={s['label']}<br>α: %{{x:.3f}}<br>Starved: %{{y:.1f}}%<extra></extra>",
        ), row=5, col=2)

    # ── Row 6 — CLEMATIS sweep-wide avg | % Working vs alpha ──────────────────
    for state_col, state_label, state_color in [
        ("WorkingPct", "Working", theme.STATE_COLORS["processing"]),
        ("StarvedPct", "Starved", theme.STATE_COLORS["starved"]),
        ("BlockedPct", "Blocked", theme.STATE_COLORS["blocked"]),
    ]:
        fig.add_trace(go.Scatter(
            x=state_mean_tick["Tick"].tolist(),
            y=state_mean_tick[state_col].tolist(),
            mode="lines", name=state_label,
            legendgroup=f"state_{state_col}",
            line=dict(color=state_color, width=2),
            legend="legend11",
            hovertemplate=f"<b>{state_label}</b><br>Tick: %{{x}}<br>%{{y:.1f}}% of machines<extra></extra>",
        ), row=6, col=1)

    for i, s in enumerate(_group_mean(sim_metrics, "alpha", "MeanBusyPct", "depth")):
        fig.add_trace(go.Scatter(
            x=s["x"], y=s["y"], mode="lines+markers", name=s["label"],
            line=dict(color=theme.palette(i), width=2.5),
            marker=dict(size=8, color=theme.palette(i)),
            legend="legend12",
            hovertemplate=f"depth={s['label']}<br>α: %{{x:.3f}}<br>Working: %{{y:.1f}}%<extra></extra>",
        ), row=6, col=2)

    # ── Global styling ─────────────────────────────────────────────────────────
    fig.update_layout(
        barmode="group",
        paper_bgcolor=theme.BG,
        plot_bgcolor=theme.BG,
        font=dict(color=theme.TEXT, family="Inter, system-ui, sans-serif", size=12),
        title=dict(
            text="Parameter Sweep — Assembly Factory (DTS)",
            font=dict(size=20, color=theme.TEXT),
            x=0.02, y=0.99,
        ),
        height=2000,
        margin=dict(l=60, r=40, t=120, b=40),
        **{"legend" + ("" if k == 0 else str(k + 1)): v
           for k, v in enumerate(_L.values())},
    )

    for ann in fig.layout.annotations:
        ann.font.color = theme.SUBTEXT
        ann.font.size  = 12

    # Re-apply bold styling to both section header annotations (added last).
    for ann in fig.layout.annotations[-2:]:
        ann.font.color = theme.TEXT
        ann.font.size  = 13

    theme.apply_axis_style(fig)

    fig.update_xaxes(title_text="BOM depth",                title_font=dict(color=theme.SUBTEXT), row=1, col=1)
    fig.update_xaxes(title_text="Workstations",             title_font=dict(color=theme.SUBTEXT), row=1, col=2)
    fig.update_xaxes(title_text="BOM depth",                title_font=dict(color=theme.SUBTEXT), row=2, col=1)
    fig.update_xaxes(title_text="α = depth / workstations", title_font=dict(color=theme.SUBTEXT), row=2, col=2)
    fig.update_xaxes(title_text="Sharing ratio",            title_font=dict(color=theme.SUBTEXT), row=3, col=1)
    fig.update_xaxes(title_text="n_products",               title_font=dict(color=theme.SUBTEXT), row=3, col=2)
    fig.update_xaxes(title_text="BOM depth",                title_font=dict(color=theme.SUBTEXT), row=4, col=1)
    fig.update_xaxes(title_text="Sharing ratio",            title_font=dict(color=theme.SUBTEXT), row=4, col=2)
    fig.update_xaxes(title_text="Sharing ratio",            title_font=dict(color=theme.SUBTEXT), row=5, col=1)
    fig.update_xaxes(title_text="α = depth / workstations", title_font=dict(color=theme.SUBTEXT), row=5, col=2)
    fig.update_xaxes(title_text="Iteration (tick)",         title_font=dict(color=theme.SUBTEXT), row=6, col=1)
    fig.update_xaxes(title_text="α = depth / workstations", title_font=dict(color=theme.SUBTEXT), row=6, col=2)

    fig.update_yaxes(title_text="Components (non-raw)", title_font=dict(color=theme.SUBTEXT), row=1, col=1)
    fig.update_yaxes(title_text="Configurations",       title_font=dict(color=theme.SUBTEXT), row=1, col=2)
    fig.update_yaxes(title_text="Raw materials",        title_font=dict(color=theme.SUBTEXT), row=2, col=1)
    fig.update_yaxes(title_text="Makespan (h)",         title_font=dict(color=theme.SUBTEXT), row=2, col=2)
    fig.update_yaxes(title_text="Busy (%)",             title_font=dict(color=theme.SUBTEXT), row=3, col=1)
    fig.update_yaxes(title_text="Lead time (h)",        title_font=dict(color=theme.SUBTEXT), row=3, col=2)
    fig.update_yaxes(title_text="Total cost ($)",       title_font=dict(color=theme.SUBTEXT), row=4, col=1)
    fig.update_yaxes(title_text="Setup time (%)",       title_font=dict(color=theme.SUBTEXT), row=4, col=2)
    fig.update_yaxes(title_text="Cost share (%)",       title_font=dict(color=theme.SUBTEXT), row=5, col=1)
    fig.update_yaxes(title_text="Starved (%)",          title_font=dict(color=theme.SUBTEXT), row=5, col=2)
    fig.update_yaxes(title_text="% of machines",        title_font=dict(color=theme.SUBTEXT), row=6, col=1)
    fig.update_yaxes(title_text="Working (%)",          title_font=dict(color=theme.SUBTEXT), row=6, col=2)

    fig.show()


if __name__ == "__main__":
    show()
