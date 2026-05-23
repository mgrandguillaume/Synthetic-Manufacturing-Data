"""Configure page — read and write config.yaml through the UI."""

import yaml
import dash
from dash import html, dcc, Input, Output, State, callback, ctx
import store

dash.register_page(__name__, path="/configure", title="Configure")

# ── Helpers ────────────────────────────────────────────────────────────────────

def _label(text: str) -> html.Span:
    return html.Span(text, className="widget-label")


def _num(id_: str, value, step=1, min_val=None, max_val=None, fmt=None) -> dcc.Input:
    kw = dict(id=id_, type="number", value=value, step=step,
              debounce=True, style={"width": "100%"})
    if min_val is not None: kw["min"] = min_val
    if max_val is not None: kw["max"] = max_val
    return dcc.Input(**kw)


def _range_row(label: str, id_lo: str, id_hi: str,
               lo, hi, step=1, min_val=None) -> html.Div:
    return html.Div([
        html.Div([
            html.Div([_label(f"{label} — min"), _num(id_lo, lo, step=step, min_val=min_val)],
                     className="form-group"),
            html.Div([_label(f"{label} — max"), _num(id_hi, hi, step=step, min_val=min_val)],
                     className="form-group"),
        ], className="grid-2"),
    ])


def _section(name: str, meta: str = "") -> html.Div:
    meta_el = html.Span(meta, className="meta") if meta else html.Span()
    return html.Div([
        html.Div([html.Span(name, className="h"), meta_el],
                 className="af-section-head"),
    ])


# ── Layout ─────────────────────────────────────────────────────────────────────

