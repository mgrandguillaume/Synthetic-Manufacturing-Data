#!/usr/bin/env python3
# Sweep visualisation for the Simple Assembly Factory model.
#
# Reads the aggregated CSVs produced by sweep.py and organises the charts
# into two visual sections:
#
#   Generation Graphs  — properties of the generated factory structure
#                        (component counts, configuration density)
#
#   Simulation Graphs  — DTS performance metrics across the parameter space
#                        (makespan, utilisation, cost, lead time, state %)
#
# Run:  python visualize_sweep.py
# Dependencies: pip install pandas plotly

import os
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

SWEEP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep_output")

# ── Load sweep outputs ─────────────────────────────────────────────────────────
gen_stats_df      = pd.read_csv(os.path.join(SWEEP_DIR, "gen_stats.csv"))
state_summary_df  = pd.read_csv(os.path.join(SWEEP_DIR, "state_summary.csv"))
throughput_df     = pd.read_csv(os.path.join(SWEEP_DIR, "throughput.csv"))
utilization_df    = pd.read_csv(os.path.join(SWEEP_DIR, "utilization.csv"))
costs_df          = pd.read_csv(os.path.join(SWEEP_DIR, "costs.csv"))

# ── Compute per-run simulation metrics ────────────────────────────────────────
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
    .merge(makespan,     on="RunID")
    .merge(mean_util,    on="RunID")
    .merge(mean_starved, on="RunID")
    .merge(total_cost,   on="RunID")
    .merge(mean_lead,    on="RunID")
)

# ── Compute sweep-wide mean state % per tick for the CLEMATIS summary chart ───
# Each run contributes one row per tick (WorkingPct, StarvedPct, BlockedPct
# already averaged across workstations).  Average across all runs per tick to
# get the sweep-wide trend line.
state_mean_tick = (
    state_summary_df
    .groupby("Tick")[["WorkingPct", "StarvedPct", "BlockedPct"]]
    .mean()
    .reset_index()
)

# ── Theme ──────────────────────────────────────────────────────────────────────
BG      = "#0d1117"
SURFACE = "#161b22"
BORDER  = "#21262d"
TEXT    = "#e6edf3"
SUBTEXT = "#8b949e"

PALETTE = ["#58a6ff", "#d29922", "#3fb950", "#f78166", "#a371f7", "#39d353"]

STATE_COLORS = {
    "BusyPct":    "#58a6ff",
    "BlockedPct": "#f78166",
    "StarvedPct": "#a371f7",
}


def palette(i: int) -> str:
    return PALETTE[i % len(PALETTE)]


# ── Helper: group-mean series ──────────────────────────────────────────────────
def group_mean(df: pd.DataFrame, x_col: str, y_col: str,
               split_col: str | None = None) -> list[dict]:
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


# ── Legend style ───────────────────────────────────────────────────────────────
def _legend_style(x: float, y: float, title: str) -> dict:
    return dict(
        x=x, y=y, xanchor="right", yanchor="top",
        bgcolor=SURFACE, bordercolor=BORDER, borderwidth=1,
        font=dict(color=SUBTEXT, size=10),
        title=dict(text=f"<b>{title}</b>", font=dict(color=SUBTEXT, size=10)),
    )


# 5 rows × 2 cols, vertical_spacing=0.12, horizontal_spacing=0.10.
# Available height = 1 - 4×0.12 = 0.52; each row ≈ 0.104 tall.
# Row tops (paper y):  row1≈1.00, row2≈0.776, row3≈0.552, row4≈0.328, row5≈0.104
# Col right edges:     col1≈0.44, col2≈0.99
_L = {
    "legend":  _legend_style(0.44, 0.97, "products"),   # row 1, col 1
    "legend2": _legend_style(0.99, 0.97, "depth"),      # row 1, col 2
    "legend3": _legend_style(0.44, 0.76, "depth"),      # row 2, col 1
    "legend4": _legend_style(0.99, 0.76, "products"),   # row 2, col 2
    "legend5": _legend_style(0.44, 0.54, "products"),   # row 3, col 1
    "legend6": _legend_style(0.99, 0.54, "depth"),      # row 3, col 2
    "legend7": _legend_style(0.44, 0.32, "depth"),      # row 4, col 1
    "legend8": _legend_style(0.99, 0.32, "state"),      # row 4, col 2
    "legend9": _legend_style(0.99, 0.10, "depth"),      # row 5, col 1-2 (full-width)
}

