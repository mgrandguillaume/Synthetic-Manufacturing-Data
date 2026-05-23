"""Simulate page — run a discrete-time simulation on the generated factory."""

import yaml
import dash
from dash import html, dcc, Input, Output, State, callback
import store

dash.register_page(__name__, path="/simulate", title="Simulate")

# ── Helpers ────────────────────────────────────────────────────────────────────

def _label(text): return html.Span(text, className="widget-label")

def _num(id_, value, step=1, min_val=None, fmt=None):
    kw = dict(id=id_, type="number", value=value, step=step,
              debounce=True, style={"width": "100%"})
    if min_val is not None: kw["min"] = min_val
    return dcc.Input(**kw)

def _metric(label, value):
    return html.Div([
        html.Div(label, className="metric-label"),
        html.Div(str(value), className="metric-value"),
    ], className="metric-card")


def _render_results(results) -> list:
    if results is None:
        return [html.Div("Click Run simulation to start.", className="alert alert-info")]

    from shared_utils import theme
    import plotly.graph_objects as go

    tp   = results["throughput"]
    util = results["utilization"]

    STATE_COLS  = ["BusyPct","SetupPct","BlockedPct","StarvedPct","IdlePct","FailedPct"]
    STATE_NAMES = ["Processing","Setup","Blocked","Starved","Idle","Failed"]
    STATE_KEYS  = ["processing","setup","blocked","starved","idle","failed"]

    # Utilisation chart
    fig_u = go.Figure()
    for col, name, key in zip(STATE_COLS, STATE_NAMES, STATE_KEYS):
        fig_u.add_trace(go.Bar(
            x=util["Workstation"], y=util[col], name=name,
            marker_color=theme.STATE_COLORS.get(key, theme.palette(STATE_KEYS.index(key))),
        ))
    fig_u.update_layout(
        barmode="stack", height=420,
        paper_bgcolor=theme.BG, plot_bgcolor=theme.BG,
        font=dict(color=theme.TEXT, family="IBM Plex Sans, system-ui, sans-serif"),
        legend=dict(bgcolor=theme.SURFACE, bordercolor=theme.BORDER, borderwidth=1,
                    font=dict(color=theme.SUBTEXT)),
        xaxis_title="Workstation", yaxis_title="Time (%)",
        margin=dict(l=50, r=20, t=30, b=40),
    )
    theme.apply_axis_style(fig_u)

    # Throughput chart
    if not tp.empty:
        times  = [0.0] + tp["Time"].tolist()
        counts = list(range(len(times)))
        fig_tp = go.Figure(go.Scatter(
            x=times, y=counts, mode="lines",
            line=dict(shape="hv", color=theme.palette(0), width=2),
            hovertemplate="Time: %{x:.2f} h<br>Orders: %{y}<extra></extra>",
        ))
        fig_tp.update_layout(
            height=350, paper_bgcolor=theme.BG, plot_bgcolor=theme.BG,
            font=dict(color=theme.TEXT, family="IBM Plex Sans, system-ui, sans-serif"),
            xaxis_title="Simulation time (h)", yaxis_title="Cumulative orders",
            margin=dict(l=50, r=20, t=30, b=40),
        )
        theme.apply_axis_style(fig_tp)
        tp_tab_content = [
            dcc.Graph(figure=fig_tp),
            dash.dash_table.DataTable(
                data=tp.to_dict("records"),
                columns=[{"name": c, "id": c} for c in tp.columns],
                style_table={"overflowX": "auto"},
                style_cell=dict(fontFamily="JetBrains Mono, monospace",
                                fontSize="12px", padding="5px 9px",
                                border="1px solid #d9d9d4"),
                style_header=dict(background="#f7f7f5", fontWeight="500",
                                  border="1px solid #d9d9d4",
                                  color="#6a6a6a", fontSize="11px"),
            ),
        ]
    else:
        tp_tab_content = [html.Div("No orders completed.", className="alert alert-warning")]

    # Costs chart
    costs = results["costs"].copy()
    costs["TotalCost"] = (costs["SetupCost"] + costs["OperatingCost"]
                          + costs["TransportCost"] + costs["RepairCost"])
    cost_cols = ["SetupCost","OperatingCost","TransportCost","RepairCost"]
    fig_c = go.Figure()
    for i, col in enumerate(cost_cols):
        fig_c.add_trace(go.Bar(
            x=costs["Workstation"], y=costs[col],
            name=col.replace("Cost",""), marker_color=theme.palette(i),
        ))
    fig_c.update_layout(
        barmode="stack", height=380,
        paper_bgcolor=theme.BG, plot_bgcolor=theme.BG,
        font=dict(color=theme.TEXT, family="IBM Plex Sans, system-ui, sans-serif"),
        xaxis_title="Workstation", yaxis_title="Cost",
        legend=dict(bgcolor=theme.SURFACE, bordercolor=theme.BORDER, borderwidth=1,
                    font=dict(color=theme.SUBTEXT)),
        margin=dict(l=50, r=20, t=30, b=40),
    )
    theme.apply_axis_style(fig_c)

    # Buffers chart
    buf_df = results["buffers"]
    if not buf_df.empty:
        fig_b = go.Figure()
        for i, comp in enumerate(buf_df["Component"].unique()):
            sub = buf_df[buf_df["Component"] == comp].sort_values("Time")
            fig_b.add_trace(go.Scatter(
                x=sub["Time"], y=sub["Stock"], mode="lines",
                name=str(comp), line=dict(color=theme.palette(i), width=1),
                hovertemplate=f"{comp}<br>Time: %{{x:.2f}} h<br>Stock: %{{y}}<extra></extra>",
            ))
        fig_b.update_layout(
            height=420, paper_bgcolor=theme.BG, plot_bgcolor=theme.BG,
            font=dict(color=theme.TEXT, family="IBM Plex Sans, system-ui, sans-serif"),
            xaxis_title="Simulation time (h)", yaxis_title="Stock (units)",
            legend=dict(bgcolor=theme.SURFACE, bordercolor=theme.BORDER, borderwidth=1,
                        font=dict(color=theme.SUBTEXT, size=9)),
            margin=dict(l=50, r=20, t=30, b=40),
        )
        theme.apply_axis_style(fig_b)
        buf_content = [dcc.Graph(figure=fig_b)]
    else:
        buf_content = [html.Div(
            "Buffer logging was disabled. Re-run with Log buffer levels enabled.",
            className="alert alert-info",
        )]

    return [
        html.Hr(className="divider"),
        html.H2("Results"),
        html.Div([
            _metric("Orders completed",   len(tp)),
            _metric("Total time (h)",     f"{tp['Time'].max():.2f}"   if not tp.empty else "—"),
            _metric("Mean lead time (h)", f"{tp['LeadTime'].mean():.2f}" if not tp.empty else "—"),
            _metric("Mean busy %",        f"{util['BusyPct'].mean():.1f}%"),
        ], className="metric-row"),

        dcc.Tabs([
            dcc.Tab(label="utilization",  className="tab-item", selected_className="tab-item--selected",
                    children=[dcc.Graph(figure=fig_u)]),
            dcc.Tab(label="throughput",   className="tab-item", selected_className="tab-item--selected",
                    children=tp_tab_content),
            dcc.Tab(label="costs",        className="tab-item", selected_className="tab-item--selected",
                    children=[dcc.Graph(figure=fig_c)]),
            dcc.Tab(label="buffers",      className="tab-item", selected_className="tab-item--selected",
                    children=buf_content),
        ], className="tab-list-container", content_className="tab-content"),
    ]


