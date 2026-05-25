"""Generate page — build a factory and inspect the result."""

import os
import time
import yaml
import dash
from dash import html, dcc, Input, Output, State, callback, dash_table
import store

# The vis.js HTML is large and contains non-ASCII bytes that break Dash's
# cp1252 JSON response pipeline on Windows.  Write it as a UTF-8 file in
# assets/ and load via iframe src URL instead of srcDoc.
_ASSETS_DIR        = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
_LAYOUT_HTML_PATH  = os.path.join(_ASSETS_DIR, "factory_layout.html")
_LAYOUT_HTML_URL   = "/assets/factory_layout.html"


def _write_layout_html(result) -> None:
    """Write the vis.js factory layout HTML to assets/factory_layout.html."""
    from engine.generate.visualize_gen import build_html
    html_str = build_html(result, height="600px")
    os.makedirs(_ASSETS_DIR, exist_ok=True)
    with open(_LAYOUT_HTML_PATH, "w", encoding="utf-8") as fh:
        fh.write(html_str)


def _layout_iframe() -> html.Iframe:
    """Return an Iframe pointing at the pre-written layout HTML asset."""
    # Cache-busting query param so the browser reloads after each generation.
    t = int(time.time())
    return html.Iframe(
        src=f"{_LAYOUT_HTML_URL}?t={t}",
        style={"width": "100%", "height": "620px",
               "border": "1px solid #d9d9d4", "borderRadius": "2px"},
    )

dash.register_page(__name__, path="/generate", title="Generate")

# ── Helpers ────────────────────────────────────────────────────────────────────

def _label(text): return html.Span(text, className="widget-label")

def _num(id_, value, step=1, min_val=None, max_val=None):
    kw = dict(id=id_, type="number", value=value, step=step,
              debounce=True, style={"width": "100%"})
    if min_val is not None: kw["min"] = min_val
    if max_val is not None: kw["max"] = max_val
    return dcc.Input(**kw)

def _metric(label, value):
    return html.Div([
        html.Div(label, className="metric-label"),
        html.Div(str(value), className="metric-value"),
    ], className="metric-card")

_TABLE_STYLE_CELL = dict(
    fontFamily="JetBrains Mono, monospace", fontSize="12px",
    padding="6px 10px", border="1px solid #d9d9d4", textAlign="left",
)
_TABLE_STYLE_HEADER = dict(
    fontFamily="JetBrains Mono, monospace", fontSize="11px",
    textTransform="uppercase", letterSpacing="0.06em",
    color="#6a6a6a", background="#f7f7f5", fontWeight="500",
    border="1px solid #d9d9d4",
)


