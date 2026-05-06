import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os

SIM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim_output")

gantt_df      = pd.read_csv(os.path.join(SIM_DIR, "gantt.csv"))
util_df       = pd.read_csv(os.path.join(SIM_DIR, "utilization.csv"))
throughput_df = pd.read_csv(os.path.join(SIM_DIR, "throughput.csv"))
costs_df      = pd.read_csv(os.path.join(SIM_DIR, "costs.csv"))
wait_df       = pd.read_csv(os.path.join(SIM_DIR, "wait_times.csv"))

# ── Theme ─────────────────────────────────────────────────────────────────────
BG       = "#0d1117"
SURFACE  = "#161b22"
BORDER   = "#21262d"
TEXT     = "#e6edf3"
SUBTEXT  = "#8b949e"
BLUE     = "#58a6ff"
AMBER    = "#d29922"
MUTED    = "#30363d"

fig = make_subplots(
    rows=3, cols=2,
    subplot_titles=[
        "Gantt Chart", "",
        "Workstation Utilization", "Throughput Over Time",
        "Cost Breakdown", "Average Wait Time",
    ],
    specs=[
        [{"colspan": 2}, None],
        [{}, {}],
        [{}, {}],
    ],
    vertical_spacing=0.12,
    horizontal_spacing=0.1,
)

# ── 1. Gantt chart ────────────────────────────────────────────────────────────
# Two colors only: blue for processing, amber for setup
for _, row in gantt_df.iterrows():
    is_setup = row["Type"] == "setup"
    fig.add_trace(go.Bar(
        x=[row["Finish"] - row["Start"]],
        y=[row["Workstation"]],
        base=[row["Start"]],
        orientation="h",
        marker_color=AMBER if is_setup else BLUE,
        marker_line_width=0,
        opacity=0.9,
        name="Setup" if is_setup else "Processing",
        legendgroup="Setup" if is_setup else "Processing",
        showlegend=False,
        hovertemplate=(
            f"<b>{'Setup' if is_setup else row['Component']}</b><br>"
            f"Order {row['Order']}<br>"
            f"{row['Start']:.2f}h → {row['Finish']:.2f}h<extra></extra>"
        ),
    ), row=1, col=1)

# ── 2. Workstation utilization ────────────────────────────────────────────────
util_styles = [
    ("Busy",  BLUE,  True),
    ("Setup", AMBER, True),
    ("Idle",  MUTED, True),
]
for col_name, color, show in util_styles:
    fig.add_trace(go.Bar(
        name=col_name,
        x=util_df["Workstation"],
        y=util_df[col_name],
        marker_color=color,
        marker_line_width=0,
        showlegend=show,
        legendgroup=col_name,
        hovertemplate=f"<b>{col_name}</b>: %{{y:.2f}} h<extra></extra>",
    ), row=2, col=1)

# ── 3. Throughput over time ───────────────────────────────────────────────────
fig.add_trace(go.Scatter(
    x=[0.0] + throughput_df["Time"].tolist(),
    y=[0]   + throughput_df["Products"].tolist(),
    mode="lines+markers",
    line=dict(color=BLUE, width=2, shape="hv"),
    marker=dict(size=6, color=BLUE, line=dict(color=BG, width=1)),
    showlegend=False,
    hovertemplate="<b>%{y} products</b> by %{x:.2f} h<extra></extra>",
), row=2, col=2)

# ── 4. Cost breakdown ─────────────────────────────────────────────────────────
cost_styles = [
    ("SetupCost",     AMBER,   "Setup"),
    ("OperatingCost", BLUE,    "Operating"),
    ("TransportCost", SUBTEXT, "Transport"),
]
for col, color, label in cost_styles:
    fig.add_trace(go.Bar(
        name=label,
        x=costs_df["Workstation"],
        y=costs_df[col],
        marker_color=color,
        marker_line_width=0,
        showlegend=True,
        legendgroup=label,
        hovertemplate=f"<b>{label}</b>: $%{{y:.0f}}<extra></extra>",
    ), row=3, col=1)

# ── 5. Average wait time ──────────────────────────────────────────────────────
avg_wait = wait_df.groupby("Workstation")["WaitTime"].mean().reset_index()
fig.add_trace(go.Bar(
    x=avg_wait["Workstation"],
    y=avg_wait["WaitTime"],
    marker_color=BLUE,
    marker_line_width=0,
    showlegend=False,
    hovertemplate="<b>%{x}</b><br>Avg wait: %{y:.2f} h<extra></extra>",
), row=3, col=2)

# ── Global styling ────────────────────────────────────────────────────────────
fig.update_layout(
    barmode="stack",
    paper_bgcolor=BG,
    plot_bgcolor=BG,
    font=dict(color=TEXT, family="Inter, system-ui, sans-serif", size=12),
    title=dict(
        text="Assembly Line Simulation",
        font=dict(size=20, color=TEXT),
        x=0.02, y=0.99,
    ),
    height=900,
    legend=dict(
        bgcolor=SURFACE,
        bordercolor=BORDER,
        borderwidth=1,
        font=dict(color=SUBTEXT, size=11),
        tracegroupgap=2,
        x=1.01, y=1,
    ),
    margin=dict(l=60, r=160, t=60, b=40),
)

for ann in fig.layout.annotations:
    ann.font.color = SUBTEXT
    ann.font.size  = 12

axis_style = dict(
    gridcolor=BORDER,
    zerolinecolor=BORDER,
    tickcolor=SUBTEXT,
    tickfont=dict(color=SUBTEXT, size=11),
    linecolor=BORDER,
)
for key in fig.layout:
    if key.startswith(("xaxis", "yaxis")):
        fig.layout[key].update(axis_style)

fig.update_xaxes(title_text="Time (h)", title_font=dict(color=SUBTEXT), row=1, col=1)
fig.update_xaxes(title_text="Time (h)", title_font=dict(color=SUBTEXT), row=2, col=2)
fig.update_yaxes(title_text="Hours",    title_font=dict(color=SUBTEXT), row=2, col=1)
fig.update_yaxes(title_text="Products", title_font=dict(color=SUBTEXT), row=2, col=2)
fig.update_yaxes(title_text="Cost ($)", title_font=dict(color=SUBTEXT), row=3, col=1)
fig.update_yaxes(title_text="Hours",    title_font=dict(color=SUBTEXT), row=3, col=2)

fig.show()