# ── Layout ─────────────────────────────────────────────────────────────────────

def layout():
    with open(store.CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    sim  = cfg.get("simulation", {})
    fail = cfg.get("failures",   {})

    # Prerequisite check
    if store.get("gen_result") is None:
        prereq = html.Div(
            "Run Generate first to create a factory.",
            className="alert alert-warning",
        )
    else:
        prereq = None

    return html.Div([
        html.Div("engine · simulate", className="af-eyebrow"),
        html.H1("Simulate"),
        html.P("Discrete-time simulation run on the generated factory.",
               className="page-caption"),

        prereq or html.Span(),

        # Parameters
        html.H2("Parameters"),
        html.Div([
            html.Div([_label("Orders"),
                      _num("sim-n-orders", int(sim.get("n_orders",10)), min_val=1)],
                     className="form-group"),
            html.Div([_label("Max ticks"),
                      _num("sim-n-ticks", int(sim.get("n_ticks",3000)), step=100, min_val=100)],
                     className="form-group"),
            html.Div([_label("Tick duration (h)"),
                      _num("sim-tick", float(sim.get("tick_duration",0.05)), step=0.01, min_val=0.001)],
                     className="form-group"),
            html.Div([_label("Buffer capacity"),
                      _num("sim-buf", int(sim.get("buffer_capacity",20)), min_val=1)],
                     className="form-group"),
            html.Div([_label("Interarrival (ticks)"),
                      _num("sim-interarr", int(sim.get("order_interarrival",10)), min_val=1)],
                     className="form-group"),
            html.Div([_label("Log buffer levels"),
                      dcc.Checklist(id="sim-log-buffers",
                                    options=[{"label": " enabled", "value": "yes"}],
                                    value=["yes"])],
                     className="form-group"),
        ], className="grid-3"),

        html.Hr(className="divider"),
        html.Label([
            dcc.Checklist(id="sim-fail-enabled",
                          options=[{"label": "  Enable machine failures", "value": "yes"}],
                          value=["yes"] if fail.get("enabled", False) else []),
        ], className="toggle-row"),

        html.Div(id="sim-fail-params", children=[
            html.Div([
                html.Div([_label("Weibull β min"),
                          _num("sim-beta-lo", float(fail.get("weibull_beta",[1.5,3.0])[0]), step=0.1)],
                         className="form-group"),
                html.Div([_label("Weibull β max"),
                          _num("sim-beta-hi", float(fail.get("weibull_beta",[1.5,3.0])[1]), step=0.1)],
                         className="form-group"),
                html.Div([_label("Weibull λ min (h)"),
                          _num("sim-lam-lo", float(fail.get("weibull_lambda",[20,50])[0]), step=1.0)],
                         className="form-group"),
                html.Div([_label("Weibull λ max (h)"),
                          _num("sim-lam-hi", float(fail.get("weibull_lambda",[20,50])[1]), step=1.0)],
                         className="form-group"),
                html.Div([_label("MTTR min (h)"),
                          _num("sim-mttr-lo", float(fail.get("mttr",[0.5,4.0])[0]), step=0.1)],
                         className="form-group"),
                html.Div([_label("MTTR max (h)"),
                          _num("sim-mttr-hi", float(fail.get("mttr",[0.5,4.0])[1]), step=0.1)],
                         className="form-group"),
                html.Div([_label("Repair cost min"),
                          _num("sim-rc-lo", float(fail.get("repair_cost",[100,500])[0]), step=10.0)],
                         className="form-group"),
                html.Div([_label("Repair cost max"),
                          _num("sim-rc-hi", float(fail.get("repair_cost",[100,500])[1]), step=10.0)],
                         className="form-group"),
            ], className="grid-2"),
        ], style={"display": "none"}),

        html.Hr(className="divider"),
        html.Button("Run simulation", id="sim-btn", n_clicks=0,
                    className="btn btn-primary btn-full"),
        html.Div(id="sim-status", style={"marginTop": "10px"}),

        dcc.Loading(
            html.Div(id="sim-results", children=_render_results(store.get("sim_result"))),
            type="circle",
        ),
    ])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("sim-fail-params", "style"),
    Input("sim-fail-enabled", "value"),
)
def _toggle_fail(value):
    return {} if value else {"display": "none"}


