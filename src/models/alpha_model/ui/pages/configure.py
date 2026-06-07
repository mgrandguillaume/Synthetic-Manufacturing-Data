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
               lo, hi, step=1, min_val=None, hint: str = None) -> html.Div:
    children = [
        html.Div([
            html.Div([_label(f"{label} — min"), _num(id_lo, lo, step=step, min_val=min_val)]),
            html.Div([_label(f"{label} — max"), _num(id_hi, hi, step=step, min_val=min_val)]),
        ], className="grid-2"),
    ]
    if hint:
        children.append(_hint(hint))
    return html.Div(children, className="form-group")


def _hint(text: str) -> html.Span:
    """Muted descriptive text rendered below an input field."""
    return html.Span(text, className="field-hint")


def _toggle_btn(id_: str) -> html.Button:
    return html.Button("? help", id=id_, className="btn-hint-toggle", n_clicks=0)


def _section(name: str, meta: str = "", action=None) -> html.Div:
    right = []
    if meta:
        right.append(html.Span(meta, className="meta"))
    if action:
        right.append(action)
    return html.Div([
        html.Span(name, className="h"),
        html.Div(right, style={"display": "flex", "alignItems": "center", "gap": "10px"}),
    ], className="af-section-head")


# ── Layout ─────────────────────────────────────────────────────────────────────

