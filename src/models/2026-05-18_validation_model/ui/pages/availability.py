"""Availability page — theoretical (integrated) vs Monte Carlo system availability."""

import math
import yaml
import dash
from dash import html, dcc, Input, Output, State, callback
import store

dash.register_page(__name__, path="/availability", title="Availability")


def _label(text): return html.Span(text, className="widget-label")

def _num(id_, value, step=1, min_val=None):
    kw = dict(id=id_, type="number", value=value, step=step,
              debounce=False, style={"width": "100%"})
    if min_val is not None: kw["min"] = min_val
    return dcc.Input(**kw)

def _metric(label, value, delta=None):
    children = [
        html.Div(label, className="metric-label"),
        html.Div(str(value), className="metric-value"),
    ]
    if delta:
        children.append(html.Div(delta, className="metric-delta"))
    return html.Div(children, className="metric-card")


def _render_results(theo_int, exp, gen_result, n_reps) -> list:
    if theo_int is None:
        return [html.Div("Click Run availability analysis to start.",
                         className="alert alert-info")]

    ci_lo, ci_hi = exp["A_sys_ci95"]

    comp_n_producers: dict = {}
    for c in gen_result["configurations"]:
        comp_n_producers[c.component] = comp_n_producers.get(c.component, 0) + 1

    bottleneck_rows = []
    for comp_id, A_c in theo_int["bottlenecks"][:10]:
        n_cap = comp_n_producers.get(comp_id, 0)
        bottleneck_rows.append({
            "Component":  comp_id,
            "A_comp (%)": round(A_c * 100, 4),
            "Producers":  n_cap,
            "Risk":       "SPOF" if n_cap == 1 else ("Limited" if n_cap == 2 else "OK"),
        })

    weibull_info = {
        "beta_rep":              round(theo_int["beta_rep"],   3),
        "lambda_rep":            round(theo_int["lambda_rep"], 2),
        "MTBF_h":                round(theo_int["MTBF_h"],     2),
        "MTTR_h":                round(theo_int["MTTR_h"],     2),
        "A_ws_integrated (%)":   f"{theo_int['A_ws']*100:.3f}",
    }

    from analysis.use_cases.availability_analysis.availability import _show_plots
    fig = _show_plots(theo_int, exp, gen_result, n_replications=n_reps)

    return [
        html.Hr(className="divider"),
        html.H2("Results"),
        html.Div([
            _metric("Integrated A_sys",   f"{theo_int['A_sys']*100:.3f}%"),
            _metric("Experimental A_sys", f"{exp['A_sys_mean']*100:.3f}%",
                    delta=f"95% CI [{ci_lo*100:.2f}%, {ci_hi*100:.2f}%]"),
        ], className="metric-row"),

        html.Details([
            html.Summary("Weibull parameters used"),
            html.Div(
                html.Div(
                    [span
                     for k, v in weibull_info.items()
                     for span in (html.Span(k, className="k"),
                                  html.Span(str(v), className="v"))],
                    className="af-kv",
                ),
                className="exp-body",
            ),
        ]),

        html.H2("Component bottlenecks  ·  top 10 weakest"),
        dash.dash_table.DataTable(
            data=bottleneck_rows,
            columns=[{"name": c, "id": c}
                     for c in ["Component", "A_comp (%)", "Producers", "Risk"]],
            style_cell=dict(fontFamily="JetBrains Mono, monospace", fontSize="12px",
                            padding="6px 10px", border="1px solid #d9d9d4", textAlign="left"),
            style_header=dict(background="#f7f7f5", fontWeight="500",
                              border="1px solid #d9d9d4", color="#6a6a6a", fontSize="11px"),
        ) if bottleneck_rows else html.Span(),

        html.Hr(className="divider"),
        dcc.Graph(figure=fig),
    ]


