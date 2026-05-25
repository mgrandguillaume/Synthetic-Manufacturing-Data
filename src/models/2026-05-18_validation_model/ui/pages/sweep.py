"""Sweep page — run the parameter sweep defined in config.yaml."""

import os
import itertools
import threading
import yaml
import pandas as pd
import dash
from dash import html, dcc, Input, Output, State, callback, dash_table
import store

dash.register_page(__name__, path="/sweep", title="Sweep")

_SWEEP_DIR = os.path.join(store.MODEL_ROOT, "analysis", "sweep", "sweep_output")


# ── Helpers ────────────────────────────────────────────────────────────────────

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


def _progress_bar(done: int, total: int, current: str) -> html.Div:
    """Render the progress bar widget."""
    pct = round(done / total * 100) if total > 0 else 0

    # Label row: "Run 42 / 160  (26%)"
    if total == 0:
        label = "Preparing…"
    elif done == total:
        label = f"Done — {total} runs completed"
    else:
        label = f"Run {done} / {total}  ({pct}%)"

    return html.Div([
        # Label + percentage
        html.Div(
            label,
            style={
                "fontSize": "13px",
                "fontFamily": "IBM Plex Sans, system-ui, sans-serif",
                "color": "#4a4a48",
                "marginBottom": "6px",
            },
        ),
        # Track
        html.Div(
            # Fill
            html.Div(style={
                "height": "100%",
                "width": f"{pct}%",
                "minWidth": "4px" if pct > 0 else "0",
                "background": "linear-gradient(90deg, #4f7df0, #6fa3ff)",
                "borderRadius": "4px",
                "transition": "width 0.35s ease",
            }),
            style={
                "height": "8px",
                "width": "100%",
                "background": "#e5e5e3",
                "borderRadius": "4px",
                "overflow": "hidden",
                "marginBottom": "8px",
            },
        ),
        # Current combo
        html.Div(
            current,
            style={
                "fontSize": "11px",
                "fontFamily": "JetBrains Mono, monospace",
                "color": "#8a8a86",
                "minHeight": "16px",
            },
        ),
    ], style={"padding": "12px 0 4px"})


def _build_charts():
    """Build the sweep visualisation figure from disk. Returns a list of Dash children."""
    csv_files = [os.path.join(_SWEEP_DIR, f)
                 for f in ["gen_stats.csv", "state_summary.csv",
                            "utilization.csv", "throughput.csv", "costs.csv"]]
    if not all(os.path.exists(p) for p in csv_files):
        return [html.Div("Previous sweep results not found on disk.",
                         className="alert alert-info")]
    from analysis.sweep.visualize_sweep import show as sweep_show
    fig = sweep_show(_SWEEP_DIR)
    return [dcc.Graph(figure=fig)]


# ── Layout ─────────────────────────────────────────────────────────────────────

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
            columns=[{"name": c, "id": c} for c in ["Parameter", "Values", "Count"]],
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

        # Progress bar — populated by the polling callback while sweep runs.
        html.Div(id="sweep-progress"),

        # Interval fires every 500 ms while a sweep is running; starts disabled.
        dcc.Interval(id="sweep-poll", interval=500, n_intervals=0, disabled=True),

        dcc.Loading(
            html.Div(id="sweep-results",
                     children=_build_charts() if store.get("sweep_done") else []),
            type="circle",
        ),
    ])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("sweep-poll",     "disabled"),
    Output("sweep-status",   "children"),
    Output("sweep-progress", "children"),
    Output("sweep-results",  "children"),
    Input("sweep-btn",  "n_clicks"),
    Input("sweep-poll", "n_intervals"),
    prevent_initial_call=True,
)
def _sweep_callback(n_clicks, n_intervals):
    triggered = dash.ctx.triggered_id

    # ── Button: start background sweep thread ──────────────────────────────────
    if triggered == "sweep-btn":
        prog = store.get("sweep_progress") or {}
        if prog.get("running"):
            return (
                False,  # keep interval enabled
                html.Div("A sweep is already running.", className="alert alert-warning"),
                dash.no_update,
                dash.no_update,
            )

        # Reset progress state
        store.set("sweep_progress", {
            "running": True, "done": 0, "total": 0,
            "current": "Preparing…", "error": None,
        })

        def _run():
            def _on_progress(done, total, current):
                store.set("sweep_progress", {
                    "running": True, "done": done, "total": total,
                    "current": current, "error": None,
                })

            try:
                from analysis.sweep.sweep import main as run_sweep
                run_sweep(progress_callback=_on_progress)
                prog = store.get("sweep_progress") or {}
                store.set("sweep_progress", {
                    "running": False,
                    "done":    prog.get("total", 0),
                    "total":   prog.get("total", 0),
                    "current": "",
                    "error":   None,
                })
                store.set("sweep_done", True)
            except Exception as exc:
                store.set("sweep_progress", {
                    "running": False, "done": 0, "total": 0,
                    "current": "", "error": str(exc),
                })

        threading.Thread(target=_run, daemon=True).start()

        return (
            False,  # enable interval
            html.Div("Sweep running…", className="alert alert-info"),
            _progress_bar(0, 0, "Preparing…"),
            dash.no_update,
        )

    # ── Interval: poll store and update progress / finalise ────────────────────
    prog    = store.get("sweep_progress") or {}
    done    = prog.get("done",    0)
    total   = prog.get("total",   0)
    running = prog.get("running", False)
    current = prog.get("current", "")
    error   = prog.get("error")

    if error:
        return (
            True,   # disable interval
            html.Div(f"Sweep failed: {error}", className="alert alert-error"),
            [],
            dash.no_update,
        )

    if not running and done > 0:
        # Sweep finished successfully — disable interval and show charts.
        return (
            True,   # disable interval
            html.Div("Sweep complete.", className="alert alert-success"),
            [],
            _build_charts(),
        )

    # Still running — update progress bar, keep interval alive.
    return (
        False,
        dash.no_update,
        _progress_bar(done, total, current),
        dash.no_update,
    )
