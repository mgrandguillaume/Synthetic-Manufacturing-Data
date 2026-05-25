"""Sweep page — run the parameter sweep defined in config.yaml."""

import os
import itertools
import threading
import yaml
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

    if total == 0:
        label = "Preparing…"
    elif done == total:
        label = f"Done — {total} runs completed"
    else:
        label = f"Run {done} / {total}  ({pct}%)"

    return html.Div([
        html.Div(
            label,
            style={
                "fontSize": "13px",
                "fontFamily": "IBM Plex Sans, system-ui, sans-serif",
                "color": "#4a4a48",
                "marginBottom": "6px",
            },
        ),
        html.Div(
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


def _build_warnings(n_actual: int, cfg: dict, expanded: dict) -> list:
    """
    Return a list of alert Divs for any performance conditions that apply.

    Parameters
    ----------
    n_actual : int
        The number of runs that will actually execute — either n_valid (all
        combinations) or the user-supplied limit, whichever is smaller.
    cfg : dict
        Parsed config.yaml.
    expanded : dict
        Sweep parameter grid already expanded to lists (from _expand()).

    Warning conditions
    ------------------
    1. BOM depth > 4 in the grid — per-run cost grows steeply with depth
       because component count ≈ branching^depth.
    2. n_ticks > 10 000 — state_summary.csv rows = runs × n_ticks; above
       ~10 K ticks the file can reach hundreds of MB.
    3. n_orders > 100 — per-run simulation time scales linearly with orders.
    4. branching_max > 3 AND max swept depth > 3 — combined exponential growth.
    5. n_actual × n_ticks ≥ 1 000 000 AND n_ticks ≤ 10 000 — wide grid at a
       moderate tick count still produces millions of state_summary rows.
    """
    sim_cfg       = cfg.get("simulation", {})
    n_ticks       = sim_cfg.get("n_ticks", 0)
    n_orders      = sim_cfg.get("n_orders", 0)
    branching_max = max(cfg.get("bom", {}).get("branching", [2, 2]))
    depth_vals    = expanded.get("depth", [])
    max_depth     = max(depth_vals) if depth_vals else 0
    est_rows      = n_actual * n_ticks

    alerts = []

    # 1. BOM depth > 4
    if any(d > 4 for d in depth_vals):
        alerts.append(html.Div([
            html.Strong("Note — BOM depth above 4: "),
            "The sweep grid includes BOM depth values above 4. Each additional "
            "depth level multiplies the number of components by the branching "
            "factor and requires proportionally more simulation ticks, so "
            "per-run time increases sharply with depth. Runs at higher depth "
            "values will take considerably longer than earlier ones.",
        ], className="alert alert-warning", style={"marginTop": "12px"}))

    # 2. High tick count
    if n_ticks > 10_000:
        alerts.append(html.Div([
            html.Strong("Note — high tick count: "),
            f"n_ticks is set to {n_ticks:,}. The sweep result file "
            f"state_summary.csv stores one row per run per tick, so this sweep "
            f"will produce approximately {est_rows:,} rows "
            f"({n_actual:,} runs × {n_ticks:,} ticks). "
            "The chart visualiser handles this with a chunked reader, but "
            "loading and rendering will still be noticeably slower than for "
            "smaller tick counts. Consider reducing n_ticks in "
            "Configure → simulation if you do not need the full time horizon "
            "for every run.",
        ], className="alert alert-warning", style={"marginTop": "12px"}))

    # 3. High order count
    if n_orders > 100:
        alerts.append(html.Div([
            html.Strong("Note — high order count: "),
            f"n_orders is set to {n_orders:,}. Per-run simulation time scales "
            "linearly with the number of orders — each order triggers a full "
            "BOM explosion and is tracked through the factory until completion. "
            f"With {n_actual:,} runs, this sweep will process approximately "
            f"{n_actual * n_orders:,} total orders. Consider reducing n_orders "
            "in Configure → simulation if shorter runs are acceptable.",
        ], className="alert alert-warning", style={"marginTop": "12px"}))

    # 4. High branching × depth
    if branching_max > 3 and max_depth > 3:
        est_comps = branching_max ** max_depth
        alerts.append(html.Div([
            html.Strong("Note — high branching × depth: "),
            f"The BOM branching factor reaches {branching_max} and the sweep "
            f"includes depth values up to {max_depth}. Component count grows "
            f"roughly as branching^depth (≈ {est_comps:,} at the maximum), "
            "which multiplies workstation assignments, buffer slots, and the "
            "BOM explosion work per order. Per-run time and memory usage can "
            "grow steeply as both parameters increase together.",
        ], className="alert alert-warning", style={"marginTop": "12px"}))

    # 5. Large state_summary not already caught by warning 2
    if est_rows >= 1_000_000 and n_ticks <= 10_000:
        alerts.append(html.Div([
            html.Strong("Note — large state_summary output: "),
            f"With {n_actual:,} runs and {n_ticks:,} ticks each, "
            f"state_summary.csv will contain approximately {est_rows:,} rows. "
            "The chart visualiser uses a chunked reader to avoid running out of "
            "memory, but loading will be slower than for smaller outputs. "
            "Use the 'Limit to N runs' field to reduce the grid size if needed.",
        ], className="alert alert-warning", style={"marginTop": "12px"}))

    return alerts


def _build_charts():
    """Build the sweep visualisation figure from disk. Returns a list of Dash children."""
    csv_files = [os.path.join(_SWEEP_DIR, f)
                 for f in ["gen_stats.csv", "state_summary.csv",
                            "utilization.csv", "throughput.csv", "costs.csv"]]
    missing = [os.path.basename(p) for p in csv_files if not os.path.exists(p)]
    if missing:
        return [html.Div(
            f"Sweep output files not found: {', '.join(missing)}. "
            "Run the sweep first.",
            className="alert alert-info",
        )]
    try:
        from analysis.sweep.visualize_sweep import show as sweep_show
        fig = sweep_show(_SWEEP_DIR)
        return [dcc.Graph(figure=fig)]
    except Exception as exc:
        import traceback
        return [html.Div([
            html.Strong("Chart build failed: "),
            str(exc),
            html.Pre(traceback.format_exc(),
                     style={"fontSize": "11px", "marginTop": "8px",
                            "whiteSpace": "pre-wrap", "color": "#8a8a86"}),
        ], className="alert alert-error")]


# ── Layout ─────────────────────────────────────────────────────────────────────

def layout():
    with open(store.CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    sweep_cfg = cfg.get("sweep", {})
    expanded  = {k: _expand(v) for k, v in sweep_cfg.items()}

    sweep_keys = list(expanded.keys())
    all_combos = list(itertools.product(*expanded.values())) if expanded else []
    n_combos   = len(all_combos)

    # Count only valid combinations (depth <= workstations_count).
    # Invalid ones are silently skipped by the engine, so the user should
    # see the valid count — that is the actual number of runs that will execute.
    def _is_valid(combo: tuple) -> bool:
        params = dict(zip(sweep_keys, combo))
        depth  = params.get("depth")
        n_ws   = params.get("workstations_count")
        return (depth <= n_ws) if (depth is not None and n_ws is not None) else True

    n_valid = sum(1 for c in all_combos if _is_valid(c))
    n_skipped = n_combos - n_valid

    rows = [{"Parameter": k, "Values": str(vals), "Count": len(vals)}
            for k, vals in expanded.items()]

    return html.Div([
        html.Div("analyse · sweep", className="af-eyebrow"),
        html.H1("Parameter sweep"),
        html.P("Reads grid from config.yaml → sweep:  and simulation params from config.yaml → simulation:",
               className="page-caption"),

        html.H2("Sweep grid"),
        html.Div([
            # Custom card: valid count + raw count in red parentheses when some
            # combinations are skipped (depth > workstations_count).
            html.Div([
                html.Div("Total combinations", className="metric-label"),
                html.Div([
                    html.Span(f"{n_valid:,}", className="metric-value"),
                    html.Span([
                        f"  ({n_combos:,} raw)",
                        html.Span(
                            " ⓘ",
                            title=(
                                f"{n_skipped:,} combination(s) skipped — "
                                "depth > workstations_count is always invalid "
                                "(every BOM stage needs at least one workstation). "
                                f"Valid runs: {n_valid:,}  |  "
                                f"Raw grid: {n_combos:,}  |  "
                                f"Skipped: {n_skipped:,}"
                            ),
                            style={"cursor": "help", "fontSize": "12px",
                                   "color": "#c0392b"},
                        ),
                    ], style={"fontSize": "13px", "color": "#c0392b",
                              "marginLeft": "6px"}) if n_skipped > 0 else html.Span(),
                ], style={"display": "flex", "alignItems": "baseline"}),
            ], className="metric-card"),
            _metric("Parameters", len(expanded)),
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

        # Warnings are populated reactively by _warnings_callback so they
        # update whenever the user changes the "Limit to N runs" field.
        html.Div(id="sweep-warnings"),

        html.Hr(className="divider"),

        # ── Max-runs limiter ───────────────────────────────────────────────────
        html.Div([
            html.Span("Limit to N runs", className="widget-label",
                      style={"flexShrink": 0}),
            dcc.Input(
                id="sweep-max-runs",
                type="number",
                placeholder=f"all  ({n_valid:,})",
                min=1,
                max=n_valid if n_valid > 0 else None,
                step=1,
                debounce=False,
                style={"width": "200px", "flexShrink": 0},
            ),
            html.Span(
                "Leave blank to run every combination. "
                "When filled, exactly N combinations are picked at random "
                "(reproducible if a seed is set in Configure → Metadata).",
                style={"fontSize": "12px", "color": "#8a8a86",
                       "alignSelf": "center"},
            ),
        ], style={"display": "flex", "alignItems": "center",
                  "gap": "12px", "marginBottom": "16px"}),

        html.Button("Run sweep", id="sweep-btn", n_clicks=0,
                    className="btn btn-primary btn-full"),
        html.Div(id="sweep-status", style={"marginTop": "10px"}),

        # Progress bar — populated by the polling callback while sweep runs.
        html.Div(id="sweep-progress"),

        # Interval fires every 500 ms while a sweep is running; starts disabled.
        dcc.Interval(id="sweep-poll", interval=2000, n_intervals=0, disabled=True),

        # sweep-load-trigger fires once ~100 ms after the page mounts so that
        # layout() returns immediately (no blocking chart work), then the callback
        # populates results from store.  This also prevents the loading-circle
        # flicker caused by wrapping sweep-results in dcc.Loading.
        dcc.Interval(id="sweep-load-trigger", interval=100,
                     n_intervals=0, max_intervals=1),

        html.Div(id="sweep-results"),
    ])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("sweep-warnings", "children"),
    Input("sweep-load-trigger", "n_intervals"),  # fires once on page mount
    Input("sweep-max-runs",     "value"),        # fires on every limit change
    prevent_initial_call=False,
)
def _warnings_callback(_, max_runs_val):
    """Recompute performance warnings whenever the run limit changes."""
    with open(store.CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    sweep_cfg = cfg.get("sweep", {})
    expanded  = {k: _expand(v) for k, v in sweep_cfg.items()}
    sweep_keys = list(expanded.keys())
    all_combos = list(itertools.product(*expanded.values())) if expanded else []

    def _is_valid(combo):
        params = dict(zip(sweep_keys, combo))
        depth  = params.get("depth")
        n_ws   = params.get("workstations_count")
        return (depth <= n_ws) if (depth is not None and n_ws is not None) else True

    n_valid  = sum(1 for c in all_combos if _is_valid(c))
    # n_actual reflects the limit the user typed (if any).
    n_actual = min(int(max_runs_val), n_valid) if max_runs_val else n_valid

    return _build_warnings(n_actual, cfg, expanded)


@callback(
    Output("sweep-poll",     "disabled"),
    Output("sweep-status",   "children"),
    Output("sweep-progress", "children"),
    Output("sweep-results",  "children"),
    Input("sweep-load-trigger", "n_intervals"),  # fires once on page mount
    Input("sweep-btn",          "n_clicks"),
    Input("sweep-poll",         "n_intervals"),
    State("sweep-max-runs",     "value"),
    prevent_initial_call=True,
)
def _sweep_callback(n_load, n_clicks, n_intervals, max_runs_val):
    triggered = dash.ctx.triggered_id

    # ── Page-load path: populate results from store if a sweep was already run ──
    if triggered == "sweep-load-trigger":
        if store.get("sweep_done"):
            return True, dash.no_update, dash.no_update, _build_charts()
        # Check if a sweep is still running from a previous visit
        prog = store.get("sweep_progress") or {}
        if prog.get("running"):
            return False, dash.no_update, dash.no_update, []
        return True, dash.no_update, dash.no_update, []

    # ── Button: start background sweep thread ──────────────────────────────────
    if triggered == "sweep-btn":
        prog = store.get("sweep_progress") or {}
        if prog.get("running"):
            return (
                False,
                html.Div("A sweep is already running.", className="alert alert-warning"),
                dash.no_update,
                dash.no_update,
            )

        # Parse the optional limit; None means "run all combinations".
        max_runs = int(max_runs_val) if max_runs_val else None

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
                run_sweep(progress_callback=_on_progress, max_runs=max_runs)
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
            True,
            html.Div(f"Sweep failed: {error}", className="alert alert-error"),
            [],
            dash.no_update,
        )

    if not running and done > 0:
        # Sweep finished — disable interval and show charts.
        return (
            True,
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
