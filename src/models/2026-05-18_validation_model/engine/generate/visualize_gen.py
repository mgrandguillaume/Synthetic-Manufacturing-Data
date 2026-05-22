    #!/usr/bin/env python3
"""
Factory layout visualizer — powered by Pyvis / vis.js.

Produces a self-contained HTML file with:
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

Usage
-----
  uv run src/models/2026-05-18_validation_model/generate/visualize_gen.py
  # writes gen_output/layout_graph.html and opens it in your browser

Dependencies
------------
  pip install pyvis
  (pandas and networkx are already required by generate.py)
"""

import json
import os
import webbrowser
from collections import defaultdict, deque

import networkx as nx
import pandas as pd
from pyvis.network import Network

# ── Paths ──────────────────────────────────────────────────────────────────────

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "gen_output")
OUT_HTML   = os.path.join(OUTPUT_DIR, "layout_graph.html")

# ── Load CSVs ─────────────────────────────────────────────────────────────────

layout_df = pd.read_csv(os.path.join(OUTPUT_DIR, "layout.csv"))
ws_df     = pd.read_csv(os.path.join(OUTPUT_DIR, "workstations.csv"))
cfg_df    = pd.read_csv(os.path.join(OUTPUT_DIR, "configurations.csv"))
bom_df    = pd.read_csv(os.path.join(OUTPUT_DIR, "bom.csv"))

# ── Lookup tables ─────────────────────────────────────────────────────────────

# ws_id -> [(component, processing_time, setup_time), ...]
ws_outputs: dict[str, list[tuple]] = defaultdict(list)
for _, row in cfg_df.iterrows():
    ws_outputs[row["Workstation"]].append(
        (row["Component"], row["ProcessingTime"], row["SetupTime"])
    )

# comp_id -> [input_component_id, ...]  (BOM: what inputs does this need?)
comp_inputs: dict[str, list[str]] = defaultdict(list)
for _, row in bom_df.iterrows():
    comp_inputs[row["Output"]].append(row["Input"])

# comp_id -> [workstation_id, ...]  (which stations produce this component?)
comp_producers: dict[str, list[str]] = defaultdict(list)
for _, row in cfg_df.iterrows():
    comp_producers[row["Component"]].append(row["Workstation"])
comp_producers["Inv"] = ["Inv"]   # raw materials come from the inventory node

# ── Build NetworkX graph ───────────────────────────────────────────────────────

G = nx.DiGraph()
for _, row in ws_df.iterrows():
    G.add_node(row["ID"], name=row["Name"], type=row["Type"])
for _, row in layout_df.iterrows():
    G.add_edge(
        row["Origin"], row["Destination"],
        capacity=row["Capacity"], cost=row["Cost"],
    )

# ── BFS stage assignment ───────────────────────────────────────────────────────
# Each node's stage = BFS distance from Inv.
# Nodes at the same stage share the same x-position.

stage_of: dict[str, int] = {"Inv": 0}
queue = deque(["Inv"])
while queue:
    node = queue.popleft()
    for succ in G.successors(node):
        if succ not in stage_of:
            stage_of[succ] = stage_of[node] + 1
            queue.append(succ)

nodes_at_stage: dict[int, list[str]] = defaultdict(list)
for node, s in stage_of.items():
    nodes_at_stage[s].append(node)

max_stage = max(stage_of.values())

# ── Compute vis.js pixel positions ────────────────────────────────────────────
# vis.js places (0, 0) at the canvas centre.
# Stages spread over [-X_HALF, +X_HALF]; nodes within a stage spread over
# [-Y_HALF, +Y_HALF].

X_HALF = 700
Y_HALF = 400

pos: dict[str, tuple[float, float]] = {}
for stage, nodes in nodes_at_stage.items():
    x = -X_HALF + (stage / max_stage) * 2 * X_HALF
    nodes_sorted = sorted(nodes)
    n = len(nodes_sorted)
    for i, node in enumerate(nodes_sorted):
        y = -Y_HALF + ((i + 1) / (n + 1)) * 2 * Y_HALF
        pos[node] = (x, y)

# ── Node colours by type ───────────────────────────────────────────────────────

