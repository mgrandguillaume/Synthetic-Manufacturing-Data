#!/usr/bin/env python3
"""
Section 2 — What the Rafael model does well and where it falls short.

Generates factory data using the Python BOM model (same logic as Rafael)
and produces four charts:

  Row 1  (full width) : BOM tree visualisation (depth=2, n_products=2,
                        sharing_ratio=0.0).  Shows the DAG structure,
                        component hierarchy, and heterogeneous quantities.
  Row 2  (2 columns)  : Component count vs BOM depth  |
                        Configuration count vs BOM depth
                        (split by n_products).  Shows structural complexity
                        that Lopes cannot represent.
  Row 3  (2 columns)  : Factory layout — topology=parallel  |
                        Factory layout — topology=linear.
                        Shows the binary choice that Rafael offers.
  Row 4  (full width) : "What is missing" — feature comparison table.

Run
---
  uv run src/rafael_vs_lopes/visualize_section2_rafael.py

Dependencies
------------
  pip install pyyaml plotly
"""

import os
import sys

import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Alpha/Python model generator import ───────────────────────────────────────
# Use importlib to load by file path so that the module name "generate" does
# not collide with any other generate.py that may be on sys.path.

import importlib.util as _ilu

_HERE      = os.path.dirname(os.path.abspath(__file__))
_GEN_FILE  = os.path.normpath(
    os.path.join(_HERE, "..", "models", "2026-04-28_python_model", "generate", "generate.py")
)
_spec = _ilu.spec_from_file_location("python_model_generate", _GEN_FILE)
_mod  = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
generate_from_params = _mod.generate_from_params

# ── Theme ──────────────────────────────────────────────────────────────────────

_BG      = "#0d1117"
_SURFACE = "#161b22"
_BORDER  = "#21262d"
_TEXT    = "#e6edf3"
_SUBTEXT = "#8b949e"

_C_RAW   = "#8b949e"    # grey   — raw materials
_C_COMP  = "#58a6ff"    # blue   — intermediate components
_C_PROD  = "#d29922"    # amber  — finished products
_C_WS    = "#3fb950"    # green  — workstations
_C_INV   = "#a371f7"    # purple — Inv / QI nodes
_C_EDGE  = "#30363d"    # dark   — BOM edges

_N_COLORS = {1: "#58a6ff", 2: "#d29922", 3: "#3fb950"}

_AXIS_STYLE = dict(
    gridcolor=_BORDER,
    zerolinecolor=_BORDER,
    tickcolor=_SUBTEXT,
    tickfont=dict(color=_SUBTEXT, size=11),
    linecolor=_BORDER,
    title_font=dict(color=_SUBTEXT, size=11),
    showgrid=False,
)

# ── Base generation params (fixed across all charts) ──────────────────────────

_BASE = {
    "branching":               [2, 3],
    "quantity":                [1, 3],
    "workstations_count":      4,
    "producers_per_component": [1, 2],
    "processing_time":         [1, 5],
    "setup_time":              [0.5, 2],
    "setup_cost":              [10, 50],
    "operating_cost":          [1, 10],
    "flow_capacity":           [50, 200],
    "transport_cost":          [1, 5],
    "seed":                    7,
}


# ── BOM tree layout ────────────────────────────────────────────────────────────

def _tree_positions(components, bom_edges):
    """
    Compute (x, y) positions for all nodes using a bottom-up algorithm:

    1. Group nodes by BOM level.
    2. Assign raw materials (level 0) evenly spaced on y = 0.
    3. For each higher level, place each node at the mean x of its children.

    Returns
    -------
    pos : dict  node_id → (x, y)
    """
    # Build children map: parent_id → [child_id, ...]
    children = {}
    for edge in bom_edges:
        children.setdefault(edge.output, [])
        if edge.input not in children[edge.output]:
            children[edge.output].append(edge.input)

    # Group by level
    by_level = {}
    for c in components:
        by_level.setdefault(c.level, []).append(c.id)

    levels = sorted(by_level.keys())
    pos    = {}

    # Level 0 — raw materials: evenly spaced
    raws = by_level.get(0, [])
    for i, node in enumerate(raws):
        pos[node] = (float(i), 0.0)

    # Levels 1+ — place at mean x of children
    for lvl in levels[1:]:
        for node in by_level[lvl]:
            child_ids = children.get(node, [])
            if child_ids and all(c in pos for c in child_ids):
                x = sum(pos[c][0] for c in child_ids) / len(child_ids)
            else:
                # fallback: spread evenly
                idx = by_level[lvl].index(node)
                x   = float(idx) * (len(raws) / max(1, len(by_level[lvl]) - 1))
            pos[node] = (x, float(lvl))

    return pos