@callback(
    Output("sim-results", "children"),
    Output("sim-status",  "children"),
    Input("sim-btn", "n_clicks"),
    State("sim-n-orders",    "value"),
    State("sim-n-ticks",     "value"),
    State("sim-tick",        "value"),
    State("sim-buf",         "value"),
    State("sim-interarr",    "value"),
    State("sim-log-buffers", "value"),
    State("sim-fail-enabled","value"),
    State("sim-beta-lo",     "value"),
    State("sim-beta-hi",     "value"),
    State("sim-lam-lo",      "value"),
    State("sim-lam-hi",      "value"),
    State("sim-mttr-lo",     "value"),
    State("sim-mttr-hi",     "value"),
    State("sim-rc-lo",       "value"),
    State("sim-rc-hi",       "value"),
    prevent_initial_call=True,
)
def _run_sim(n_clicks,
             n_orders, n_ticks, tick, buf, interarr, log_buf,
             fail_en, beta_lo, beta_hi, lam_lo, lam_hi,
             mttr_lo, mttr_hi, rc_lo, rc_hi):
    gen_result = store.get("gen_result")
    if gen_result is None:
        return dash.no_update, html.Div(
            "Generate a factory first.", className="alert alert-warning")

    from engine.simulate.simulate import simulate
    import yaml

    with open(store.CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    seed = cfg.get("metadata", {}).get("seed")

    try:
        results = simulate(
            gen_result,
            n_orders             = int(n_orders   or 10),
            tick_duration        = float(tick      or 0.05),
            buffer_capacity      = int(buf         or 20),
            order_interarrival   = int(interarr    or 10),
            n_ticks              = int(n_ticks     or 3000),
            log_buffers          = bool(log_buf),
            failures_enabled     = bool(fail_en),
            weibull_beta_range   = [float(beta_lo or 1.5), float(beta_hi or 3.0)],
            weibull_lambda_range = [float(lam_lo  or 20),  float(lam_hi  or 50)],
            mttr_range           = [float(mttr_lo or 0.5), float(mttr_hi or 4.0)],
            repair_cost_range    = [float(rc_lo   or 100), float(rc_hi   or 500)],
            seed                 = seed,
        )
        store.set("sim_result", results)
        return _render_results(results), html.Div("Simulation complete.", className="alert alert-success")

    except Exception as exc:
        return dash.no_update, html.Div(f"Error: {exc}", className="alert alert-error")