def _render_results(result) -> list:
    """Return layout children for the results section, or an info banner."""
    if result is None:
        return [html.Div("Click Generate factory to build a factory.",
                         className="alert alert-info")]

    comps  = result["components"]
    edges  = result["bom_edges"]
    ws_    = result["workstations"]
    cfgs   = result["configurations"]

    _write_layout_html(result)   # write UTF-8 file to assets/

    return [
        html.Hr(className="divider"),

        # Metrics
        html.H2("Summary"),
        html.Div([
            _metric("Components",     len(comps)),
            _metric("BOM edges",      len(edges)),
            _metric("Workstations",   len(ws_)),
            _metric("Configurations", len(cfgs)),
            _metric("Layout edges",   len(result["layout_edges"])),
        ], className="metric-row"),

        # Data tabs
        dcc.Tabs([
            dcc.Tab(label="components", className="tab-item",
                    selected_className="tab-item--selected",
                    children=dash_table.DataTable(
                        data=[{"ID": c.id, "Name": c.name,
                               "Level": c.level, "IsProduct": c.is_product}
                              for c in comps],
                        columns=[{"name": n, "id": n}
                                 for n in ["ID","Name","Level","IsProduct"]],
                        style_table={"height": "380px", "overflowY": "auto"},
                        style_cell=_TABLE_STYLE_CELL,
                        style_header=_TABLE_STYLE_HEADER,
                    )),
            dcc.Tab(label="configurations", className="tab-item",
                    selected_className="tab-item--selected",
                    children=dash_table.DataTable(
                        data=[{"ID": c.id, "WS": c.workstation, "Comp": c.component,
                               "PT": round(c.processing_time, 4),
                               "ST": round(c.setup_time, 4),
                               "SC": round(c.setup_cost, 2),
                               "OC": round(c.operating_cost, 2)}
                              for c in cfgs],
                        columns=[{"name": n, "id": n}
                                 for n in ["ID","WS","Comp","PT","ST","SC","OC"]],
                        style_table={"height": "380px", "overflowY": "auto"},
                        style_cell=_TABLE_STYLE_CELL,
                        style_header=_TABLE_STYLE_HEADER,
                    )),
            dcc.Tab(label="bom edges", className="tab-item",
                    selected_className="tab-item--selected",
                    children=dash_table.DataTable(
                        data=[{"Input": e.input, "Output": e.output, "Qty": e.quantity}
                              for e in edges],
                        columns=[{"name": n, "id": n} for n in ["Input","Output","Qty"]],
                        style_table={"height": "380px", "overflowY": "auto"},
                        style_cell=_TABLE_STYLE_CELL,
                        style_header=_TABLE_STYLE_HEADER,
                    )),
            dcc.Tab(label="workstations", className="tab-item",
                    selected_className="tab-item--selected",
                    children=dash_table.DataTable(
                        data=[{"ID": w.id, "Name": w.name, "Type": w.type}
                              for w in ws_],
                        columns=[{"name": n, "id": n} for n in ["ID","Name","Type"]],
                        style_table={"height": "380px", "overflowY": "auto"},
                        style_cell=_TABLE_STYLE_CELL,
                        style_header=_TABLE_STYLE_HEADER,
                    )),
        ], className="tab-list-container", content_className="tab-content"),

        # Factory layout — written to assets/ to avoid Dash's JSON/cp1252 pipeline
        html.Hr(className="divider"),
        html.H2("Factory layout"),
        _layout_iframe(),
    ]


# ── Layout ─────────────────────────────────────────────────────────────────────