def _chart_bom_tree(fig, result, row, col):
    """
    Draw the BOM as a DAG: edges as lines, nodes as scatter markers,
    colour-coded by level (raw / intermediate / product).
    """
    components = result["components"]
    bom_edges  = result["bom_edges"]

    pos = _tree_positions(components, bom_edges)

    # ── Edges ──────────────────────────────────────────────────────────────────
    for edge in bom_edges:
        if edge.input not in pos or edge.output not in pos:
            continue
        x0, y0 = pos[edge.input]
        x1, y1 = pos[edge.output]
        fig.add_trace(go.Scatter(
            x=[x0, x1, None],
            y=[y0, y1, None],
            mode="lines",
            line=dict(color=_C_EDGE, width=1.5),
            showlegend=False,
            hoverinfo="skip",
        ), row=row, col=col)

    # ── Nodes grouped by type ──────────────────────────────────────────────────
    groups = {
        "Raw material (level 0)":  (lambda c: c.level == 0,           _C_RAW,  8,  "circle"),
        "Intermediate component":  (lambda c: c.level > 0 and not c.is_product, _C_COMP, 12, "circle"),
        "Finished product":        (lambda c: c.is_product,           _C_PROD, 16, "diamond"),
    }

    for label, (pred, color, size, symbol) in groups.items():
        nodes = [c for c in components if pred(c)]
        if not nodes:
            continue
        xs = [pos[c.id][0] for c in nodes if c.id in pos]
        ys = [pos[c.id][1] for c in nodes if c.id in pos]
        labels = [c.id.replace("_", " ") for c in nodes if c.id in pos]

        fig.add_trace(go.Scatter(
            x=xs, y=ys,
            mode="markers+text",
            marker=dict(color=color, size=size, symbol=symbol,
                        line=dict(color=_BORDER, width=1)),
            text=labels,
            textposition="top center",
            textfont=dict(color=color, size=9),
            name=label,
            legendgroup=f"bom_{label}",
            hovertemplate="%{text}<extra></extra>",
        ), row=row, col=col)

    # Hide axes for the tree chart
    fig.update_xaxes(showticklabels=False, showgrid=False,
                     zeroline=False, row=row, col=col)
    fig.update_yaxes(showticklabels=False, showgrid=False,
                     zeroline=False, row=row, col=col)


# ── Complexity charts ──────────────────────────────────────────────────────────

def _chart_complexity(fig, row, col_comp, col_cfg):
    """
    Two line charts: component count and configuration count vs BOM depth,
    one line per number of products.
    """
    depths     = [1, 2, 3, 4]
    n_products = [1, 2, 3]

    for n_prod in n_products:
        comp_counts = []
        cfg_counts  = []
        for depth in depths:
            r = generate_from_params({
                **_BASE,
                "depth":      depth,
                "n_products": n_prod,
                "sharing_ratio": 0.0,
                "topology":   "parallel",
            })
            comp_counts.append(len(r["components"]))
            cfg_counts.append(len(r["configurations"]))

        color = _N_COLORS[n_prod]

        fig.add_trace(go.Scatter(
            x=depths, y=comp_counts,
            mode="lines+markers",
            name=f"{n_prod} product(s)",
            line=dict(color=color, width=2.2),
            marker=dict(color=color, size=7),
            legendgroup=f"np_{n_prod}",
            legendgrouptitle_text="Products" if n_prod == 1 else "",
            hovertemplate=(
                f"{n_prod} product(s)<br>depth %{{x}}<br>"
                "%{y} components<extra></extra>"
            ),
        ), row=row, col=col_comp)

        fig.add_trace(go.Scatter(
            x=depths, y=cfg_counts,
            mode="lines+markers",
            name=f"{n_prod} product(s)",
            line=dict(color=color, width=2.2),
            marker=dict(color=color, size=7),
            legendgroup=f"np_{n_prod}",
            showlegend=False,
            hovertemplate=(
                f"{n_prod} product(s)<br>depth %{{x}}<br>"
                "%{y} configurations<extra></extra>"
            ),
        ), row=row, col=col_cfg)

    # Lopes reference line on both charts
    for c in [col_comp, col_cfg]:
        fig.add_hline(
            y=1,
            line_dash="dash",
            line_color=_SUBTEXT,
            line_width=1.2,
            annotation_text="Lopes (always 1)",
            annotation_position="top left",
            annotation_font=dict(color=_SUBTEXT, size=9),
            row=row, col=c,
        )


