#!/usr/bin/env python3
# Sweep visualisation for the Simple Assembly Factory model.
#
# Reads the aggregated CSVs produced by sweep.py and shows how key output
# metrics change across the parameter space.
#
# Run:  python visualize_sweep.py
# Dependencies: pip install pandas plotly

import os
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

SWEEP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep_output")

# ── Load sweep outputs ─────────────────────────────────────────────────────────
throughput_df  = pd.read_csv(os.path.join(SWEEP_DIR, "throughput.csv"))
utilization_df = pd.read_csv(os.path.join(SWEEP_DIR, "utilization.csv"))
costs_df       = pd.read_csv(os.path.join(SWEEP_DIR, "costs.csv"))
wait_df        = pd.read_csv(os.path.join(SWEEP_DIR, "wait_times.csv"))

# ── Compute per-run aggregate metrics ─────────────────────────────────────────
# Makespan: time at which the last order completed per run
makespan = (
    throughput_df.groupby("RunID")["Time"].max()
    .reset_index().rename(columns={"Time": "Makespan"})
)

# Mean busy utilisation (%) per run, averaged across all workstations
utilization_df["BusyPct"] = (
    utilization_df["Busy"] /
    (utilization_df["Busy"] + utilization_df["Setup"] + utilization_df["Idle"])
    * 100
)
mean_util = (
    utilization_df.groupby("RunID")["BusyPct"].mean()
    .reset_index().rename(columns={"BusyPct": "MeanBusyPct"})
)

# Total cost per run (sum across all workstations)
costs_df["TotalCost"] = costs_df["SetupCost"] + costs_df["OperatingCost"] + costs_df["TransportCost"]
total_cost = (
    costs_df.groupby("RunID")["TotalCost"].sum()
    .reset_index()
)

# Mean wait time per run
mean_wait = (
    wait_df.groupby("RunID")["WaitTime"].mean()
    .reset_index().rename(columns={"WaitTime": "MeanWait"})
)

# Attach sweep parameters (take first row per RunID from throughput — all rows same)
sweep_params_cols = ["RunID", "n_products", "depth", "workstations_count",
                     "sharing_ratio", "topology"]
run_params = throughput_df[sweep_params_cols].drop_duplicates("RunID")

metrics = (
    run_params
    .merge(makespan,    on="RunID")
    .merge(mean_util,   on="RunID")
    .merge(total_cost,  on="RunID")
    .merge(mean_wait,   on="RunID")
)

# ── Theme ──────────────────────────────────────────────────────────────────────
BG      = "#0d1117"
SURFACE = "#161b22"
BORDER  = "#21262d"
TEXT    = "#e6edf3"
SUBTEXT = "#8b949e"

PALETTE = ["#58a6ff", "#d29922", "#3fb950", "#f78166", "#a371f7", "#39d353"]


def palette(i: int) -> str:
    return PALETTE[i % len(PALETTE)]


# ── Helper: mean metric grouped by one sweep parameter, split by another ──────
def group_mean(df: pd.DataFrame, x_col: str, y_col: str,
               split_col: str | None = None) -> list[dict]:
    """
    Returns a list of {label, x, y} dicts, one per unique value of split_col.
    If split_col is None, returns a single series.
    """
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


# ── Build subplots ─────────────────────────────────────────────────────────────
fig = make_subplots(
    rows=3, cols=2,
    subplot_titles=[
        "Makespan vs Workstation Count",
        "Mean Busy Utilisation vs Sharing Ratio",
        "Total Cost vs BOM Depth",
        "Mean Wait Time vs Workstation Count",
        "Makespan: Parallel vs Linear Topology",
        "Total Cost vs Number of Products",
    ],
    vertical_spacing=0.13,
    horizontal_spacing=0.1,
)

# ── 1. Makespan vs workstations_count (split by topology) ─────────────────────
for i, s in enumerate(group_mean(metrics, "workstations_count", "Makespan", "topology")):
    fig.add_trace(go.Scatter(
        x=s["x"], y=s["y"], mode="lines+markers", name=f"topology={s['label']}",
        line=dict(color=palette(i), width=2),
        marker=dict(size=7, color=palette(i)),
        legendgroup=f"topo_{s['label']}", showlegend=True,
        hovertemplate=f"<b>topology={s['label']}</b><br>WS count: %{{x}}<br>Makespan: %{{y:.2f}} h<extra></extra>",
    ), row=1, col=1)

# ── 2. Mean busy utilisation vs sharing_ratio (split by n_products) ───────────
for i, s in enumerate(group_mean(metrics, "sharing_ratio", "MeanBusyPct", "n_products")):
    fig.add_trace(go.Scatter(
        x=s["x"], y=s["y"], mode="lines+markers", name=f"n_products={s['label']}",
        line=dict(color=palette(i), width=2),
        marker=dict(size=7, color=palette(i)),
        legendgroup=f"nprод_{s['label']}", showlegend=True,
        hovertemplate=f"<b>n_products={s['label']}</b><br>Sharing ratio: %{{x}}<br>Busy: %{{y:.1f}}%<extra></extra>",
    ), row=1, col=2)

