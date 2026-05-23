"""Sweep page — run the parameter sweep defined in config.yaml."""

import os
import itertools
import yaml
import pandas as pd
import dash
from dash import html, dcc, Input, Output, callback, dash_table
import store

dash.register_page(__name__, path="/sweep", title="Sweep")

_SWEEP_DIR = os.path.join(store.MODEL_ROOT, "analysis", "sweep", "sweep_output")


def _expand(val):
    if isinstance(val, dict):
        start, stop, step = val["min"], val["max"], val["step"]
        out, v = [], start
        while v <= stop + step * 1e-9:
            out.append(round(v, 10))
            v += step
        return out
    return val if isinstance(val, list) else [val]


def _metric(label, value):
    return html.Div([
        html.Div(label, className="metric-label"),
        html.Div(str(value), className="metric-value"),
    ], className="metric-card")


def layout():
    with open(store.CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    sweep_cfg = cfg.get("sweep", {})
    expanded  = {k: _expand(v) for k, v in sweep_cfg.items()}
    n_combos  = len(list(itertools.product(*expanded.values()))) if expanded else 0

    rows = [{"Parameter": k, "Values": str(vals), "Count": len(vals)}
            for k, vals in expanded.items()]

    return html.Div([
        html.Div("analyse · sweep", className="af-eyebrow"),
        html.H1("Parameter sweep"),
        html.P("Reads grid from config.yaml → sweep:  and simulation params from config.yaml → simulation:",
               className="page-caption"),

        html.H2("Sweep grid"),
        html.Div([
            _metric("Total combinations", f"{n_combos:,}"),
            _metric("Parameters",         len(expanded)),
        ], className="metric-row"),

        dash_table.DataTable(
            data=rows,
            columns=[{"name": c, "id": c} for c in ["Parameter","Values","Count"]],
            style_cell=dict(fontFamily="JetBrains Mono, monospace", fontSize="12px",
                            padding="6px 10px", border="1px solid #d9d9d4", textAlign="left"),
            style_header=dict(background="#f7f7f5", fontWeight="500",
                              border="1px solid #d9d9d4", color="#6a6a6a", fontSize="11px"),
        ) if rows else html.Div("No sweep parameters defined in config.yaml.",
                                className="alert alert-info"),

        html.Hr(className="divider"),
        html.Button("Run sweep", id="sweep-btn", n_clicks=0,
                    className="btn btn-primary btn-full"),
        html.Div(id="sweep-status", style={"marginTop": "10px"}),

        dcc.Loading(
            html.Div(id="sweep-results",
                     children=_initial_charts() if store.get("sweep_done") else []),
            type="circle",
        ),
    ])


def _initial_charts():
    csv_files = [os.path.join(_SWEEP_DIR, f)
                 for f in ["gen_stats.csv","state_summary.csv",
                            "utilization.csv","throughput.csv","costs.csv"]]
    if not all(os.path.exists(p) for p in csv_files):
        return [html.Div("Previous sweep results not found on disk.",
                         className="alert alert-info")]
    from analysis.sweep.visualize_sweep import show as sweep_show
    fig = sweep_show(_SWEEP_DIR)
    return [dcc.Graph(figure=fig)]


@callback(
    Output("sweep-results", "children"),
    Output("sweep-status",  "children"),
    Input("sweep-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _run_sweep(n_clicks):
    try:
        from analysis.sweep.sweep import main as run_sweep
        run_sweep()
        store.set("sweep_done", True)

        from analysis.sweep.visualize_sweep import show as sweep_show
        fig = sweep_show(_SWEEP_DIR)
        return [dcc.Graph(figure=fig)], html.Div("Sweep complete.", className="alert alert-success")

    except Exception as exc:
        return dash.no_update, html.Div(f"Error: {exc}", className="alert alert-error")
