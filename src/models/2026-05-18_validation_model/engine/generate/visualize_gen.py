#!/usr/bin/env python3
"""
Factory layout visualizer — powered by Pyvis / vis.js.

Produces a self-contained HTML string (or file) with:
  • One node per workstation (Inv source, assembly stations, QI sink)
  • Directed edges from the layout graph
  • Rich per-node HTML tooltip showing configurations, processing times,
    setup times, and BOM input requirements per component
  • Edge tooltip showing transport capacity and cost

How tooltips work
-----------------
vis.js treats the node `title` field as a plain HTML attribute on the canvas
wrapper, which browsers render as raw text rather than styled HTML.  To get
proper rendered HTML popups we instead post-process the generated HTML and
inject a small JavaScript block that:
  1. Stores all tooltip HTML in a JS dictionary keyed by node/edge ID.
  2. Listens to vis.js `hoverNode` / `blurNode` / `hoverEdge` / `blurEdge`
     events on the `network` object.
  3. Positions a custom <div> near the cursor and sets its innerHTML.

Public API
----------
  build_html(gen_result: dict) -> str
      Build and return the full HTML string from a gen_result dict as
      returned by generate_simple_assembly / generate_from_params.
      Does not touch the filesystem.

Standalone usage
----------------
  uv run src/models/2026-05-18_validation_model/engine/generate/visualize_gen.py
  # writes gen_output/layout_graph.html and opens it in your browser

Dependencies
------------
  pip install pyvis
  (pandas and networkx are already required by generate.py)
"""

import json
import os
import tempfile
import webbrowser
from collections import defaultdict, deque

import networkx as nx
from pyvis.network import Network

# ── Node colours by type ───────────────────────────────────────────────────────

_NODE_COLORS: dict[str, dict] = {
    "source": {
        "background": "#4ade80", "border": "#16a34a",
        "highlight": {"background": "#86efac", "border": "#16a34a"},
        "hover":     {"background": "#86efac", "border": "#16a34a"},
    },
    "production": {
        "background": "#60a5fa", "border": "#2563eb",
        "highlight": {"background": "#93c5fd", "border": "#2563eb"},
        "hover":     {"background": "#93c5fd", "border": "#2563eb"},
    },
    "sink": {
        "background": "#f87171", "border": "#dc2626",
        "highlight": {"background": "#fca5a5", "border": "#dc2626"},
        "hover":     {"background": "#fca5a5", "border": "#dc2626"},
    },
}

_TOOLTIP_JS = """
<!-- ── Custom tooltip injection ───────────────────────────────────────── -->
<style>
  #vt {{
    position: fixed;
    pointer-events: none;
    background: #1e2130;
    color: #e6edf3;
    padding: 10px 14px;
    border-radius: 6px;
    border: 1px solid #3a3f55;
    font-family: Inter, sans-serif;
    font-size: 13px;
    max-width: 640px;
    z-index: 9999;
    display: none;
    box-shadow: 0 4px 24px rgba(0,0,0,0.6);
    line-height: 1.5;
  }}
</style>
<div id="vt"></div>
<script>
(function () {{
  var nodeTips = {node_tips};
  var edgeTips = {edge_tips};
  var tip = document.getElementById('vt');
  var mx = 0, my = 0;

  document.addEventListener('mousemove', function (e) {{
    mx = e.clientX;
    my = e.clientY;
    if (tip.style.display === 'block') _place();
  }});

  function _place() {{
    var x = mx + 16, y = my - 10;
    if (x + tip.offsetWidth + 16 > window.innerWidth)  x = mx - tip.offsetWidth - 16;
    if (y + tip.offsetHeight > window.innerHeight) y = my - tip.offsetHeight - 10;
    tip.style.left = x + 'px';
    tip.style.top  = y + 'px';
  }}

  function _show(html) {{
    tip.innerHTML = html;
    tip.style.display = 'block';
    _place();
  }}

  function _hide() {{
    tip.style.display = 'none';
  }}

  function _attach() {{
    if (typeof network === 'undefined' || network === null) {{
      setTimeout(_attach, 50);
      return;
    }}
    network.on('hoverNode', function (p) {{
      if (nodeTips[p.node]) _show(nodeTips[p.node]);
    }});
    network.on('blurNode',  _hide);
    network.on('hoverEdge', function (p) {{
      var e = network.body.data.edges.get(p.edge);
      if (!e) return;
      var key = e.from + '__' + e.to;
      if (edgeTips[key]) _show(edgeTips[key]);
    }});
    network.on('blurEdge',  _hide);
  }}
  _attach();
}})();
</script>
<!-- ──────────────────────────────────────────────────────────────────── -->
"""


