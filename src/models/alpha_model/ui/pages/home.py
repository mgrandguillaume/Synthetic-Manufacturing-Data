"""Home page — project overview and session status."""

import dash
from dash import html
import store

dash.register_page(__name__, path="/", title="Home")


def _badge(done: bool) -> str:
    return "Done" if done else "—"


def _metric(label: str, value: str) -> html.Div:
    return html.Div([
        html.Div(label, className="metric-label"),
        html.Div(value, className="metric-value"),
    ], className="metric-card")


def _pipeline_row(num: str, name: str, desc: str, done: bool) -> html.Div:
    return html.Div([
        html.Span(num,  className="num"),
        html.Span([
            html.B(name, style={"fontFamily": "var(--af-sans)", "fontSize": "13px"}),
            html.Span(f"  {desc}", className="desc"),
        ]),
        html.Span("Done" if done else "Ready",
                  className="status done" if done else "status"),
    ], className="pipeline-row")


def layout():
    gen_done   = store.get("gen_result")   is not None
    sim_done   = store.get("sim_result")   is not None
    sweep_done = store.get("sweep_done",   False)
    val_done   = store.get("validate_done",False)
    avail_done = store.get("avail_done",   False)

    return html.Div([
        # ── Header ────────────────────────────────────────────────────────────
        html.Div("project · overview", className="af-eyebrow"),
        html.H1("Assembly Factory"),
        html.P(
            "A synthetic discrete-time manufacturing simulation. "
            "Use the sidebar to navigate.",
            className="page-caption",
        ),

        # ── Session status ─────────────────────────────────────────────────────
        html.H2("Session status"),
        html.Div([
            _metric("Generate",     _badge(gen_done)),
            _metric("Simulate",     _badge(sim_done)),
            _metric("Sweep",        _badge(sweep_done)),
            _metric("Validate",     _badge(val_done)),
            _metric("Availability", _badge(avail_done)),
        ], className="metric-row"),

        # ── Pipeline ──────────────────────────────────────────────────────────
        html.H2("Pipeline"),
        html.Div([
            html.Div([
                html.Span("Step", className="num",    style={"color": "var(--af-ink-3)"}),
                html.Span("Stage"),
                html.Span("Status", style={"textAlign": "right", "color": "var(--af-ink-3)"}),
            ], className="af-section-head", style={"borderBottom": "none"}),
        ]),
        html.Div([
            _pipeline_row("01", "Configure",    "review & adjust config.yaml",                        True),
            _pipeline_row("02", "Generate",     "build a factory from the config",                    gen_done),
            _pipeline_row("03", "Simulate",     "run a discrete-time simulation",                     sim_done),
            _pipeline_row("04", "Sweep",        "scan the parameter grid",                            sweep_done),
            _pipeline_row("05", "Validate",     "conservation, boundary, monotonicity checks",        val_done),
            _pipeline_row("06", "Availability", "theoretical vs Monte Carlo system availability",      avail_done),
        ], className="pipeline-table"),
    ])