# ── 3. Total cost vs depth (split by topology) ────────────────────────────────
for i, s in enumerate(group_mean(metrics, "depth", "TotalCost", "topology")):
    fig.add_trace(go.Bar(
        x=s["x"], y=s["y"], name=f"topology={s['label']}",
        marker_color=palette(i), marker_line_width=0, opacity=0.85,
        legendgroup=f"topo_{s['label']}", showlegend=False,
        hovertemplate=f"<b>topology={s['label']}</b><br>Depth: %{{x}}<br>Cost: $%{{y:.0f}}<extra></extra>",
    ), row=2, col=1)

# ── 4. Mean wait time vs workstations_count (split by depth) ──────────────────
for i, s in enumerate(group_mean(metrics, "workstations_count", "MeanWait", "depth")):
    fig.add_trace(go.Scatter(
        x=s["x"], y=s["y"], mode="lines+markers", name=f"depth={s['label']}",
        line=dict(color=palette(i), width=2, dash="dot"),
        marker=dict(size=7, color=palette(i)),
        legendgroup=f"depth_{s['label']}", showlegend=True,
        hovertemplate=f"<b>depth={s['label']}</b><br>WS count: %{{x}}<br>Wait: %{{y:.2f}} h<extra></extra>",
    ), row=2, col=2)

# ── 5. Makespan by topology (bar — averaged over all other params) ─────────────
topo_mean = metrics.groupby("topology")["Makespan"].mean().reset_index()
fig.add_trace(go.Bar(
    x=topo_mean["topology"], y=topo_mean["Makespan"],
    marker_color=[palette(0), palette(1)], marker_line_width=0, opacity=0.85,
    showlegend=False,
    hovertemplate="<b>%{x}</b><br>Mean makespan: %{y:.2f} h<extra></extra>",
), row=3, col=1)

# ── 6. Total cost vs n_products (split by topology) ───────────────────────────
for i, s in enumerate(group_mean(metrics, "n_products", "TotalCost", "topology")):
    fig.add_trace(go.Scatter(
        x=s["x"], y=s["y"], mode="lines+markers", name=f"topology={s['label']}",
        line=dict(color=palette(i), width=2),
        marker=dict(size=7, color=palette(i)),
        legendgroup=f"topo_{s['label']}", showlegend=False,
        hovertemplate=f"<b>topology={s['label']}</b><br>Products: %{{x}}<br>Cost: $%{{y:.0f}}<extra></extra>",
    ), row=3, col=2)

# ── Global styling ─────────────────────────────────────────────────────────────
fig.update_layout(
    barmode="group",
    paper_bgcolor=BG,
    plot_bgcolor=BG,
    font=dict(color=TEXT, family="Inter, system-ui, sans-serif", size=12),
    title=dict(
        text="Parameter Sweep — Assembly Factory",
        font=dict(size=20, color=TEXT),
        x=0.02, y=0.99,
    ),
    height=1050,
    legend=dict(
        bgcolor=SURFACE, bordercolor=BORDER, borderwidth=1,
        font=dict(color=SUBTEXT, size=11),
        tracegroupgap=4,
        x=1.01, y=1,
    ),
    margin=dict(l=60, r=180, t=60, b=40),
)

for ann in fig.layout.annotations:
    ann.font.color = SUBTEXT
    ann.font.size  = 12

axis_style = dict(
    gridcolor=BORDER, zerolinecolor=BORDER,
    tickcolor=SUBTEXT, tickfont=dict(color=SUBTEXT, size=11),
    linecolor=BORDER,
)
for key in fig.layout:
    if key.startswith(("xaxis", "yaxis")):
        fig.layout[key].update(axis_style)

# Axis labels
fig.update_xaxes(title_text="Workstation count",  title_font=dict(color=SUBTEXT), row=1, col=1)
fig.update_xaxes(title_text="Sharing ratio",       title_font=dict(color=SUBTEXT), row=1, col=2)
fig.update_xaxes(title_text="BOM depth",           title_font=dict(color=SUBTEXT), row=2, col=1)
fig.update_xaxes(title_text="Workstation count",  title_font=dict(color=SUBTEXT), row=2, col=2)
fig.update_xaxes(title_text="Topology",            title_font=dict(color=SUBTEXT), row=3, col=1)
fig.update_xaxes(title_text="Number of products", title_font=dict(color=SUBTEXT), row=3, col=2)

fig.update_yaxes(title_text="Makespan (h)",  title_font=dict(color=SUBTEXT), row=1, col=1)
fig.update_yaxes(title_text="Busy (%)",      title_font=dict(color=SUBTEXT), row=1, col=2)
fig.update_yaxes(title_text="Total cost ($)", title_font=dict(color=SUBTEXT), row=2, col=1)
fig.update_yaxes(title_text="Wait time (h)", title_font=dict(color=SUBTEXT), row=2, col=2)
fig.update_yaxes(title_text="Makespan (h)",  title_font=dict(color=SUBTEXT), row=3, col=1)
fig.update_yaxes(title_text="Total cost ($)", title_font=dict(color=SUBTEXT), row=3, col=2)

fig.show()