def layout():
    with open(store.CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    bom  = cfg.get("bom",          {})
    ws   = cfg.get("workstations", {})
    cc   = cfg.get("workstations", {})
    lay  = cfg.get("layout",       {})
    meta = cfg.get("metadata",       {})

    return html.Div([
        html.Div("engine · generate", className="af-eyebrow"),
        html.H1("Generate factory"),
        html.P("Build a factory structure from config.yaml or custom values.",
               className="page-caption"),

        # Source toggle
        html.Label([
            dcc.Checklist(
                id="gen-use-config",
                options=[{"label": "  Use config.yaml values", "value": "yes"}],
                value=["yes"],
            ),
        ], className="toggle-row"),

        # Custom params (hidden by default)
        html.Div(id="gen-custom-params", children=[
            html.Div([
                html.Div([
                    html.Div([
                        html.B("BOM", style={"fontSize": "13px"}),
                        html.Div([_label("Products"),
                                  _num("gen-n-products", int(bom.get("n_products", 1)), min_val=1)],
                                 className="form-group"),
                        html.Div([_label("Depth"),
                                  _num("gen-depth", int(bom.get("depth", 2)), min_val=1)],
                                 className="form-group"),
                        html.Div([_label("Branching min"),
                                  _num("gen-branch-lo", int(bom.get("branching",[2,3])[0]), min_val=1)],
                                 className="form-group"),
                        html.Div([_label("Branching max"),
                                  _num("gen-branch-hi", int(bom.get("branching",[2,3])[1]), min_val=1)],
                                 className="form-group"),
                        html.Div([_label("Qty min"),
                                  _num("gen-qty-lo", int(bom.get("quantity",[1,1])[0]), min_val=1)],
                                 className="form-group"),
                        html.Div([_label("Qty max"),
                                  _num("gen-qty-hi", int(bom.get("quantity",[1,1])[1]), min_val=1)],
                                 className="form-group"),
                        html.Div([_label("Sharing ratio"),
                                  _num("gen-sharing", float(bom.get("sharing_ratio", 0.0)),
                                       step=0.05, min_val=0.0, max_val=1.0)],
                                 className="form-group"),
                    ]),
                    html.Div([
                        html.B("Workstations & Configurations", style={"fontSize": "13px"}),
                        html.Div([_label("Workstation count"),
                                  _num("gen-n-ws", int(ws.get("count", 4)), min_val=1)],
                                 className="form-group"),
                        html.Div([_label("Producers / comp min"),
                                  _num("gen-prod-lo", int(cc.get("producers_per_component",[1,2])[0]), min_val=1)],
                                 className="form-group"),
                        html.Div([_label("Producers / comp max"),
                                  _num("gen-prod-hi", int(cc.get("producers_per_component",[1,2])[1]), min_val=1)],
                                 className="form-group"),
                        html.Div([_label("Assembly type"),
                                  dcc.Dropdown(id="gen-assembly-type",
                                               options=["low","medium","high"],
                                               value=cc.get("assembly_type","medium"),
                                               clearable=False)],
                                 className="form-group"),
                        html.Div([_label("Variation (±)"),
                                  _num("gen-variation", float(cc.get("variation", 0.10)),
                                       step=0.01, min_val=0.0, max_val=1.0)],
                                 className="form-group"),
                        html.Div([_label("Seed (0 = random)"),
                                  _num("gen-seed", int(meta.get("seed") or 0), min_val=0)],
                                 className="form-group"),
                    ]),
                ], className="grid-2"),

                details := html.Details([
                    html.Summary("Cost & layout ranges"),
                    html.Div([
                        html.Div([
                            html.Div([_label("Setup time min (h)"),
                                      _num("gen-st-lo", float(cc.get("setup_time",[0.5,2.0])[0]), step=0.1)],
                                     className="form-group"),
                            html.Div([_label("Setup time max (h)"),
                                      _num("gen-st-hi", float(cc.get("setup_time",[0.5,2.0])[1]), step=0.1)],
                                     className="form-group"),
                            html.Div([_label("Setup cost min"),
                                      _num("gen-sc-lo", float(cc.get("setup_cost",[50,300])[0]), step=10.0)],
                                     className="form-group"),
                            html.Div([_label("Setup cost max"),
                                      _num("gen-sc-hi", float(cc.get("setup_cost",[50,300])[1]), step=10.0)],
                                     className="form-group"),
                            html.Div([_label("Operating cost min"),
                                      _num("gen-oc-lo", float(cc.get("operating_cost",[2,15])[0]), step=0.5)],
                                     className="form-group"),
                            html.Div([_label("Operating cost max"),
                                      _num("gen-oc-hi", float(cc.get("operating_cost",[2,15])[1]), step=0.5)],
                                     className="form-group"),
                        ], className="grid-2"),
                        html.Div([
                            html.Div([_label("Flow capacity min"),
                                      _num("gen-cap-lo", float(lay.get("flow_capacity",[50,200])[0]), step=10.0)],
                                     className="form-group"),
                            html.Div([_label("Flow capacity max"),
                                      _num("gen-cap-hi", float(lay.get("flow_capacity",[50,200])[1]), step=10.0)],
                                     className="form-group"),
                            html.Div([_label("Transport cost min"),
                                      _num("gen-cost-lo", float(lay.get("transport_cost",[0.5,5.0])[0]), step=0.1)],
                                     className="form-group"),
                            html.Div([_label("Transport cost max"),
                                      _num("gen-cost-hi", float(lay.get("transport_cost",[0.5,5.0])[1]), step=0.1)],
                                     className="form-group"),
                        ], className="grid-2"),
                    ], className="exp-body"),
                ]),
            ], style={"background": "var(--af-paper-2)", "border": "1px solid var(--af-rule)",
                      "borderRadius": "2px", "padding": "14px", "marginTop": "10px"}),
        ], style={"display": "none"}),

        # Active config summary (shown when using config)
        html.Div(id="gen-config-summary", children=[
            html.Details([
                html.Summary("Active config.yaml parameters"),
                html.Div([
                    html.Pre(
                        "\n".join([
                            f"n_products:    {bom.get('n_products')}",
                            f"depth:         {bom.get('depth')}",
                            f"branching:     {bom.get('branching')}",
                            f"quantity:      {bom.get('quantity')}",
                            f"sharing_ratio: {bom.get('sharing_ratio')}",
                            f"ws_count:      {ws.get('count')}",
                            f"assembly_type: {cc.get('assembly_type')}",
                            f"variation:     {cc.get('variation')}",
                            f"seed:          {meta.get('seed')}",
                        ])
                    ),
                ], className="exp-body"),
            ], style={"marginTop": "8px"}),
        ]),

        # Generate button
        html.Hr(className="divider"),
        html.Button("Generate factory", id="gen-btn", n_clicks=0,
                    className="btn btn-primary btn-full"),
        html.Div(id="gen-status", style={"marginTop": "10px"}),

        # Results (populated by callback; pre-filled on page load from store)
        dcc.Loading(
            html.Div(id="gen-results", children=_render_results(store.get("gen_result"))),
            type="circle",
        ),
    ])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("gen-custom-params",   "style"),
    Output("gen-config-summary",  "style"),
    Input("gen-use-config",       "value"),
)
def _toggle_mode(use_config):
    if use_config:
        return {"display": "none"}, {}
    return {}, {"display": "none"}


