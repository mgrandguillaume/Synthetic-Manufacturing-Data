#!/usr/bin/env python3
# Factory-layout visualisation for a single generation run.
#
# Reads layout.csv and workstations.csv written by generate.py and renders
# an interactive graph of the factory layout:
#   • Inventory (source)  — left, green
#   • Assembly workstations (production) — centre, blue
#   • Quality Inspection (sink) — right, red
#   Edges carry capacity and transport-cost info on hover.
#
# Run standalone:  python visualize_gen.py
# Or call show()   from another script after generation completes.
# Shared style:    theme.py (model root) — colours, palette, apply_axis_style()
# Dependencies:    pip install pandas plotly networkx

import os
import sys

import pandas as pd
import plotly.graph_objects as go
import networkx as nx

# Import shared theme from the model root directory.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import theme

_DEFAULT_GEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen_output")


def show(gen_dir: str = _DEFAULT_GEN_DIR) -> None:
    """
    Build and display the factory layout graph.

    Parameters
    ----------
    gen_dir : path to the folder containing layout.csv and workstations.csv.
              Defaults to generate/gen_output/ next to this file.
    """
    layout_df = pd.read_csv(os.path.join(gen_dir, "layout.csv"))
    ws_df     = pd.read_csv(os.path.join(gen_dir, "workstations.csv"))

    # ── Build directed graph ──────────────────────────────────────────────────
    G = nx.DiGraph()
    for _, row in ws_df.iterrows():
        G.add_node(row["ID"], name=row["Name"], type=row["Type"])
    for _, row in layout_df.iterrows():
        G.add_edge(row["Origin"], row["Destination"],
                   capacity=row["Capacity"], cost=row["Cost"])

    # ── Node positions: source left, sink right, production evenly spaced ────
    prod_nodes = [n for n, d in G.nodes(data=True) if d["type"] == "production"]
    n_prod = len(prod_nodes)
    pos: dict[str, tuple[float, float]] = {}
    for node, data in G.nodes(data=True):
        if data["type"] == "source":
            pos[node] = (0.0, 0.5)
        elif data["type"] == "sink":
            pos[node] = (1.0, 0.5)
    for i, node in enumerate(prod_nodes):
        pos[node] = (0.5, (i + 1) / (n_prod + 1))

    # ── Node styling by type ──────────────────────────────────────────────────
    NODE_STYLE: dict[str, dict] = {
        "source":     {"color": "#4ade80", "border": "#16a34a"},
        "production": {"color": theme.STATE_COLORS["processing"], "border": "#2563eb"},
        "sink":       {"color": theme.STATE_COLORS["blocked"],    "border": "#dc2626"},
    }

    # ── Edge traces (lines + invisible hover points + arrowhead annotations) ─
    edge_traces: list[go.BaseTraceType] = []
    annotations: list[dict] = []
    for u, v, data in G.edges(data=True):
        x0, y0 = pos[u]
        x1, y1 = pos[v]

        # Line
        edge_traces.append(go.Scatter(
            x=[x0, x1, None], y=[y0, y1, None],
            mode="lines",
            line=dict(width=1.5, color="rgba(150,150,170,0.4)"),
            hoverinfo="none",
            showlegend=False,
        ))

        # Arrow annotation pointing toward destination
        annotations.append(dict(
            x=x1, y=y1, ax=x0, ay=y0,
            xref="x", yref="y", axref="x", ayref="y",
            showarrow=True, arrowhead=2, arrowsize=1.2,
            arrowcolor="rgba(150,150,170,0.7)", arrowwidth=1.5,
        ))

        # Invisible midpoint scatter for edge hover info
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        edge_traces.append(go.Scatter(
            x=[mx], y=[my],
            mode="markers",
            marker=dict(size=10, color="rgba(0,0,0,0)"),
            hovertemplate=(
                f"<b>{u} → {v}</b><br>"
                f"Capacity: {data['capacity']:.0f} units<br>"
                f"Transport cost: ${data['cost']:.2f}<extra></extra>"
            ),
            showlegend=False,
        ))

    # ── Node trace ────────────────────────────────────────────────────────────
    node_x, node_y   = [], []
    node_color, node_border = [], []
    node_text, node_hover   = [], []

    for node, data in G.nodes(data=True):
        x, y = pos[node]
        style = NODE_STYLE.get(data["type"], NODE_STYLE["production"])
        node_x.append(x)
        node_y.append(y)
        node_color.append(style["color"])
        node_border.append(style["border"])
        node_text.append(f"<b>{node}</b>")
        node_hover.append(
            f"<b>{node}</b><br>{data['name']}<br>Type: {data['type']}"
        )

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        text=node_text,
        textposition="top center",
        textfont=dict(size=12, color=theme.TEXT, family="Inter, system-ui, sans-serif"),
        hovertext=node_hover,
        hoverinfo="text",
        showlegend=False,
        marker=dict(
            size=36,
            color=node_color,
            line=dict(color=node_border, width=2),
            opacity=0.95,
        ),
    )

    # ── Legend entries (dummy traces, markers only) ───────────────────────────
    legend_traces = []
    for label, type_key in [("Inventory (source)", "source"),
                             ("Assembly WS (production)", "production"),
                             ("Quality Inspection (sink)", "sink")]:
        style = NODE_STYLE[type_key]
        legend_traces.append(go.Scatter(
            x=[None], y=[None],
            mode="markers",
            name=label,
            marker=dict(size=10, color=style["color"],
                        line=dict(color=style["border"], width=1.5)),
            showlegend=True,
        ))

    # ── Build figure ─────────────────────────────────────────────────────────
    fig = go.Figure(
        data=edge_traces + legend_traces + [node_trace],
        layout=go.Layout(
            title=dict(
                text="Assembly Factory — Layout Graph",
                font=dict(size=20, color=theme.TEXT,
                          family="Inter, system-ui, sans-serif"),
                x=0.02, y=0.97,
            ),
            paper_bgcolor=theme.BG,
            plot_bgcolor=theme.BG,
            showlegend=True,
            legend=dict(
                bgcolor=theme.SURFACE, bordercolor=theme.BORDER, borderwidth=1,
                font=dict(color=theme.SUBTEXT, size=11),
                x=1.01, y=1,
            ),
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
                       range=[-0.15, 1.15]),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
                       range=[-0.1, 1.1]),
            margin=dict(l=20, r=160, t=60, b=20),
            annotations=annotations,
            hoverlabel=dict(
                bgcolor=theme.SURFACE,
                bordercolor=theme.BORDER,
                font=dict(color=theme.TEXT, size=12,
                          family="Inter, system-ui, sans-serif"),
            ),
        ),
    )

    fig.show()


if __name__ == "__main__":
    show()