# ── Build subplots ─────────────────────────────────────────────────────────────
fig = make_subplots(
    rows=5, cols=2,
    subplot_titles=[
        # Row 1 — Generation Graphs
        "Component Count vs BOM Depth",
        "Configuration Count vs Workstations",
        # Row 2 — Simulation Graphs
        "Makespan vs Alpha",
        "Mean Busy Utilisation vs Sharing Ratio",
        # Row 3
        "Total Cost vs BOM Depth",
        "Mean Lead Time vs Alpha",
        # Row 4
        "Starved % vs Alpha",
        "Mean State % over Iterations  (sweep-wide avg)",
        # Row 5 — full-width
        "% Working Machines vs Alpha",
        "",
    ],
    specs=[
        [{}, {}],
        [{}, {}],
        [{}, {}],
        [{}, {}],
        [{"colspan": 2}, None],
    ],
    vertical_spacing=0.12,
    horizontal_spacing=0.10,
)

# ── Section header annotations ────────────────────────────────────────────────
# "Generation Graphs" sits just above row 1 (in the top margin).
# "Simulation Graphs" sits in the gap between rows 1 and 2 (y ≈ 0.77).
SECTION_FONT = dict(color=TEXT, size=13)

fig.add_annotation(
    x=0.5, y=0.836,
    xref="paper", yref="paper",
    text="<b>── Simulation Graphs ──────────────────────────────────────────</b>",
    showarrow=False, font=SECTION_FONT, align="center",
)

# ── Row 1, col 1 — Component count vs depth (split by n_products) ─────────────
for i, s in enumerate(group_mean(gen_stats_df, "depth", "n_components", "n_products")):
    fig.add_trace(go.Scatter(
        x=s["x"], y=s["y"], mode="lines+markers",
        name=s["label"],
        line=dict(color=palette(i), width=2),
        marker=dict(size=7, color=palette(i)),
        legend="legend",
        hovertemplate=(
            f"products={s['label']}<br>"
            "Depth: %{x}<br>Components: %{y:.1f}<extra></extra>"
        ),
    ), row=1, col=1)

# ── Row 1, col 2 — Configuration count vs workstations (split by depth) ───────
for i, s in enumerate(group_mean(gen_stats_df, "workstations_count", "n_configs", "depth")):
    fig.add_trace(go.Scatter(
        x=s["x"], y=s["y"], mode="lines+markers",
        name=s["label"],
        line=dict(color=palette(i), width=2),
        marker=dict(size=7, color=palette(i)),
        legend="legend2",
        hovertemplate=(
            f"depth={s['label']}<br>"
            "Workstations: %{x}<br>Configs: %{y:.1f}<extra></extra>"
        ),
    ), row=1, col=2)

# ── Row 2, col 1 — Makespan vs alpha (split by depth) ────────────────────────
for i, s in enumerate(group_mean(sim_metrics, "alpha", "Makespan", "depth")):
    fig.add_trace(go.Scatter(
        x=s["x"], y=s["y"], mode="lines+markers",
        name=s["label"],
        line=dict(color=palette(i), width=2),
        marker=dict(size=7, color=palette(i)),
        legend="legend3",
        hovertemplate=(
            f"depth={s['label']}<br>"
            "α: %{x:.3f}<br>Makespan: %{y:.2f} h<extra></extra>"
        ),
    ), row=2, col=1)