# ── Public API ─────────────────────────────────────────────────────────────────

def build_html(gen_result: dict, height: str = "600px") -> str:
    """Return a self-contained vis.js HTML string for the factory layout.

    Parameters
    ----------
    gen_result : dict
        As returned by generate_simple_assembly / generate_from_params.
        Must contain keys: workstations, layout_edges, configurations, bom_edges.
    height : str
        CSS height of the canvas, e.g. "600px" or "100vh".
    """
    ws_list   = gen_result["workstations"]
    edges     = gen_result["layout_edges"]
    cfgs      = gen_result["configurations"]
    bom_edges = gen_result["bom_edges"]

    # ── Build lookup tables ───────────────────────────────────────────────────
    # ws_id -> [(component, processing_time, setup_time), ...]
    ws_outputs: dict[str, list] = defaultdict(list)
    for c in cfgs:
        ws_outputs[c.workstation].append((c.component, c.processing_time, c.setup_time))

    # comp_id -> [input_comp_id, ...]
    comp_inputs: dict[str, list] = defaultdict(list)
    for e in bom_edges:
        comp_inputs[e.output].append(e.input)

    # comp_id -> [workstation_id, ...]
    comp_producers: dict[str, list] = defaultdict(list)
    for c in cfgs:
        comp_producers[c.component].append(c.workstation)

    # ── Build NetworkX graph ──────────────────────────────────────────────────
    G = nx.DiGraph()
    for w in ws_list:
        G.add_node(w.id, name=w.name, type=w.type)
    for e in edges:
        G.add_edge(e.origin, e.destination, capacity=e.capacity, cost=e.cost)

    # ── BFS stage assignment from source nodes ────────────────────────────────
    sources = [w.id for w in ws_list if w.type == "source"]
    stage_of: dict[str, int] = {s: 0 for s in sources}
    queue = deque(sources)
    while queue:
        node = queue.popleft()
        for succ in G.successors(node):
            if succ not in stage_of:
                stage_of[succ] = stage_of[node] + 1
                queue.append(succ)
    # Fallback for isolated nodes
    max_s = max(stage_of.values()) if stage_of else 0
    for w in ws_list:
        if w.id not in stage_of:
            stage_of[w.id] = max_s + 1

    nodes_at_stage: dict[int, list] = defaultdict(list)
    for node, s in stage_of.items():
        nodes_at_stage[s].append(node)

    max_stage = max(stage_of.values()) if stage_of else 1

    # ── vis.js pixel positions ────────────────────────────────────────────────
    X_HALF, Y_HALF = 700, 400
    pos: dict[str, tuple] = {}
    for s, nodes in nodes_at_stage.items():
        x = -X_HALF + (s / max_stage) * 2 * X_HALF
        nodes_sorted = sorted(nodes)
        n = len(nodes_sorted)
        for i, node in enumerate(nodes_sorted):
            y = -Y_HALF + ((i + 1) / (n + 1)) * 2 * Y_HALF
            pos[node] = (x, y)

    # ── Tooltip builders ──────────────────────────────────────────────────────
    def _node_tip(node: str, data: dict) -> str:
        stage = stage_of.get(node, "?")
        parts = [
            f"<b style='font-size:15px'>{node}</b><br>",
            f"<span style='color:#8b949e'>{data['name']}</span><br>",
            f"<span style='color:#8b949e'>Stage:&nbsp;{stage}</span>",
        ]
        outputs = ws_outputs.get(node)
        if outputs:
            sorted_outputs = sorted(outputs, key=lambda r: r[0])
            two_cols = len(sorted_outputs) > 2
            parts.append(
                "<hr style='border:none;border-top:1px solid #3a3f55;margin:7px 0'>"
                "<b>Produces:</b>"
            )
            if two_cols:
                parts.append(
                    "<div style='display:grid;grid-template-columns:1fr 1fr;"
                    "gap:6px 16px;margin-top:5px'>"
                )
            for comp, pt, st in sorted_outputs:
                margin = "margin:0" if two_cols else "margin:5px 0 2px 8px"
                parts.append(f"<div style='{margin}'>")
                parts.append(
                    f"&#9654;&nbsp;<b>{comp}</b>"
                    f"<span style='color:#8b949e;margin-left:8px'>"
                    f"PT&nbsp;{pt:.2f}h&nbsp;&nbsp;|&nbsp;&nbsp;ST&nbsp;{st:.2f}h"
                    f"</span>"
                )
                inputs_needed = sorted(set(comp_inputs.get(comp, [])))
                if inputs_needed:
                    parts.append(
                        "<div style='margin-left:14px;color:#8b949e;font-size:12px'>"
                        "<i>needs:</i></div>"
                    )
                    for inp in inputs_needed:
                        suppliers = ", ".join(sorted(comp_producers.get(inp, ["?"])))
                        parts.append(
                            f"<div style='margin-left:20px;font-size:12px'>"
                            f"&#9666;&nbsp;{inp}&nbsp;"
                            f"<span style='color:#6b7280'>({suppliers})</span>"
                            f"</div>"
                        )
                parts.append("</div>")
            if two_cols:
                parts.append("</div>")
        return "".join(parts)

    def _edge_tip(u: str, v: str, capacity: float, cost: float) -> str:
        return (
            f"<b>{u} &rarr; {v}</b><br>"
            f"Capacity:&nbsp;{capacity}<br>"
            f"Cost:&nbsp;{cost:.2f}"
        )

    # ── Build Pyvis network ───────────────────────────────────────────────────
    net = Network(
        height=height,
        width="100%",
        directed=True,
        bgcolor="#0f1117",
        font_color="#e6edf3",
        cdn_resources="in_line",   # embed JS/CSS in the HTML — no lib/ folder written
    )
    net.toggle_physics(False)

    node_tooltips: dict[str, str] = {}
    edge_tooltips: dict[str, str] = {}

    for node, data in G.nodes(data=True):
        x, y = pos.get(node, (0, 0))
        node_tooltips[node] = _node_tip(node, data)
        net.add_node(
            node,
            label=node,
            x=x, y=y,
            color=_NODE_COLORS.get(data["type"], _NODE_COLORS["production"]),
            size=28,
            font={"size": 13, "color": "#e6edf3",
                  "face": "Inter, sans-serif", "bold": True},
            borderWidth=2,
            shape="dot",
        )

    for u, v, data in G.edges(data=True):
        edge_key = f"{u}__{v}"
        edge_tooltips[edge_key] = _edge_tip(u, v, data["capacity"], data["cost"])
        net.add_edge(
            u, v,
            color={"color": "rgba(150,150,170,0.55)", "highlight": "#a5b4fc",
                   "hover": "#a5b4fc"},
            arrows="to",
            width=1.5,
            smooth={"type": "curvedCW", "roundness": 0.08},
        )

    # ── Write to temp file, read back, post-process ───────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w",
                                     encoding="utf-8") as tmp:
        tmp_path = tmp.name
    net.write_html(tmp_path)
    with open(tmp_path, "r", encoding="utf-8") as fh:
        html = fh.read()
    os.unlink(tmp_path)

    # Enable vis.js hover events (pyvis doesn't set this flag by default)
    html = html.replace(
        '"interaction": {',
        '"interaction": {"hover": true, ',
        1,
    )

    # Inject custom tooltip JS
    injection = _TOOLTIP_JS.format(
        node_tips=json.dumps(node_tooltips, ensure_ascii=False),
        edge_tips=json.dumps(edge_tooltips, ensure_ascii=False),
    )
    html = html.replace("</body>", injection + "\n</body>")

    return html