def layout():
    with open(store.CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    bom  = cfg.get("bom",            {})
    ws   = cfg.get("workstations",   {})
    cc   = cfg.get("configurations", {})
    lay  = cfg.get("layout",         {})
    sim  = cfg.get("simulation",     {})
    fail = cfg.get("failures",       {})
    meta = cfg.get("metadata",       {})
    out  = cfg.get("output",         {})
    sw   = cfg.get("sweep",          {})

    return html.Div([
        html.Div("project · configure", className="af-eyebrow"),
        html.H1("Configure"),
        html.P(
            f"Editing: {store.CONFIG_PATH}  —  inline comments are stripped on save (PyYAML limitation).",
            className="page-caption",
        ),

        dcc.Tabs([
            # ── Tab 0: BOM ────────────────────────────────────────────────────
            dcc.Tab(label="bom", className="tab-item", selected_className="tab-item--selected",
                    children=html.Div([
                        _section("Bill of materials", meta="bom.*"),
                        html.Div([
                            html.Div([
                                html.Div([_label("Number of products"),
                                          _num("cfg-bom-n-products", int(bom.get("n_products", 1)), min_val=1)],
                                         className="form-group"),
                                html.Div([_label("BOM depth"),
                                          _num("cfg-bom-depth", int(bom.get("depth", 2)), min_val=1)],
                                         className="form-group"),
                            ], className="grid-2"),
                            _range_row("Branching (children per node)",
                                       "cfg-bom-branch-lo", "cfg-bom-branch-hi",
                                       bom.get("branching", [2, 3])[0],
                                       bom.get("branching", [2, 3])[1], min_val=1),
                            _range_row("Quantity per BOM edge",
                                       "cfg-bom-qty-lo", "cfg-bom-qty-hi",
                                       bom.get("quantity", [1, 1])[0],
                                       bom.get("quantity", [1, 1])[1], min_val=1),
                            html.Div([
                                _label("Sharing ratio  (0 = no sharing, 1 = always reuse)"),
                                _num("cfg-bom-sharing", float(bom.get("sharing_ratio", 0.0)),
                                     step=0.05, min_val=0.0, max_val=1.0),
                            ], className="form-group"),
                        ], className="af-section-body"),
                    ])),

            # ── Tab 1: Workstations ───────────────────────────────────────────
            dcc.Tab(label="workstations", className="tab-item", selected_className="tab-item--selected",
                    children=html.Div([
                        _section("Workstations", meta="workstations.*"),
                        html.Div([
                            html.Div([_label("Assembly workstation count"),
                                      _num("cfg-ws-count", int(ws.get("count", 4)), min_val=1)],
                                     className="form-group"),
                            html.Label([
                                dcc.Checklist(
                                    id="cfg-ws-use-stage-balance",
                                    options=[{"label": "  Custom stage balance (Dirichlet)", "value": "yes"}],
                                    value=["yes"] if ws.get("stage_balance") is not None else [],
                                ),
                            ], className="toggle-row"),
                            html.Div([
                                _label("Stage balance  (null = uniform; high ≥ 5 = near-uniform; low ≤ 0.5 = skewed)"),
                                dcc.Input(id="cfg-ws-stage-balance", type="number",
                                          value=float(ws.get("stage_balance") or 1.0),
                                          step=0.5, min=0.01, debounce=True,
                                          style={"width": "100%"}),
                            ], id="cfg-ws-stage-balance-wrap", className="form-group"),
                        ], className="af-section-body"),
                    ])),

            # ── Tab 2: Configurations ─────────────────────────────────────────
            dcc.Tab(label="configurations", className="tab-item", selected_className="tab-item--selected",
                    children=html.Div([
                        _section("Configurations", meta="configurations.*"),
                        html.Div([
                            html.Div([
                                _label("Assembly type  (sets processing-time formula)"),
                                dcc.Dropdown(
                                    id="cfg-assembly-type",
                                    options=["low", "medium", "high"],
                                    value=cc.get("assembly_type", "medium"),
                                    clearable=False,
                                ),
                            ], className="form-group"),
                            html.Div([
                                _label("Variation  (±fraction around formula mean)"),
                                _num("cfg-variation", float(cc.get("variation", 0.10)),
                                     step=0.01, min_val=0.0, max_val=1.0),
                            ], className="form-group"),
                            _range_row("Producers per component",
                                       "cfg-prod-lo", "cfg-prod-hi",
                                       cc.get("producers_per_component", [1, 2])[0],
                                       cc.get("producers_per_component", [1, 2])[1], min_val=1),
                            html.Hr(className="divider"),
                            _range_row("Setup time (h)",
                                       "cfg-st-lo", "cfg-st-hi",
                                       cc.get("setup_time",     [0.5, 2.0])[0],
                                       cc.get("setup_time",     [0.5, 2.0])[1], step=0.1),
                            _range_row("Setup cost",
                                       "cfg-sc-lo", "cfg-sc-hi",
                                       cc.get("setup_cost",     [50,  300])[0],
                                       cc.get("setup_cost",     [50,  300])[1], step=10.0),
                            _range_row("Operating cost",
                                       "cfg-oc-lo", "cfg-oc-hi",
                                       cc.get("operating_cost", [2,   15])[0],
                                       cc.get("operating_cost", [2,   15])[1], step=0.5),
                        ], className="af-section-body"),
                    ])),

            # ── Tab 3: Layout ─────────────────────────────────────────────────
            dcc.Tab(label="layout", className="tab-item", selected_className="tab-item--selected",
                    children=html.Div([
                        _section("Layout", meta="layout.*"),
                        html.Div([
                            _range_row("Flow capacity",
                                       "cfg-lay-cap-lo", "cfg-lay-cap-hi",
                                       lay.get("flow_capacity",  [50, 200])[0],
                                       lay.get("flow_capacity",  [50, 200])[1], step=5.0),
                            _range_row("Transport cost",
                                       "cfg-lay-cost-lo", "cfg-lay-cost-hi",
                                       lay.get("transport_cost", [0.5, 5.0])[0],
                                       lay.get("transport_cost", [0.5, 5.0])[1], step=0.1),
                        ], className="af-section-body"),
                    ])),

            # ── Tab 4: Simulation ─────────────────────────────────────────────
            dcc.Tab(label="simulation", className="tab-item", selected_className="tab-item--selected",
                    children=html.Div([
                        _section("Simulation", meta="simulation.*"),
                        html.Div([
                            html.Div([
                                html.Div([_label("Number of orders"),
                                          _num("cfg-sim-n-orders", int(sim.get("n_orders", 10)), min_val=1)],
                                         className="form-group"),
                                html.Div([_label("Max ticks"),
                                          _num("cfg-sim-n-ticks", int(sim.get("n_ticks", 3000)),
                                               step=100, min_val=100)],
                                         className="form-group"),
                                html.Div([_label("Tick duration (h)"),
                                          _num("cfg-sim-tick", float(sim.get("tick_duration", 0.05)),
                                               step=0.01, min_val=0.001)],
                                         className="form-group"),
                                html.Div([_label("Buffer capacity"),
                                          _num("cfg-sim-buf", int(sim.get("buffer_capacity", 20)), min_val=1)],
                                         className="form-group"),
                                html.Div([_label("Order interarrival (ticks)"),
                                          _num("cfg-sim-interarr", int(sim.get("order_interarrival", 10)), min_val=1)],
                                         className="form-group"),
                            ], className="grid-2"),
                        ], className="af-section-body"),
                    ])),

            # ── Tab 5: Failures ───────────────────────────────────────────────
            dcc.Tab(label="failures", className="tab-item", selected_className="tab-item--selected",
                    children=html.Div([
                        _section("Machine failures (Weibull)", meta="failures.*"),
                        html.Div([
                            html.Label([
                                dcc.Checklist(
                                    id="cfg-fail-enabled",
                                    options=[{"label": "  Enable machine failures", "value": "yes"}],
                                    value=["yes"] if fail.get("enabled", False) else [],
                                ),
                            ], className="toggle-row"),
                            html.Hr(className="divider"),
                            _range_row("Weibull β (shape)",
                                       "cfg-fail-beta-lo", "cfg-fail-beta-hi",
                                       fail.get("weibull_beta",   [1.5, 3.0])[0],
                                       fail.get("weibull_beta",   [1.5, 3.0])[1], step=0.1),
                            _range_row("Weibull λ (scale, h)",
                                       "cfg-fail-lam-lo", "cfg-fail-lam-hi",
                                       fail.get("weibull_lambda", [20,  50])[0],
                                       fail.get("weibull_lambda", [20,  50])[1], step=1.0),
                            _range_row("MTTR (h)",
                                       "cfg-fail-mttr-lo", "cfg-fail-mttr-hi",
                                       fail.get("mttr",           [0.5, 4.0])[0],
                                       fail.get("mttr",           [0.5, 4.0])[1], step=0.1),
                            _range_row("Repair cost",
                                       "cfg-fail-rc-lo", "cfg-fail-rc-hi",
                                       fail.get("repair_cost",    [100, 500])[0],
                                       fail.get("repair_cost",    [100, 500])[1], step=10.0),
                        ], className="af-section-body"),
                    ])),

            # ── Tab 6: Sweep ──────────────────────────────────────────────────
            dcc.Tab(label="sweep", className="tab-item", selected_className="tab-item--selected",
                    children=html.Div([
                        _section("Sweep grid", meta="sweep.*"),
                        html.Div([
                            html.P(
                                "Each parameter can be scalar (n_products: 5), "
                                "list (depth: [1, 2, 3]), or "
                                "range (depth: {min: 1, max: 8, step: 1}).",
                                style={"fontSize": "13px", "marginBottom": "10px"},
                            ),
                            _label("Sweep parameters (YAML)"),
                            dcc.Textarea(
                                id="cfg-sweep-raw",
                                value=yaml.dump(sw, default_flow_style=False, sort_keys=True),
                                style={"width": "100%", "height": "200px",
                                       "fontFamily": "var(--af-mono)", "fontSize": "12px"},
                            ),
                        ], className="af-section-body"),
                    ])),

            # ── Tab 7: Metadata & Output ──────────────────────────────────────
            dcc.Tab(label="metadata · output", className="tab-item", selected_className="tab-item--selected",
                    children=html.Div([
                        _section("Metadata", meta="metadata.*"),
                        html.Div([
                            html.Div([_label("Factory name"),
                                      dcc.Input(id="cfg-meta-name", type="text",
                                                value=str(meta.get("name", "simple_assembly_factory")),
                                                debounce=True, style={"width": "100%"})],
                                     className="form-group"),
                            html.Label([
                                dcc.Checklist(
                                    id="cfg-meta-use-seed",
                                    options=[{"label": "  Fixed seed (reproducible)", "value": "yes"}],
                                    value=["yes"] if meta.get("seed") is not None else [],
                                ),
                            ], className="toggle-row"),
                            html.Div([_label("Seed value"),
                                      _num("cfg-meta-seed", int(meta.get("seed") or 42), min_val=0)],
                                     className="form-group"),
                        ], className="af-section-body"),
                        _section("Output", meta="output.*"),
                        html.Div([
                            html.Div([_label("Output directory (relative or absolute)"),
                                      dcc.Input(id="cfg-out-dir", type="text",
                                                value=str(out.get("directory", "gen_output")),
                                                debounce=True, style={"width": "100%"})],
                                     className="form-group"),
                        ], className="af-section-body"),
                    ])),

        ], className="tab-list-container",
           content_className="tab-content"),

        # ── Save button ────────────────────────────────────────────────────────
        html.Hr(className="divider"),
        html.Button("Save config", id="cfg-save-btn", n_clicks=0,
                    className="btn btn-primary btn-full"),
        html.Div(id="cfg-save-status", style={"marginTop": "10px"}),
    ])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("cfg-ws-stage-balance-wrap", "style"),
    Input("cfg-ws-use-stage-balance", "value"),
)
def _toggle_stage_balance(value):
    return {} if value else {"opacity": "0.4", "pointerEvents": "none"}