# ── Row 2, col 2 — Mean busy % vs sharing ratio (split by n_products) ─────────
for i, s in enumerate(group_mean(sim_metrics, "sharing_ratio", "MeanBusyPct", "n_products")):
    fig.add_trace(go.Scatter(
        x=s["x"], y=s["y"], mode="lines+markers",
        name=s["label"],
        line=dict(color=palette(i), width=2),
        marker=dict(size=7, color=palette(i)),
        legend="legend4",
        hovertemplate=(
            f"products={s['label']}<br>"
            "Sharing: %{x}<br>Busy: %{y:.1f}%<extra></extra>"
        ),
    ), row=2, col=2)

# ── Row 3, col 1 — Total cost vs depth (bar, split by n_products) ─────────────
for i, s in enumerate(group_mean(sim_metrics, "depth", "TotalCost", "n_products")):
    fig.add_trace(go.Bar(
        x=s["x"], y=s["y"],
        name=s["label"],
        marker_color=palette(i), marker_line_width=0, opacity=0.85,
        legend="legend5",
        hovertemplate=(
            f"products={s['label']}<br>"
            "Depth: %{x}<br>Cost: $%{y:.0f}<extra></extra>"
        ),
    ), row=3, col=1)

# ── Row 3, col 2 — Mean lead time vs alpha (split by depth) ──────────────────
for i, s in enumerate(group_mean(sim_metrics, "alpha", "MeanLeadTime", "depth")):
    fig.add_trace(go.Scatter(
        x=s["x"], y=s["y"], mode="lines+markers",
        name=s["label"],
        line=dict(color=palette(i), width=2, dash="dot"),
        marker=dict(size=7, color=palette(i)),
        legend="legend6",
        hovertemplate=(
            f"depth={s['label']}<br>"
            "α: %{x:.3f}<br>Lead time: %{y:.2f} h<extra></extra>"
        ),
    ), row=3, col=2)

# ── Row 4, col 1 — Starved % vs alpha (split by depth) ───────────────────────
for i, s in enumerate(group_mean(sim_metrics, "alpha", "MeanStarvedPct", "depth")):
    fig.add_trace(go.Scatter(
        x=s["x"], y=s["y"], mode="lines+markers",
        name=s["label"],
        line=dict(color=palette(i), width=2, dash="dash"),
        marker=dict(size=7, color=palette(i)),
        legend="legend7",
        hovertemplate=(
            f"depth={s['label']}<br>"
            "α: %{x:.3f}<br>Starved: %{y:.1f}%<extra></extra>"
        ),
    ), row=4, col=1)

# ── Row 4, col 2 — CLEMATIS aggregate: mean state % vs iteration (tick) ───────
# Sweep-wide average of Working / Starved / Blocked % at every simulation tick.
# Mirrors the single-run CLEMATIS chart; shows how the aggregate state
# composition evolves over the course of a typical run.
for state_col, state_label, state_color in [
    ("WorkingPct", "Working", STATE_COLORS["BusyPct"]),
    ("StarvedPct", "Starved", STATE_COLORS["StarvedPct"]),
    ("BlockedPct", "Blocked", STATE_COLORS["BlockedPct"]),
]:
    fig.add_trace(go.Scatter(
        x=state_mean_tick["Tick"].tolist(),
        y=state_mean_tick[state_col].tolist(),
        mode="lines",
        name=state_label,
        legendgroup=f"state_{state_col}",
        line=dict(color=state_color, width=2),
        legend="legend8",
        hovertemplate=(
            f"<b>{state_label}</b><br>"
            "Tick: %{x}<br>%{y:.1f}% of machines<extra></extra>"
        ),
    ), row=4, col=2)

# ── Row 5 (full-width) — % working machines vs alpha (split by depth) ─────────
# Shows how machine utilisation changes with the serial/parallel topology ratio.
# Each depth has its own alpha range (α = depth / n_ws), so splitting by depth
# keeps lines monotone and directly comparable to the Lopes paper figure.
for i, s in enumerate(group_mean(sim_metrics, "alpha", "MeanBusyPct", "depth")):
    fig.add_trace(go.Scatter(
        x=s["x"], y=s["y"], mode="lines+markers",
        name=s["label"],
        line=dict(color=palette(i), width=2.5),
        marker=dict(size=8, color=palette(i)),
        legend="legend9",
        hovertemplate=(
            f"depth={s['label']}<br>"
            "α: %{x:.3f}<br>Working: %{y:.1f}%<extra></extra>"
        ),
    ), row=5, col=1)

