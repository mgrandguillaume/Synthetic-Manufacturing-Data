import pandas as pd
import plotly.graph_objects as go
import networkx as nx
import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "gen_output")

layout_df = pd.read_csv(os.path.join(OUTPUT_DIR, "layout.csv"))
ws_df     = pd.read_csv(os.path.join(OUTPUT_DIR, "workstations.csv"))

G = nx.DiGraph()
for _, row in ws_df.iterrows():
    G.add_node(row["ID"], name=row["Name"], type=row["Type"])
for _, row in layout_df.iterrows():
    G.add_edge(row["Origin"], row["Destination"],
               capacity=row["Capacity"], cost=row["Cost"])

# Layout: source left, sink right, production nodes evenly spaced in middle
prod_nodes = [n for n, d in G.nodes(data=True) if d["type"] == "production"]
n_prod = len(prod_nodes)
pos = {}
for node, data in G.nodes(data=True):
    if data["type"] == "source":
        pos[node] = (0.0, 0.5)
    elif data["type"] == "sink":
        pos[node] = (1.0, 0.5)
for i, node in enumerate(prod_nodes):
    pos[node] = (0.5, (i + 1) / (n_prod + 1))

NODE_STYLE = {
    "source":     {"color": "#4ade80", "border": "#16a34a", "symbol": "circle"},
    "production": {"color": "#60a5fa", "border": "#2563eb", "symbol": "circle"},
    "sink":       {"color": "#f87171", "border": "#dc2626", "symbol": "circle"},
}

# Edge traces (lines only, no labels — labels on hover)
edge_traces = []
annotations = []
for u, v, data in G.edges(data=True):
    x0, y0 = pos[u]
    x1, y1 = pos[v]
    edge_traces.append(go.Scatter(
        x=[x0, x1, None], y=[y0, y1, None],
        mode="lines",
        line=dict(width=1.5, color="rgba(150,150,170,0.4)"),
        hoverinfo="none",
    ))
    # Arrow pointing toward destination (v)
    annotations.append(dict(
        x=x1, y=y1, ax=x0, ay=y0,
        xref="x", yref="y", axref="x", ayref="y",
        showarrow=True, arrowhead=2, arrowsize=1.2,
        arrowcolor="rgba(150,150,170,0.7)", arrowwidth=1.5,
    ))
    # Invisible scatter point at midpoint to show edge info on hover
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    edge_traces.append(go.Scatter(
        x=[mx], y=[my], mode="markers",
        marker=dict(size=10, color="rgba(0,0,0,0)"),
        hovertemplate=f"<b>{u} → {v}</b><br>Capacity: {data['capacity']:.0f}<br>Cost: {data['cost']:.2f}<extra></extra>",
    ))

# Node trace
node_x, node_y, node_hover, node_color, node_border, node_text = [], [], [], [], [], []
for node, data in G.nodes(data=True):
    x, y = pos[node]
    style = NODE_STYLE[data["type"]]
    node_x.append(x); node_y.append(y)
    node_color.append(style["color"])
    node_border.append(style["border"])
    node_text.append(f"<b>{node}</b>")
    node_hover.append(f"<b>{node}</b><br>{data['name']}<br>Type: {data['type']}")

node_trace = go.Scatter(
    x=node_x, y=node_y,
    mode="markers+text",
    text=node_text,
    textposition="top center",
    textfont=dict(size=12, color="white", family="Inter, sans-serif"),
    hovertext=node_hover,
    hoverinfo="text",
    marker=dict(
        size=36,
        color=node_color,
        line=dict(color=node_border, width=2),
        opacity=0.95,
    ),
)

fig = go.Figure(
    data=edge_traces + [node_trace],
    layout=go.Layout(
        title=dict(
            text="Factory Layout",
            font=dict(size=22, color="white", family="Inter, sans-serif"),
            x=0.04, y=0.96,
        ),
        paper_bgcolor="#0f1117",
        plot_bgcolor="#0f1117",
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
                   range=[-0.15, 1.15]),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
                   range=[-0.1, 1.1]),
        margin=dict(l=20, r=20, t=60, b=20),
        annotations=annotations,
        hoverlabel=dict(
            bgcolor="#1e2130",
            bordercolor="#3a3f55",
            font=dict(color="white", size=12, family="Inter, sans-serif"),
        ),
    )
)

fig.show()