# ── Factory layout charts ──────────────────────────────────────────────────────

def _draw_layout_graph(fig, layout_edges, workstations, row, col, title_note):
    """
    Draw a workstation network graph using manual node positions.
    Inv on the far left, QI on the far right, production WS in between.
    """
    # Determine all unique node IDs and assign positions
    ws_ids = [ws.id for ws in workstations if ws.type == "production"]
    n_ws   = len(ws_ids)

    # Decide layout based on edges
    origins = [e.origin for e in layout_edges]
    is_linear = (origins.count("Inv") == 1)

    if is_linear:
        # Chain: Inv → WS_1 → WS_2 → ... → QI, horizontal
        node_pos = {"Inv": (0.0, 0.0), "QI": (float(n_ws + 1), 0.0)}
        for i, ws_id in enumerate(ws_ids, start=1):
            node_pos[ws_id] = (float(i), 0.0)
    else:
        # Parallel: Inv left, QI right, WS stacked in the middle
        node_pos = {"Inv": (0.0, 0.0), "QI": (2.0, 0.0)}
        for i, ws_id in enumerate(ws_ids):
            y = (n_ws - 1) / 2.0 - i   # centre the stack vertically
            node_pos[ws_id] = (1.0, y)

    # Edges
    for edge in layout_edges:
        if edge.origin not in node_pos or edge.destination not in node_pos:
            continue
        x0, y0 = node_pos[edge.origin]
        x1, y1 = node_pos[edge.destination]
        fig.add_trace(go.Scatter(
            x=[x0, x1, None], y=[y0, y1, None],
            mode="lines",
            line=dict(color="#3d444d", width=2),
            showlegend=False, hoverinfo="skip",
        ), row=row, col=col)

    # Nodes
    node_types = {ws.id: ws.type for ws in workstations}
    for node_id, (x, y) in node_pos.items():
        ntype = node_types.get(node_id, "source")
        color = _C_INV if ntype in ("source", "sink") else _C_WS
        size  = 22 if ntype in ("source", "sink") else 18

        fig.add_trace(go.Scatter(
            x=[x], y=[y],
            mode="markers+text",
            marker=dict(color=color, size=size,
                        line=dict(color=_BORDER, width=1.5)),
            text=[node_id],
            textposition="top center" if not is_linear else "top center",
            textfont=dict(color=color, size=10),
            showlegend=False,
            hovertemplate=f"{node_id}  ({ntype})<extra></extra>",
        ), row=row, col=col)

    # Add a note label at the bottom
    fig.add_annotation(
        text=title_note,
        x=0.5, y=-0.18,
        xref=f"x{_subplot_idx(row, col)} domain",
        yref=f"y{_subplot_idx(row, col)} domain",
        xanchor="center",
        font=dict(color=_SUBTEXT, size=10),
        showarrow=False,
    )

    fig.update_xaxes(showticklabels=False, showgrid=False,
                     zeroline=False, row=row, col=col)
    fig.update_yaxes(showticklabels=False, showgrid=False,
                     zeroline=False, row=row, col=col)


def _subplot_idx(row: int, col: int) -> str:
    """
    Map (row, col) to plotly axis index string for the subplot layout used
    in this figure.

    Layout (6 actual subplots):
      row 1 col 1   → colspan 2 → axis 1
      row 2 col 1   → axis 2
      row 2 col 2   → axis 3
      row 3 col 1   → axis 4
      row 3 col 2   → axis 5
      row 4 colspan → axis 6  (table — not used here)
    """
    mapping = {(1, 1): "", (2, 1): "2", (2, 2): "3",
               (3, 1): "4", (3, 2): "5"}
    return mapping.get((row, col), "")


# ── Feature table ──────────────────────────────────────────────────────────────