NODE_COLORS: dict[str, dict] = {
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

# ── HTML tooltip builders ──────────────────────────────────────────────────────

def _build_node_tooltip(node: str, data: dict) -> str:
    """Return an HTML string for the node hover tooltip.

    When a workstation produces more than 2 components the produces list is
    rendered in a 2-column CSS grid so the tooltip stays on-screen.
    """
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

        # Wrap in a 2-column grid when there are many components.
        if two_cols:
            parts.append(
                "<div style='display:grid;grid-template-columns:1fr 1fr;"
                "gap:6px 16px;margin-top:5px'>"
            )

        for comp, pt, st in sorted_outputs:
            # Each component block sits in its own grid cell.
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
            parts.append("</div>")   # end component cell

        if two_cols:
            parts.append("</div>")   # end grid

    return "".join(parts)


def _build_edge_tooltip(u: str, v: str, capacity: float, cost: float) -> str:
    return (
        f"<b>{u} &rarr; {v}</b><br>"
        f"Capacity:&nbsp;{capacity}<br>"
        f"Cost:&nbsp;{cost:.2f}"
    )

# ── Build Pyvis network ────────────────────────────────────────────────────────

net = Network(
    height="920px",
    width="100%",
    directed=True,
    bgcolor="#0f1117",
    font_color="#e6edf3",
)
net.toggle_physics(False)   # keep nodes pinned at computed positions

# Collect tooltip HTML for injection later.
# Do NOT pass title= to add_node/add_edge — vis.js treats it as a plain HTML
# attribute which browsers render as unstyled raw text.
node_tooltips: dict[str, str] = {}
edge_tooltips: dict[str, str] = {}   # key: "u__v"

for node, data in G.nodes(data=True):
    x, y = pos[node]
    node_tooltips[node] = _build_node_tooltip(node, data)
    net.add_node(
        node,
        label=node,
        x=x, y=y,
        color=NODE_COLORS[data["type"]],
        size=28,
        font={"size": 13, "color": "#e6edf3",
              "face": "Inter, sans-serif", "bold": True},
        borderWidth=2,
        shape="dot",
    )

for u, v, data in G.edges(data=True):
    edge_key = f"{u}__{v}"
    edge_tooltips[edge_key] = _build_edge_tooltip(
        u, v, data["capacity"], data["cost"]
    )
    net.add_edge(
        u, v,
        color={"color": "rgba(150,150,170,0.55)", "highlight": "#a5b4fc",
               "hover": "#a5b4fc"},
        arrows="to",
        width=1.5,
        smooth={"type": "curvedCW", "roundness": 0.08},
    )

# ── Write base HTML ────────────────────────────────────────────────────────────

net.write_html(OUT_HTML)

# ── Post-process: inject custom tooltip JS ────────────────────────────────────
# We read the file pyvis just wrote, append our tooltip machinery, and save it.

with open(OUT_HTML, "r", encoding="utf-8") as fh:
    html = fh.read()

# vis.js only fires hoverNode / blurNode / hoverEdge / blurEdge when
# interaction.hover is explicitly true.  pyvis does not set this flag, so we
# patch it into the options block that pyvis already wrote.
html = html.replace(
    '"interaction": {',
    '"interaction": {"hover": true, ',
    1,   # replace only the first occurrence (the options literal)
)

# Serialise tooltip data so the JS can look them up by ID.
node_tooltips_js = json.dumps(node_tooltips, ensure_ascii=False)
edge_tooltips_js = json.dumps(edge_tooltips, ensure_ascii=False)

tooltip_injection = f"""
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
  var nodeTips = {node_tooltips_js};
  var edgeTips = {edge_tooltips_js};
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

  // Hook into the vis.js network object once it is ready.
  // pyvis sets `var network;` then assigns it inside drawGraph() which runs
  // immediately — so by the time this script block executes, `network` is set.
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
      // vis.js edge IDs are integers; build the string key from the edge data.
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

html = html.replace("</body>", tooltip_injection + "\n</body>")

with open(OUT_HTML, "w", encoding="utf-8") as fh:
    fh.write(html)

# ── Open in browser ───────────────────────────────────────────────────────────

print(f"[visualize_gen] Saved: {OUT_HTML}")
webbrowser.open(f"file:///{OUT_HTML.replace(os.sep, '/')}")