# ── Global styling ─────────────────────────────────────────────────────────────
fig.update_layout(
    barmode="group",
    paper_bgcolor=BG,
    plot_bgcolor=BG,
    font=dict(color=TEXT, family="Inter, system-ui, sans-serif", size=12),
    title=dict(
        text=(
            "Parameter Sweep — Assembly Factory (DTS)"
            "<br><sup><span style='color:#8b949e;font-size:13px'>"
            "── Generation Graphs ─────────────────────────────────────"
            "</span></sup>"
        ),
        font=dict(size=20, color=TEXT),
        x=0.02, y=0.99,
    ),
    height=1700,
    margin=dict(l=60, r=40, t=90, b=40),
    **{"legend" + ("" if k == 0 else str(k + 1)): v
       for k, v in enumerate(_L.values())},
)

for ann in fig.layout.annotations:
    ann.font.color = SUBTEXT
    ann.font.size  = 12

# Re-apply bolder styling to the section header annotation (it comes last).
fig.layout.annotations[-1].font.color = TEXT
fig.layout.annotations[-1].font.size  = 13

axis_style = dict(
    gridcolor=BORDER, zerolinecolor=BORDER,
    tickcolor=SUBTEXT, tickfont=dict(color=SUBTEXT, size=11),
    linecolor=BORDER,
)
for key in fig.layout:
    if key.startswith(("xaxis", "yaxis")):
        fig.layout[key].update(axis_style)

# X-axis labels
fig.update_xaxes(title_text="BOM depth",                  title_font=dict(color=SUBTEXT), row=1, col=1)
fig.update_xaxes(title_text="Workstations",               title_font=dict(color=SUBTEXT), row=1, col=2)
fig.update_xaxes(title_text="α = depth / workstations",   title_font=dict(color=SUBTEXT), row=2, col=1)
fig.update_xaxes(title_text="Sharing ratio",              title_font=dict(color=SUBTEXT), row=2, col=2)
fig.update_xaxes(title_text="BOM depth",                  title_font=dict(color=SUBTEXT), row=3, col=1)
fig.update_xaxes(title_text="α = depth / workstations",   title_font=dict(color=SUBTEXT), row=3, col=2)
fig.update_xaxes(title_text="α = depth / workstations",   title_font=dict(color=SUBTEXT), row=4, col=1)
fig.update_xaxes(title_text="Iteration (tick)",            title_font=dict(color=SUBTEXT), row=4, col=2)
fig.update_xaxes(title_text="α = depth / workstations",   title_font=dict(color=SUBTEXT), row=5, col=1)

# Y-axis labels
fig.update_yaxes(title_text="Components (non-raw)", title_font=dict(color=SUBTEXT), row=1, col=1)
fig.update_yaxes(title_text="Configurations",       title_font=dict(color=SUBTEXT), row=1, col=2)
fig.update_yaxes(title_text="Makespan (h)",         title_font=dict(color=SUBTEXT), row=2, col=1)
fig.update_yaxes(title_text="Busy (%)",             title_font=dict(color=SUBTEXT), row=2, col=2)
fig.update_yaxes(title_text="Total cost ($)",       title_font=dict(color=SUBTEXT), row=3, col=1)
fig.update_yaxes(title_text="Lead time (h)",        title_font=dict(color=SUBTEXT), row=3, col=2)
fig.update_yaxes(title_text="Starved (%)",          title_font=dict(color=SUBTEXT), row=4, col=1)
fig.update_yaxes(title_text="% of machines",        title_font=dict(color=SUBTEXT), row=4, col=2)
fig.update_yaxes(title_text="Working (%)",          title_font=dict(color=SUBTEXT), row=5, col=1)

fig.show()