def _chart_table(fig, row, col):
    """Comparison table: features × models with ✓ / ✗ cells."""
    features = [
        "Bill of Materials (BOM)",
        "Multiple product types",
        "Heterogeneous machines",
        "Continuous topology parameter",
        "Discrete-Time Simulation",
        "Machine state logs (starved / blocked)",
        "Throughput & lead times",
        "Cost tracking",
        "Setup times & changeovers",
    ]
    lopes = ["✗", "✗", "✗", "✓", "✓", "✓", "✗", "✗", "✗"]
    rafael = ["✓", "✓", "✓", "✗", "✗", "✗", "✗", "✗", "✓"]
    alpha  = ["✓", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "✓"]

    def cell_colors(vals):
        return ["#1a3a1a" if v == "✓" else "#3a1a1a" for v in vals]

    header_fill = "#21262d"
    row_fill    = ["#161b22", "#0d1117"] * (len(features) // 2 + 1)

    fig.add_trace(go.Table(
        header=dict(
            values=["<b>Feature</b>", "<b>Lopes</b>", "<b>Rafael</b>", "<b>Alpha</b>"],
            fill_color=header_fill,
            font=dict(color=_TEXT, size=12),
            align="left",
            height=32,
            line=dict(color=_BORDER, width=1),
        ),
        cells=dict(
            values=[features, lopes, rafael, alpha],
            fill_color=[
                row_fill[:len(features)],
                cell_colors(lopes),
                cell_colors(rafael),
                cell_colors(alpha),
            ],
            font=dict(
                color=[
                    [_TEXT] * len(features),
                    ["#3fb950" if v == "✓" else "#f78166" for v in lopes],
                    ["#3fb950" if v == "✓" else "#f78166" for v in rafael],
                    ["#3fb950" if v == "✓" else "#f78166" for v in alpha],
                ],
                size=12,
            ),
            align=["left", "center", "center", "center"],
            height=28,
            line=dict(color=_BORDER, width=1),
        ),
    ), row=row, col=col)


# ── Entry point ────────────────────────────────────────────────────────────────

def show() -> None:
    # Generate the BOM tree sample
    print("Generating factory data...")
    bom_result = generate_from_params({
        **_BASE,
        "n_products":    2,
        "depth":         2,
        "sharing_ratio": 0.0,
        "topology":      "parallel",
    })

    par_result = generate_from_params({
        **_BASE,
        "n_products":    2,
        "depth":         2,
        "sharing_ratio": 0.0,
        "topology":      "parallel",
    })
    lin_result = generate_from_params({
        **_BASE,
        "n_products":    2,
        "depth":         2,
        "sharing_ratio": 0.0,
        "topology":      "linear",
    })
    print("  Done.")

    # ── Build figure ───────────────────────────────────────────────────────────
    fig = make_subplots(
        rows=4, cols=2,
        specs=[
            [{"colspan": 2, "type": "xy"}, None],
            [{"type": "xy"}, {"type": "xy"}],
            [{"type": "xy"}, {"type": "xy"}],
            [{"colspan": 2, "type": "table"}, None],
        ],
        subplot_titles=[
            "① BOM tree  (depth=2, n_products=2, sharing_ratio=0)",
            "② Component count vs BOM depth",
            "② Configuration count vs BOM depth",
            "③ Factory layout — topology = parallel",
            "③ Factory layout — topology = linear (series)",
            "",   # table row — no title needed
        ],
        vertical_spacing=0.08,
        horizontal_spacing=0.10,
        row_heights=[0.30, 0.22, 0.20, 0.28],
    )

    _chart_bom_tree(fig, bom_result, row=1, col=1)
    _chart_complexity(fig, row=2, col_comp=1, col_cfg=2)
    _draw_layout_graph(
        fig, par_result["layout_edges"], par_result["workstations"],
        row=3, col=1,
        title_note="Inv → every WS independently → QI  ·  no inter-WS dependencies",
    )
    _draw_layout_graph(
        fig, lin_result["layout_edges"], lin_result["workstations"],
        row=3, col=2,
        title_note="Inv → WS_1 → WS_2 → … → QI  ·  strictly serial",
    )
    _chart_table(fig, row=4, col=1)

    # ── Layout ────────────────────────────────────────────────────────────────
    fig.update_layout(
        paper_bgcolor=_BG,
        plot_bgcolor=_BG,
        font=dict(color=_TEXT, family="Inter, system-ui, sans-serif", size=12),
        height=1300,
        title=dict(
            text=(
                "Section 2 — Rafael model: what it does well and where it falls short"
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
        margin=dict(l=65, r=190, t=72, b=50),
    )

    fig.update_xaxes(**_AXIS_STYLE)
    fig.update_yaxes(**_AXIS_STYLE)

    # Per-axis labels
    fig.update_xaxes(title_text="BOM depth", dtick=1, row=2, col=1)
    fig.update_yaxes(title_text="Component count", row=2, col=1)
    fig.update_xaxes(title_text="BOM depth", dtick=1, row=2, col=2)
    fig.update_yaxes(title_text="Configuration count", row=2, col=2)

    # Subplot title font
    for ann in fig.layout.annotations:
        if ann.text and ann.text[:1] in "①②③":
            ann.update(font=dict(color=_TEXT, size=13))

    fig.show()


if __name__ == "__main__":
    show()