@callback(
    Output("gen-results", "children"),
    Output("gen-status",  "children"),
    Input("gen-btn", "n_clicks"),
    State("gen-use-config",   "value"),
    # Custom params
    State("gen-n-products",   "value"),
    State("gen-depth",        "value"),
    State("gen-branch-lo",    "value"),
    State("gen-branch-hi",    "value"),
    State("gen-qty-lo",       "value"),
    State("gen-qty-hi",       "value"),
    State("gen-sharing",      "value"),
    State("gen-n-ws",         "value"),
    State("gen-prod-lo",      "value"),
    State("gen-prod-hi",      "value"),
    State("gen-assembly-type","value"),
    State("gen-variation",    "value"),
    State("gen-seed",         "value"),
    State("gen-st-lo",        "value"),
    State("gen-st-hi",        "value"),
    State("gen-sc-lo",        "value"),
    State("gen-sc-hi",        "value"),
    State("gen-oc-lo",        "value"),
    State("gen-oc-hi",        "value"),
    State("gen-cap-lo",       "value"),
    State("gen-cap-hi",       "value"),
    State("gen-cost-lo",      "value"),
    State("gen-cost-hi",      "value"),
    prevent_initial_call=True,
)
def _run_generate(n_clicks, use_config,
                  n_products, depth, br_lo, br_hi, qty_lo, qty_hi, sharing,
                  n_ws, prod_lo, prod_hi, asm_type, variation, seed_val,
                  st_lo, st_hi, sc_lo, sc_hi, oc_lo, oc_hi,
                  cap_lo, cap_hi, cost_lo, cost_hi):
    from engine.generate.generate import generate_simple_assembly, generate_from_params
    from engine.generate.factory   import pt_range

    try:
        if use_config:
            result = generate_simple_assembly(store.CONFIG_PATH, export_csv=True)
        else:
            params = {
                "n_products":              int(n_products  or 1),
                "depth":                   int(depth       or 2),
                "branching":               [int(br_lo  or 2), int(br_hi  or 3)],
                "quantity":                [int(qty_lo or 1), int(qty_hi or 1)],
                "sharing_ratio":           float(sharing   or 0.0),
                "workstations_count":      int(n_ws        or 4),
                "producers_per_component": [int(prod_lo or 1), int(prod_hi or 2)],
                "processing_time":         pt_range(asm_type or "medium",
                                                    int(depth or 2),
                                                    float(variation or 0.10)),
                "setup_time":              [float(st_lo  or 0.5),  float(st_hi  or 2.0)],
                "setup_cost":              [float(sc_lo  or 50),   float(sc_hi  or 300)],
                "operating_cost":          [float(oc_lo  or 2),    float(oc_hi  or 15)],
                "flow_capacity":           [float(cap_lo or 50),   float(cap_hi or 200)],
                "transport_cost":          [float(cost_lo or 0.5), float(cost_hi or 5.0)],
                "seed":                    int(seed_val) if seed_val else None,
            }
            result = generate_from_params(params, export_csv=False)

        store.set("gen_result", result)
        return _render_results(result), html.Div("Factory generated.", className="alert alert-success")

    except Exception as exc:
        return dash.no_update, html.Div(f"Error: {exc}", className="alert alert-error")
