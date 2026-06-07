"""Simulate page — run a discrete-time simulation on the generated factory."""

import yaml
import numpy as np
import dash
from dash import html, dcc, Input, Output, State, callback
import plotly.graph_objects as go
import store

dash.register_page(__name__, path="/simulate", title="Simulate")

# ── Helpers ────────────────────────────────────────────────────────────────────

def _label(text): return html.Span(text, className="widget-label")

def _num(id_, value, step=1, min_val=None, fmt=None):
    # debounce=False: these inputs are read as States so debounce must be off —
    # otherwise State may capture the server-side (pre-debounce) value when the
    # button is clicked, causing stale reads.
    kw = dict(id=id_, type="number", value=value, step=step,
              debounce=False, style={"width": "100%"})
    if min_val is not None: kw["min"] = min_val
    return dcc.Input(**kw)

def _metric(label, value):
    return html.Div([
        html.Div(label, className="metric-label"),
        html.Div(str(value), className="metric-value"),
    ], className="metric-card")


def _build_figures(results: dict) -> dict:
    """Build all five Plotly figures from simulation result DataFrames.

    Heavy function — only called once after a fresh simulation run.
    Returns a dict of serialised figure dicts (via .to_dict()) so they can
    be cached in store and cheaply reconstructed on subsequent page visits.
    """
    from shared_utils import theme

    tp     = results["throughput"]
    util   = results["utilization"]
    states = results["states"]

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
    fig_tp_dict = None
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
        fig_tp_dict = fig_tp.to_dict()

    # Costs chart
    costs = results["costs"].copy()
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
    # -------------------------------------------------------------------------
    # The buffers DataFrame has shape (n_ticks × n_components, 4).  With
    # n_ticks = 50 000 and 30 components that is 1.5 million rows.
    #
    # Slow path (old): filter the full DataFrame once per component, create
    #   a Scatter (SVG) trace with 50 000 points each → serialize 1.5 M pts
    #   to JSON → browser renders 30 SVG paths of 50 000 pts each.
    #
    # Fast path (new):
    #   1. Reshape — postprocess builds the DataFrame in tick-major order
    #      (np.repeat ticks, np.tile components), so one reshape turns it
    #      into a (n_ticks, n_components) 2-D array; no filtering needed.
    #   2. Stride-downsample — a monitor is ~1 200 px wide so >1 500 pts/trace
    #      add no visible detail.  We drop every nth point so each trace has
    #      at most _BUF_MAX_PTS points.
    #   3. Scattergl — WebGL-based renderer; handles 100 k+ pts with no lag.
    #
    # Combined effect: ~25× fewer data points, ~10× faster WebGL rendering.
    _BUF_MAX_PTS = 1_500

    buf_df = results["buffers"]
    fig_b_dict = None
    if not buf_df.empty:
        # Step 1: reconstruct the (n_ticks, n_comps) 2-D array via reshape.
        # comp_names are the unique components in the order postprocess wrote them;
        # they repeat in the same pattern every tick.
        # ── Geometry: find n_c without reading the full string column ─────────
        # buf_df is tile-ordered: the same n_c component names repeat every tick,
        # all sharing the same Time value.  A binary search on the float Time
        # column finds where the first tick ends — that is n_c — in O(log n)
        # instead of allocating a 3 M-element Python string array and hashing it.
        times_arr  = buf_df["Time"].to_numpy()                               # float64, fast
        n_c        = int(np.searchsorted(times_arr, times_arr[0], side="right"))
        comp_names = buf_df["Component"].iloc[:n_c].tolist()                 # only n_c strings
        n_t        = len(times_arr) // n_c                                   # ticks logged

        stocks_flat = buf_df["Stock"].to_numpy()
        stocks_2d   = stocks_flat[:n_t * n_c].reshape(n_t, n_c)
        times_1d    = times_arr[::n_c][:n_t]          # one time value per tick row

        # Step 2: compute stride so each trace has at most _BUF_MAX_PTS points.
        step = max(1, n_t // _BUF_MAX_PTS)
        t_ds = times_1d[::step]

        # Step 3: build figure with Scattergl (WebGL) traces.
        fig_b = go.Figure()
        for i, comp in enumerate(comp_names):
            s_ds = stocks_2d[::step, i]
            fig_b.add_trace(go.Scattergl(
                x=t_ds, y=s_ds, mode="lines",
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
        fig_b_dict = fig_b.to_dict()

    # Machine state % over ticks ──────────────────────────────────────────────
    # Aggregate: what fraction of all workstations are in each state, per tick?
    # This is the CLEMATIS-style factory-wide dynamics chart from visualize_sim.py.
    #
    # Performance notes:
    #   - groupby on a Categorical "State" column is fast even for large DataFrames.
    #   - We downsample to at most _MS_MAX_PTS ticks so Scattergl stays smooth.
    #   - Rolling average uses pandas on the downsampled series (cheap).
    _MS_MAX_PTS = 2_000
    SMOOTH      = 20   # rolling window in ticks (applied after downsampling)

    MS_STATES = [
        ("processing", theme.STATE_COLORS["processing"], "Working"),
        ("blocked",    theme.STATE_COLORS["blocked"],    "Blocked"),
        ("starved",    theme.STATE_COLORS["starved"],    "Starved"),
        ("failed",     theme.STATE_COLORS["failed"],     "Failed"),
    ]

    total_ws  = states["Workstation"].nunique()
    state_pct = (
        states.groupby(["Tick", "State"], observed=True)
        .size()
        .unstack(fill_value=0)
        .div(total_ws)
        .mul(100)
    )

    # Stride-downsample so each trace stays below _MS_MAX_PTS points.
    n_ticks_ms = len(state_pct)
    step_ms    = max(1, n_ticks_ms // _MS_MAX_PTS)
    sp_ds      = state_pct.iloc[::step_ms]

    fig_ms = go.Figure()
    for state_key, color, label in MS_STATES:
        if state_key not in sp_ds.columns:
            continue
        raw      = sp_ds[state_key]
        smoothed = raw.rolling(window=SMOOTH, min_periods=1).mean()
        ticks    = sp_ds.index.to_numpy()

        # Faint raw line
        fig_ms.add_trace(go.Scattergl(
            x=ticks, y=raw.to_numpy(),
            mode="lines",
            line=dict(color=color, width=0.75),
            opacity=0.20,
            showlegend=False,
            hoverinfo="skip",
        ))
        # Bold rolling-average line
        fig_ms.add_trace(go.Scattergl(
            x=ticks, y=smoothed.to_numpy(),
            mode="lines",
            name=label,
            line=dict(color=color, width=2.5),
            hovertemplate=(
                f"<b>{label}</b><br>"
                "Tick: %{x}<br>%{y:.1f}% of machines<extra></extra>"
            ),
        ))

    fig_ms.update_layout(
        height=380,
        paper_bgcolor=theme.BG, plot_bgcolor=theme.BG,
        font=dict(color=theme.TEXT, family="IBM Plex Sans, system-ui, sans-serif"),
        xaxis_title="Tick", yaxis_title="% of workstations",
        yaxis=dict(range=[0, 100]),
        legend=dict(bgcolor=theme.SURFACE, bordercolor=theme.BORDER, borderwidth=1,
                    font=dict(color=theme.SUBTEXT)),
        margin=dict(l=50, r=20, t=30, b=40),
    )
    theme.apply_axis_style(fig_ms)

    return dict(
        util=fig_u.to_dict(),
        tp=fig_tp_dict,
        cost=fig_c.to_dict(),
        buf=fig_b_dict,
        ms=fig_ms.to_dict(),
    )


def _assemble_children(results: dict, figs: dict) -> list:
    """Build the Dash children list from pre-computed figure dicts.

    Called both after a fresh run (figs just built) and on page revisit
    (figs loaded from store).  Reconstructing go.Figure from a dict is
    O(1) — no DataFrame work happens here.
    """
    tp   = results["throughput"]
    util = results["utilization"]

    fig_u = go.Figure(figs["util"])
    fig_c = go.Figure(figs["cost"])

    # Throughput tab
    if figs.get("tp") is not None:
        fig_tp = go.Figure(figs["tp"])
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

    # Buffers tab
    if figs.get("buf") is not None:
        buf_content = [dcc.Graph(figure=go.Figure(figs["buf"]))]
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
            _metric("Total time (h)",     f"{tp['Time'].max():.2f}"      if not tp.empty else "—"),
            _metric("Mean lead time (h)", f"{tp['LeadTime'].mean():.2f}" if not tp.empty else "—"),
            _metric("Mean busy %",        f"{util['BusyPct'].mean():.1f}%"),
        ], className="metric-row"),

        dcc.Tabs([
            dcc.Tab(label="machine states", className="tab-item", selected_className="tab-item--selected",
                    children=[dcc.Graph(figure=go.Figure(figs["ms"]))]),
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


def _render_results(results) -> list:
    """Return Dash children for the results area.

    On first call after a fresh run the figures are built from DataFrames
    and cached in store.  On every subsequent page visit the cached figure
    dicts are used directly — no DataFrame work, instant load.
    """
    if results is None:
        return [html.Div("Click Run simulation to start.", className="alert alert-info")]

    figs = store.get("sim_figures")
    if figs is None or "ms" not in figs:
        # First time (or stale cache missing the machine-states figure): rebuild
        figs = _build_figures(results)
        store.set("sim_figures", figs)

    return _assemble_children(results, figs)


# ── Layout ─────────────────────────────────────────────────────────────────────

def layout():
    with open(store.CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    sim  = cfg.get("simulation", {})
    fail = cfg.get("failures",   {})

    # Restore last-used values from store, fall back to config defaults.
    # This ensures navigating away and back keeps the user's edits intact.
    p = store.get("sim_params") or {}

    def _v(key, cfg_val):
        """Return stored param if present, else the config/default value."""
        return p[key] if key in p else cfg_val

    # Prerequisite check
    if store.get("gen_result") is None:
        prereq = html.Div(
            "Run Generate first to create a factory.",
            className="alert alert-warning",
        )
    else:
        prereq = None

    fail_enabled_val = _v("fail_enabled", ["yes"] if fail.get("enabled", False) else [])
    log_buf_val      = _v("log_buffers",  ["yes"])

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
                      _num("sim-n-orders", _v("n_orders",    int(sim.get("n_orders",10))),   min_val=1)],
                     className="form-group"),
            html.Div([_label("Max ticks"),
                      _num("sim-n-ticks",  _v("n_ticks",     int(sim.get("n_ticks",3000))),  step=100, min_val=100)],
                     className="form-group"),
            html.Div([_label("Tick duration (h)"),
                      _num("sim-tick",     _v("tick",        float(sim.get("tick_duration",0.05))), step=0.01, min_val=0.0)],
                     className="form-group"),
            html.Div([_label("Buffer capacity"),
                      _num("sim-buf",      _v("buf",         int(sim.get("buffer_capacity",20))),   min_val=1)],
                     className="form-group"),
            html.Div([_label("Interarrival (ticks)"),
                      _num("sim-interarr", _v("interarr",    int(sim.get("order_interarrival",10))), min_val=1)],
                     className="form-group"),
            html.Div([_label("Log buffer levels"),
                      dcc.Checklist(id="sim-log-buffers",
                                    options=[{"label": " enabled", "value": "yes"}],
                                    value=log_buf_val)],
                     className="form-group"),
        ], className="grid-3"),

        html.Hr(className="divider"),
        html.Label([
            dcc.Checklist(id="sim-fail-enabled",
                          options=[{"label": "  Enable machine failures", "value": "yes"}],
                          value=fail_enabled_val),
        ], className="toggle-row"),

        html.Div(id="sim-fail-params", children=[
            html.Div([
                html.Div([_label("Weibull β min"),
                          _num("sim-beta-lo", _v("beta_lo", float(fail.get("weibull_beta",[1.5,3.0])[0])), step=0.1)],
                         className="form-group"),
                html.Div([_label("Weibull β max"),
                          _num("sim-beta-hi", _v("beta_hi", float(fail.get("weibull_beta",[1.5,3.0])[1])), step=0.1)],
                         className="form-group"),
                html.Div([_label("Weibull λ min (h)"),
                          _num("sim-lam-lo",  _v("lam_lo",  float(fail.get("weibull_lambda",[20,50])[0])), step=1.0)],
                         className="form-group"),
                html.Div([_label("Weibull λ max (h)"),
                          _num("sim-lam-hi",  _v("lam_hi",  float(fail.get("weibull_lambda",[20,50])[1])), step=1.0)],
                         className="form-group"),
                html.Div([_label("MTTR min (h)"),
                          _num("sim-mttr-lo", _v("mttr_lo", float(fail.get("mttr",[0.5,4.0])[0])), step=0.1)],
                         className="form-group"),
                html.Div([_label("MTTR max (h)"),
                          _num("sim-mttr-hi", _v("mttr_hi", float(fail.get("mttr",[0.5,4.0])[1])), step=0.1)],
                         className="form-group"),
                html.Div([_label("Repair cost min"),
                          _num("sim-rc-lo",   _v("rc_lo",   float(fail.get("repair_cost",[100,500])[0])), step=10.0)],
                         className="form-group"),
                html.Div([_label("Repair cost max"),
                          _num("sim-rc-hi",   _v("rc_hi",   float(fail.get("repair_cost",[100,500])[1])), step=10.0)],
                         className="form-group"),
            ], className="grid-2"),
        ], style={} if fail_enabled_val else {"display": "none"}),

        html.Hr(className="divider"),
        html.Button("Run simulation", id="sim-btn", n_clicks=0,
                    className="btn btn-primary btn-full"),
        html.Div(id="sim-status", style={"marginTop": "10px"}),

        # sim-load-trigger fires once ~100 ms after the page mounts.
        # This keeps layout() instant (no blocking figure work here) while
        # still populating results immediately after the page frame appears.
        dcc.Interval(id="sim-load-trigger", interval=100,
                     n_intervals=0, max_intervals=1),

        dcc.Loading(
            html.Div(id="sim-results"),
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
    Input("sim-load-trigger", "n_intervals"),   # fires once ~100 ms after page mount
    Input("sim-btn",          "n_clicks"),
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
def _run_sim(n_intervals, n_clicks,
             n_orders, n_ticks, tick, buf, interarr, log_buf,
             fail_en, beta_lo, beta_hi, lam_lo, lam_hi,
             mttr_lo, mttr_hi, rc_lo, rc_hi):

    # ── Page-load path: just render whatever is already in the store ───────────
    if dash.ctx.triggered_id == "sim-load-trigger":
        return _render_results(store.get("sim_result")), dash.no_update

    # ── Button path: validate, run, return results ─────────────────────────────
    gen_result = store.get("gen_result")
    if gen_result is None:
        return dash.no_update, html.Div(
            "Generate a factory first.", className="alert alert-warning")

    from engine.simulate.simulate import simulate
    import yaml

    with open(store.CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    seed = cfg.get("metadata", {}).get("seed")

    # Persist all form values so layout() can restore them on the next page visit
    store.set("sim_params", dict(
        n_orders=int(n_orders or 10),   n_ticks=int(n_ticks or 3000),
        tick=float(tick or 0.05),       buf=int(buf or 20),
        interarr=int(interarr or 10),   log_buffers=log_buf,
        fail_enabled=fail_en,
        beta_lo=float(beta_lo or 1.5),  beta_hi=float(beta_hi or 3.0),
        lam_lo=float(lam_lo or 20),     lam_hi=float(lam_hi or 50),
        mttr_lo=float(mttr_lo or 0.5),  mttr_hi=float(mttr_hi or 4.0),
        rc_lo=float(rc_lo or 100),      rc_hi=float(rc_hi or 500),
    ))

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
        # Build figures now and cache them so future page visits are instant
        store.set("sim_figures", None)   # clear stale cache first
        figs = _build_figures(results)
        store.set("sim_figures", figs)
        return _assemble_children(results, figs), html.Div("Simulation complete.", className="alert alert-success")

    except Exception as exc:
        return dash.no_update, html.Div(f"Error: {exc}", className="alert alert-error")