def layout():
    with open(store.CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    fail_cfg = cfg.get("failures", {})

    if not fail_cfg.get("enabled", False):
        return html.Div([
            html.Div("analyse · availability", className="af-eyebrow"),
            html.H1("Availability analysis"),
            html.Div(
                "Machine failures are disabled in config.yaml. "
                "Go to Configure → Failures, enable them, and save before running this analysis.",
                className="alert alert-error",
            ),
        ])

    return html.Div([
        html.Div("analyse · availability", className="af-eyebrow"),
        html.H1("Availability analysis"),
        html.P("Compares theoretical (integrated RBD) and experimental (Monte Carlo) "
               "system availability. Horizon and warm-up are scaled automatically to "
               "the workstation MTBF.",
               className="page-caption"),

        html.H2("Monte Carlo parameters"),
        html.Div([
            html.Div([_label("Replications"),
                      _num("av-reps", 200, step=50, min_val=50)],
                     className="form-group"),
        ], className="grid-3"),

        html.Hr(className="divider"),
        html.Button("Run availability analysis", id="av-btn", n_clicks=0,
                    className="btn btn-primary btn-full"),
        html.Div(id="av-status", style={"marginTop": "10px"}),

        # av-load-trigger fires once ~100 ms after the page mounts so that
        # layout() returns immediately (no blocking chart work), then the
        # callback below populates results from store.
        dcc.Interval(id="av-load-trigger", interval=100,
                     n_intervals=0, max_intervals=1),

        dcc.Loading(
            html.Div(id="av-results"),
            type="circle",
        ),
    ])


# ── Callbacks ──────────────────────────────────────────────────────────────────

@callback(
    Output("av-results", "children"),
    Output("av-status",  "children"),
    Input("av-load-trigger", "n_intervals"),   # fires once on page mount
    Input("av-btn",          "n_clicks"),
    State("av-reps", "value"),
    prevent_initial_call=True,
)
def _avail_callback(n_load, n_clicks, n_reps):
    triggered = dash.ctx.triggered_id

    # ── Page-load path: populate from store if a run already exists ────────────
    if triggered == "av-load-trigger":
        theo_int  = store.get("avail_theo_int")
        exp       = store.get("avail_exp")
        gen       = store.get("avail_gen")
        n_reps_st = store.get("avail_n_reps")
        return _render_results(theo_int, exp, gen, n_reps_st), dash.no_update

    # ── Button path: run the full analysis ────────────────────────────────────
    with open(store.CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    fail_cfg = cfg.get("failures", {})
    seed     = cfg.get("metadata", {}).get("seed", 42)

    if not fail_cfg.get("enabled", False):
        return dash.no_update, html.Div(
            "Enable failures in Configure first.", className="alert alert-warning")

    try:
        from engine.generate.generate import generate_simple_assembly
        from analysis.use_cases.availability_analysis import theoretical_integrated, experimental
        from analysis.use_cases.availability_analysis.availability import (
            WARMUP_MTBF_MULT, HORIZON_MTBF_MULT,
            POINTS_PER_MIN_MTTR, N_TIMEPOINTS_FLOOR,
        )

        gen_result = generate_simple_assembly(store.CONFIG_PATH, export_csv=False)
        theo_int   = theoretical_integrated.compute(gen_result, fail_cfg)

        # Scale horizon and warm-up to MTBF (same logic as standalone script).
        beta_rep   = (float(fail_cfg["weibull_beta"][0])   + float(fail_cfg["weibull_beta"][1]))   / 2
        lambda_rep = (float(fail_cfg["weibull_lambda"][0]) + float(fail_cfg["weibull_lambda"][1])) / 2
        mtbf_h     = lambda_rep * math.gamma(1.0 + 1.0 / beta_rep)
        mttr_min   = float(fail_cfg["mttr"][0])

        warmup_hours  = WARMUP_MTBF_MULT  * mtbf_h
        horizon_hours = warmup_hours + HORIZON_MTBF_MULT * mtbf_h
        span          = horizon_hours - warmup_hours
        n_timepoints  = max(
            N_TIMEPOINTS_FLOOR,
            int(math.ceil(span / (mttr_min / POINTS_PER_MIN_MTTR))) + 1,
        )

        n_reps_int = int(n_reps or 200)
        exp_result = experimental.run(
            gen_result, fail_cfg,
            n_replications = n_reps_int,
            horizon_hours  = horizon_hours,
            warmup_hours   = warmup_hours,
            n_timepoints   = n_timepoints,
            seed           = seed,
        )

        store.set("avail_theo_int", theo_int)
        store.set("avail_exp",      exp_result)
        store.set("avail_gen",      gen_result)
        store.set("avail_n_reps",   n_reps_int)

        children = _render_results(theo_int, exp_result, gen_result, n_reps_int)
        return children, html.Div("Analysis complete.", className="alert alert-success")

    except Exception as exc:
        return dash.no_update, html.Div(f"Error: {exc}", className="alert alert-error")