def layout():
    with open(store.CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    bom  = cfg.get("bom",          {})
    ws   = cfg.get("workstations", {})
    lay  = cfg.get("layout",       {})
    sim  = cfg.get("simulation",     {})
    fail = cfg.get("failures",       {})
    meta = cfg.get("metadata",       {})
    out  = cfg.get("output",         {})
    sw   = cfg.get("sweep",          {})

    return html.Div([
        html.Div("project · configure", className="af-eyebrow"),
        html.H1("Configure"),
        html.P(
            "Adjust factory structure, simulation settings, and sweep ranges. "
            "Changes take effect after clicking Save config.",
            className="page-caption",
        ),

        dcc.Tabs([
            # ── Tab 0: BOM ────────────────────────────────────────────────────
            dcc.Tab(label="bom", className="tab-item", selected_className="tab-item--selected",
                    children=html.Div([
                        _section("Bill of materials", meta="bom.*",
                                 action=_toggle_btn("bom-hints-toggle")),
                        html.Div([
                            html.Div([
                                html.Div([
                                    _label("Number of products"),
                                    _num("cfg-bom-n-products", int(bom.get("n_products", 1)), min_val=1),
                                    _hint("Distinct finished goods in the catalogue. Each gets its own BOM tree; raw components may be shared across trees."),
                                ], className="form-group"),
                                html.Div([
                                    _label("BOM depth"),
                                    _num("cfg-bom-depth", int(bom.get("depth", 2)), min_val=1),
                                    _hint("Assembly levels from raw material (level 0) to finished product. Higher depth means longer supply chains and more workstation stages."),
                                ], className="form-group"),
                            ], className="grid-2"),
                            _range_row("Branching",
                                       "cfg-bom-branch-lo", "cfg-bom-branch-hi",
                                       bom.get("branching", [2, 3])[0],
                                       bom.get("branching", [2, 3])[1], min_val=1,
                                       hint="Number of distinct sub-component types consumed at each assembly step. A value of 3 means an operation requires 3 different inputs."),
                            _range_row("Quantity per BOM edge",
                                       "cfg-bom-qty-lo", "cfg-bom-qty-hi",
                                       bom.get("quantity", [1, 1])[0],
                                       bom.get("quantity", [1, 1])[1], min_val=1,
                                       hint="Units of each sub-component consumed per assembly operation. Higher values increase buffer pressure and raise the minimum buffer_capacity required."),
                            html.Div([
                                _label("Sharing ratio"),
                                _num("cfg-bom-sharing", float(bom.get("sharing_ratio", 0.0)),
                                     step=0.05, min_val=0.0, max_val=1.0),
                                _hint("Probability that a new BOM node reuses an existing component from another product's tree. 0 = fully independent BOMs; 1 = maximum reuse across products."),
                            ], className="form-group"),
                        ], id="bom-body", className="af-section-body hints-hidden"),
                    ])),

            # ── Tab 1: Workstations ───────────────────────────────────────────
            dcc.Tab(label="workstations", className="tab-item", selected_className="tab-item--selected",
                    children=html.Div([
                        _section("Workstations", meta="workstations.*",
                                 action=_toggle_btn("ws-hints-toggle")),
                        html.Div([
                            html.Div([
                                _label("Assembly workstation count"),
                                _num("cfg-ws-count", int(ws.get("count", 4)), min_val=1),
                                _hint("Total number of assembly workstations. Must be ≥ BOM depth — each level in the supply chain needs at least one workstation."),
                            ], className="form-group"),
                            html.Label([
                                dcc.Checklist(
                                    id="cfg-ws-use-stage-balance",
                                    options=[{"label": "  Custom stage balance (Dirichlet)", "value": "yes"}],
                                    value=["yes"] if ws.get("stage_balance") is not None else [],
                                ),
                            ], className="toggle-row"),
                            html.Div([
                                _label("Stage balance"),
                                dcc.Input(id="cfg-ws-stage-balance", type="number",
                                          value=float(ws.get("stage_balance") or 1.0),
                                          step=0.5, min=0.0, debounce=True,
                                          style={"width": "100%"}),
                                _hint("Dirichlet concentration parameter controlling how workstations are spread across BOM levels. ≥ 5 = near-uniform; ≤ 0.5 = heavily skewed toward fewer levels."),
                            ], id="cfg-ws-stage-balance-wrap", className="form-group"),
                            html.Hr(className="divider"),
                            html.Div([
                                _label("Assembly type"),
                                dcc.Dropdown(
                                    id="cfg-assembly-type",
                                    options=["low", "medium", "high"],
                                    value=ws.get("assembly_type", "medium"),
                                    clearable=False,
                                ),
                                _hint("Sets the processing-time formula. 'low' = labour-intensive (longer times); 'medium' = standard; 'high' = automated (shorter times, steeper depth scaling)."),
                            ], className="form-group"),
                            html.Div([
                                _label("Variation"),
                                _num("cfg-variation", float(ws.get("variation", 0.10)),
                                     step=0.01, min_val=0.0, max_val=1.0),
                                _hint("Random spread applied around the assembly-type formula mean. 0.10 = ±10%. Controls how much processing times vary between workstations."),
                            ], className="form-group"),
                            _range_row("Producers per component",
                                       "cfg-prod-lo", "cfg-prod-hi",
                                       ws.get("producers_per_component", [1, 2])[0],
                                       ws.get("producers_per_component", [1, 2])[1], min_val=1,
                                       hint="How many workstations can produce each component type. More producers increase parallelism and reduce bottlenecks at busy BOM levels."),
                            html.Hr(className="divider"),
                            _range_row("Setup time (h)",
                                       "cfg-st-lo", "cfg-st-hi",
                                       ws.get("setup_time",     [0.5, 2.0])[0],
                                       ws.get("setup_time",     [0.5, 2.0])[1], step=0.1,
                                       hint="Hours a workstation spends on changeover before starting a new component type. High setup times penalise frequent task-switching."),
                            _range_row("Setup cost",
                                       "cfg-sc-lo", "cfg-sc-hi",
                                       ws.get("setup_cost",     [50,  300])[0],
                                       ws.get("setup_cost",     [50,  300])[1], step=10.0,
                                       hint="Cost incurred each time a workstation changes the component type it is producing."),
                            _range_row("Operating cost",
                                       "cfg-oc-lo", "cfg-oc-hi",
                                       ws.get("operating_cost", [2,   15])[0],
                                       ws.get("operating_cost", [2,   15])[1], step=0.5,
                                       hint="Cost per hour a workstation spends actively processing. Drives the trade-off between high utilisation and running cost."),
                        ], id="ws-body", className="af-section-body hints-hidden"),
                    ])),

            # ── Tab 2: Layout ─────────────────────────────────────────────────
            dcc.Tab(label="layout", className="tab-item", selected_className="tab-item--selected",
                    children=html.Div([
                        _section("Layout", meta="layout.*",
                                 action=_toggle_btn("lay-hints-toggle")),
                        html.Div([
                            _range_row("Flow capacity",
                                       "cfg-lay-cap-lo", "cfg-lay-cap-hi",
                                       lay.get("flow_capacity",  [50, 200])[0],
                                       lay.get("flow_capacity",  [50, 200])[1], step=5.0,
                                       hint="Maximum units per hour that can flow along a transport link between workstations. Low capacity creates transport bottlenecks."),
                            _range_row("Transport cost",
                                       "cfg-lay-cost-lo", "cfg-lay-cost-hi",
                                       lay.get("transport_cost", [0.5, 5.0])[0],
                                       lay.get("transport_cost", [0.5, 5.0])[1], step=0.1,
                                       hint="Cost per unit moved along a layout link. Higher values make routing decisions more consequential for total cost."),
                        ], id="lay-body", className="af-section-body hints-hidden"),
                    ])),

            # ── Tab 3: Simulation ─────────────────────────────────────────────
            dcc.Tab(label="simulation", className="tab-item", selected_className="tab-item--selected",
                    children=html.Div([
                        _section("Simulation", meta="simulation.*",
                                 action=_toggle_btn("sim-hints-toggle")),
                        html.Div([
                            html.Div([
                                html.Div([
                                    _label("Number of orders"),
                                    _num("cfg-sim-n-orders", int(sim.get("n_orders", 10)), min_val=1),
                                    _hint("Production orders released over the run. More orders give more stable throughput statistics but take longer to simulate."),
                                ], className="form-group"),
                                html.Div([
                                    _label("Max ticks"),
                                    _num("cfg-sim-n-ticks", int(sim.get("n_ticks", 3000)),
                                         step=100, min_val=100),
                                    _hint("Hard upper bound on simulation length. Increase if orders are not completing — especially for deep BOMs or low parallelism."),
                                ], className="form-group"),
                                html.Div([
                                    _label("Tick duration (h)"),
                                    _num("cfg-sim-tick", float(sim.get("tick_duration", 0.05)),
                                         step=0.01, min_val=0.0),
                                    _hint("Simulated hours per tick. Smaller values give finer time resolution but increase total run time proportionally."),
                                ], className="form-group"),
                                html.Div([
                                    _label("Buffer capacity"),
                                    _num("cfg-sim-buf", int(sim.get("buffer_capacity", 20)), min_val=1),
                                    _hint("Maximum units any intermediate component buffer may hold. Must be ≥ quantity max to avoid deadlock; should be ≥ branching × quantity for low blocking."),
                                ], className="form-group"),
                                html.Div([
                                    _label("Order interarrival (ticks)"),
                                    _num("cfg-sim-interarr", int(sim.get("order_interarrival", 10)), min_val=1),
                                    _hint("Ticks between successive order releases. Lower values stress the factory with overlapping orders; higher values give more slack between runs."),
                                ], className="form-group"),
                            ], className="grid-2"),
                        ], id="sim-body", className="af-section-body hints-hidden"),
                    ])),

            # ── Tab 4: Failures ───────────────────────────────────────────────
            dcc.Tab(label="failures", className="tab-item", selected_className="tab-item--selected",
                    children=html.Div([
                        _section("Machine failures (Weibull)", meta="failures.*",
                                 action=_toggle_btn("fail-hints-toggle")),
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
                                       fail.get("weibull_beta",   [1.5, 3.0])[1], step=0.1,
                                       hint="Weibull shape parameter. β < 1: early failures (infant mortality). β = 1: constant failure rate. β > 1: wear-out behaviour where older machines fail more often."),
                            _range_row("Weibull λ (scale, h)",
                                       "cfg-fail-lam-lo", "cfg-fail-lam-hi",
                                       fail.get("weibull_lambda", [20,  50])[0],
                                       fail.get("weibull_lambda", [20,  50])[1], step=1.0,
                                       hint="Characteristic life of a machine in hours. Higher values mean machines survive longer before failing. MTBF = λ · Γ(1 + 1/β)."),
                            _range_row("MTTR (h)",
                                       "cfg-fail-mttr-lo", "cfg-fail-mttr-hi",
                                       fail.get("mttr",           [0.5, 4.0])[0],
                                       fail.get("mttr",           [0.5, 4.0])[1], step=0.1,
                                       hint="Mean Time To Repair in hours, sampled per failure event. Together with MTBF, determines availability: A = MTBF / (MTBF + MTTR)."),
                            _range_row("Repair cost",
                                       "cfg-fail-rc-lo", "cfg-fail-rc-hi",
                                       fail.get("repair_cost",    [100, 500])[0],
                                       fail.get("repair_cost",    [100, 500])[1], step=10.0,
                                       hint="Cost charged per failure event, sampled from this range independently per workstation."),
                        ], id="fail-body", className="af-section-body hints-hidden"),
                    ])),

            # ── Tab 5: Sweep ──────────────────────────────────────────────────
            dcc.Tab(label="sweep", className="tab-item", selected_className="tab-item--selected",
                    children=html.Div([
                        _section("Sweep grid", meta="sweep.*",
                                 action=_toggle_btn("sweep-hints-toggle")),
                        html.Div([
                            html.Span(
                                "Each parameter can be a scalar (n_products: 5), "
                                "a list (depth: [1, 2, 3]), or a range dict (depth: {min: 1, max: 8, step: 1}). "
                                "Every combination of all sweep parameters is run. "
                                "Combinations where depth > workstations_count are automatically skipped.",
                                className="field-hint",
                                style={"marginBottom": "10px"},
                            ),
                            _label("Sweep parameters (YAML)"),
                            dcc.Textarea(
                                id="cfg-sweep-raw",
                                value=yaml.dump(sw, default_flow_style=False, sort_keys=True),
                                style={"width": "100%", "height": "200px",
                                       "fontFamily": "var(--af-mono)", "fontSize": "12px"},
                            ),
                        ], id="sweep-body", className="af-section-body hints-hidden"),
                    ])),

            # ── Tab 6: Metadata & Output ──────────────────────────────────────
            dcc.Tab(label="metadata · output", className="tab-item", selected_className="tab-item--selected",
                    children=html.Div([
                        _section("Metadata", meta="metadata.*",
                                 action=_toggle_btn("meta-hints-toggle")),
                        html.Div([
                            html.Div([
                                _label("Factory name"),
                                dcc.Input(id="cfg-meta-name", type="text",
                                          value=str(meta.get("name", "simple_assembly_factory")),
                                          debounce=True, style={"width": "100%"}),
                                _hint("Human-readable identifier for this configuration. Used in output file headers."),
                            ], className="form-group"),
                            html.Label([
                                dcc.Checklist(
                                    id="cfg-meta-use-seed",
                                    options=[{"label": "  Fixed seed (reproducible)", "value": "yes"}],
                                    value=["yes"] if meta.get("seed") is not None else [],
                                ),
                            ], className="toggle-row"),
                            html.Div([
                                _label("Seed value"),
                                _num("cfg-meta-seed", int(meta.get("seed") or 42), min_val=0),
                                _hint("Integer seed passed to Python's random module. Disable for a fresh random run each time."),
                            ], className="form-group"),
                        ], className="af-section-body hints-hidden", id="meta-body-metadata"),
                        _section("Output", meta="output.*"),
                        html.Div([
                            html.Div([
                                _label("Output directory (relative or absolute)"),
                                dcc.Input(id="cfg-out-dir", type="text",
                                          value=str(out.get("directory", "gen_output")),
                                          debounce=True, style={"width": "100%"}),
                                _hint("Where generated CSV files are written. Relative paths are resolved from the engine/generate/ directory."),
                            ], className="form-group"),
                        ], className="af-section-body hints-hidden", id="meta-body-output"),
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

def _hint_toggle(n, body_id_on="af-section-body", body_id_off="af-section-body hints-hidden"):
    """Return (body_className, button_label) based on click parity."""
    if n and n % 2 == 1:
        return body_id_on, "hide help"
    return body_id_off, "? help"


@callback(
    Output("bom-body",         "className"),
    Output("bom-hints-toggle", "children"),
    Input("bom-hints-toggle",  "n_clicks"),
)
def _toggle_bom(n):
    return _hint_toggle(n)


@callback(
    Output("ws-body",         "className"),
    Output("ws-hints-toggle", "children"),
    Input("ws-hints-toggle",  "n_clicks"),
)
def _toggle_ws(n):
    return _hint_toggle(n)


@callback(
    Output("lay-body",         "className"),
    Output("lay-hints-toggle", "children"),
    Input("lay-hints-toggle",  "n_clicks"),
)
def _toggle_lay(n):
    return _hint_toggle(n)


@callback(
    Output("sim-body",         "className"),
    Output("sim-hints-toggle", "children"),
    Input("sim-hints-toggle",  "n_clicks"),
)
def _toggle_sim(n):
    return _hint_toggle(n)


@callback(
    Output("fail-body",         "className"),
    Output("fail-hints-toggle", "children"),
    Input("fail-hints-toggle",  "n_clicks"),
)
def _toggle_fail(n):
    return _hint_toggle(n)


@callback(
    Output("sweep-body",         "className"),
    Output("sweep-hints-toggle", "children"),
    Input("sweep-hints-toggle",  "n_clicks"),
)
def _toggle_sweep(n):
    return _hint_toggle(n)


@callback(
    Output("meta-body-metadata",  "className"),
    Output("meta-body-output",    "className"),
    Output("meta-hints-toggle",   "children"),
    Input("meta-hints-toggle",    "n_clicks"),
)
def _toggle_meta(n):
    body_cls, label = _hint_toggle(n)
    return body_cls, body_cls, label


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
                "count":                   int(ws_cnt or 4),
                "stage_balance":           float(sb_val or 1.0) if use_sb else None,
                "producers_per_component": [int(prod_lo or 1), int(prod_hi or 2)],
                "assembly_type":           asm_type or "medium",
                "variation":               float(variation or 0.10),
                "setup_time":              [float(st_lo or 0.5),  float(st_hi or 2.0)],
                "setup_cost":              [float(sc_lo or 50),   float(sc_hi or 300)],
                "operating_cost":          [float(oc_lo or 2),    float(oc_hi or 15)],
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

        # ── Validate before writing ────────────────────────────────────────────
        from shared_utils import validate_config
        validate_warnings = []
        try:
            validate_warnings = validate_config.validate(new_cfg) or []
        except validate_config.ConfigError as ce:
            error_items = [html.Li(e) for e in ce.errors]
            warn_items  = [html.Li(w) for w in ce.warnings]
            children = [
                html.Div(
                    [html.Strong(f"{len(ce.errors)} configuration error(s) — config not saved:"),
                     html.Ul(error_items, style={"marginTop": "6px", "paddingLeft": "18px"})],
                    className="alert alert-error",
                ),
            ]
            if warn_items:
                children.append(html.Div(
                    [html.Strong("Warnings:"), html.Ul(warn_items, style={"marginTop": "6px", "paddingLeft": "18px"})],
                    className="alert alert-warning",
                ))
            return html.Div(children)

        # ── Write config ───────────────────────────────────────────────────────
        with open(store.CONFIG_PATH, "w") as f:
            yaml.dump(new_cfg, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False)

        # Clear the Simulate page's cached form values so the next visit reads
        # the updated config instead of the stale last-run parameters.
        store.set("sim_params", None)

        # Return success + any soft warnings.
        children = [html.Div("Config saved.", className="alert alert-success")]
        if validate_warnings:
            warn_items = [html.Li(w) for w in validate_warnings]
            children.append(html.Div(
                [html.Strong(f"{len(validate_warnings)} warning(s):"),
                 html.Ul(warn_items, style={"marginTop": "6px", "paddingLeft": "18px"})],
                className="alert alert-warning",
            ))
        return html.Div(children)

    except Exception as exc:
        return html.Div(f"Failed to save: {exc}", className="alert alert-error")