# ── Standalone entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import pandas as pd
    from types import SimpleNamespace

    OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "gen_output")
    OUT_HTML   = os.path.join(OUTPUT_DIR, "layout_graph.html")

    layout_df = pd.read_csv(os.path.join(OUTPUT_DIR, "layout.csv"))
    ws_df     = pd.read_csv(os.path.join(OUTPUT_DIR, "workstations.csv"))
    cfg_df    = pd.read_csv(os.path.join(OUTPUT_DIR, "configurations.csv"))
    bom_df    = pd.read_csv(os.path.join(OUTPUT_DIR, "bom.csv"))

    # Build a gen_result-compatible dict from the CSVs
    gen_result = {
        "workstations": [
            SimpleNamespace(id=row["ID"], name=row["Name"], type=row["Type"])
            for _, row in ws_df.iterrows()
        ],
        "layout_edges": [
            SimpleNamespace(origin=row["Origin"], destination=row["Destination"],
                            capacity=row["Capacity"], cost=row["Cost"])
            for _, row in layout_df.iterrows()
        ],
        "configurations": [
            SimpleNamespace(workstation=row["Workstation"], component=row["Component"],
                            processing_time=row["ProcessingTime"], setup_time=row["SetupTime"])
            for _, row in cfg_df.iterrows()
        ],
        "bom_edges": [
            SimpleNamespace(input=row["Input"], output=row["Output"])
            for _, row in bom_df.iterrows()
        ],
    }

    html = build_html(gen_result, height="920px")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"[visualize_gen] Saved: {OUT_HTML}")
    webbrowser.open(f"file:///{OUT_HTML.replace(os.sep, '/')}")