@callback(
    Output("cfg-save-status", "children"),
    Input("cfg-save-btn", "n_clicks"),
    # ── BOM ────────────────────────────────────────────────────────────────────
    State("cfg-bom-n-products",   "value"),
    State("cfg-bom-depth",        "value"),
    State("cfg-bom-branch-lo",    "value"),
    State("cfg-bom-branch-hi",    "value"),
    State("cfg-bom-qty-lo",       "value"),
    State("cfg-bom-qty-hi",       "value"),
    State("cfg-bom-sharing",      "value"),
    # ── Workstations ──────────────────────────────────────────────────────────
    State("cfg-ws-count",              "value"),
    State("cfg-ws-use-stage-balance",  "value"),
    State("cfg-ws-stage-balance",      "value"),
    # ── Configurations ────────────────────────────────────────────────────────
    State("cfg-assembly-type", "value"),
    State("cfg-variation",     "value"),
    State("cfg-prod-lo",       "value"),
    State("cfg-prod-hi",       "value"),
    State("cfg-st-lo",         "value"),
    State("cfg-st-hi",         "value"),
    State("cfg-sc-lo",         "value"),
    State("cfg-sc-hi",         "value"),
    State("cfg-oc-lo",         "value"),
    State("cfg-oc-hi",         "value"),
    # ── Layout ────────────────────────────────────────────────────────────────
    State("cfg-lay-cap-lo",    "value"),
    State("cfg-lay-cap-hi",    "value"),
    State("cfg-lay-cost-lo",   "value"),
    State("cfg-lay-cost-hi",   "value"),
    # ── Simulation ────────────────────────────────────────────────────────────
    State("cfg-sim-n-orders",  "value"),
    State("cfg-sim-n-ticks",   "value"),
    State("cfg-sim-tick",      "value"),
    State("cfg-sim-buf",       "value"),
    State("cfg-sim-interarr",  "value"),
    # ── Failures ──────────────────────────────────────────────────────────────
    State("cfg-fail-enabled",  "value"),
    State("cfg-fail-beta-lo",  "value"),
    State("cfg-fail-beta-hi",  "value"),
    State("cfg-fail-lam-lo",   "value"),
    State("cfg-fail-lam-hi",   "value"),
    State("cfg-fail-mttr-lo",  "value"),
    State("cfg-fail-mttr-hi",  "value"),
    State("cfg-fail-rc-lo",    "value"),
    State("cfg-fail-rc-hi",    "value"),
    # ── Sweep ─────────────────────────────────────────────────────────────────
    State("cfg-sweep-raw",     "value"),
    # ── Metadata / Output ─────────────────────────────────────────────────────
    State("cfg-meta-name",     "value"),
    State("cfg-meta-use-seed", "value"),
    State("cfg-meta-seed",     "value"),
    State("cfg-out-dir",       "value"),
    prevent_initial_call=True,
)
def _save_config(n_clicks,
                 bom_n, bom_d, br_lo, br_hi, qty_lo, qty_hi, sharing,
                 ws_cnt, use_sb, sb_val,
                 asm_type, variation, prod_lo, prod_hi,
                 st_lo, st_hi, sc_lo, sc_hi, oc_lo, oc_hi,
                 cap_lo, cap_hi, cost_lo, cost_hi,
                 sim_n, sim_ticks, sim_tick, sim_buf, sim_ia,
                 fail_en, beta_lo, beta_hi, lam_lo, lam_hi,
                 mttr_lo, mttr_hi, rc_lo, rc_hi,
                 sweep_raw,
                 meta_name, use_seed, seed_val,
                 out_dir):
    try:
        sweep_parsed = yaml.safe_load(sweep_raw or "{}")
        if not isinstance(sweep_parsed, dict):
            return html.Div("Sweep section must be a YAML mapping.", className="alert alert-error")

        new_cfg = {
            "metadata": {
                "name": meta_name or "simple_assembly_factory",
                "seed": int(seed_val) if use_seed else None,
            },
            "bom": {
                "n_products":    int(bom_n  or 1),
                "depth":         int(bom_d  or 2),
                "branching":     [int(br_lo  or 2), int(br_hi  or 3)],
                "quantity":      [int(qty_lo or 1), int(qty_hi or 1)],
                "sharing_ratio": float(sharing or 0.0),
            },
            "workstations": {
                "count":         int(ws_cnt or 4),
                "stage_balance": float(sb_val or 1.0) if use_sb else None,
            },
            "configurations": {
                "producers_per_component": [int(prod_lo or 1), int(prod_hi or 2)],
                "assembly_type": asm_type or "medium",
                "variation":     float(variation or 0.10),
                "setup_time":    [float(st_lo or 0.5),  float(st_hi or 2.0)],
                "setup_cost":    [float(sc_lo or 50),   float(sc_hi or 300)],
                "operating_cost":[float(oc_lo or 2),    float(oc_hi or 15)],
            },
            "layout": {
                "flow_capacity":  [float(cap_lo  or 50),  float(cap_hi  or 200)],
                "transport_cost": [float(cost_lo or 0.5), float(cost_hi or 5.0)],
            },
            "simulation": {
                "tick_duration":      float(sim_tick or 0.05),
                "buffer_capacity":    int(sim_buf   or 20),
                "order_interarrival": int(sim_ia    or 10),
                "n_ticks":            int(sim_ticks or 3000),
                "n_orders":           int(sim_n     or 10),
            },
            "failures": {
                "enabled":        bool(fail_en),
                "weibull_beta":   [float(beta_lo or 1.5), float(beta_hi or 3.0)],
                "weibull_lambda": [float(lam_lo  or 20),  float(lam_hi  or 50)],
                "mttr":           [float(mttr_lo  or 0.5),float(mttr_hi  or 4.0)],
                "repair_cost":    [float(rc_lo   or 100), float(rc_hi   or 500)],
            },
            "sweep":  sweep_parsed,
            "output": {"directory": out_dir or "gen_output"},
        }

        with open(store.CONFIG_PATH, "w") as f:
            yaml.dump(new_cfg, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False)

        return html.Div("Config saved.", className="alert alert-success")

    except Exception as exc:
        return html.Div(f"Failed to save: {exc}", className="alert alert-error")
