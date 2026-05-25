"""Validate page — run all validation checks and show the report."""

import os
import dash
from dash import html, dcc, Input, Output, callback
import store

dash.register_page(__name__, path="/validate", title="Validate")

_VALIDATE_DIR = os.path.join(store.MODEL_ROOT, "analysis", "model_validation", "validation_output")
_REPORT_PATH  = os.path.join(_VALIDATE_DIR, "validation_report.txt")


def _read_report() -> list:
    """Return layout children for the report section."""
    if not os.path.exists(_REPORT_PATH):
        return [html.Div("Click Run validation to generate the report.",
                         className="alert alert-info")]

    with open(_REPORT_PATH, encoding="utf-8") as f:
        text = f.read()

    passed = store.get("validate_passed")
    banner = []
    if passed is True:
        banner.append(html.Div("Overall: ALL CHECKS PASSED", className="alert alert-success"))
    elif passed is False:
        banner.append(html.Div("Overall: ONE OR MORE CHECKS FAILED", className="alert alert-error"))

    return banner + [
        html.Details([
            html.Summary("Full validation report"),
            html.Div(html.Pre(text), className="exp-body"),
        ], open=True),
    ]


def _charts() -> list:
    """Return chart children; generates data if CSVs are missing."""
    val_csvs = [os.path.join(_VALIDATE_DIR, f)
                for f in ["val_orders.csv","val_buffers.csv","val_availability.csv"]]
    if not all(os.path.exists(p) for p in val_csvs):
        from analysis.model_validation.visualize_validation import generate_data
        generate_data(_VALIDATE_DIR)

    from analysis.model_validation.visualize_validation import show as val_show
    fig = val_show(_VALIDATE_DIR)
    return [html.H2("Diagnostic charts"), dcc.Graph(figure=fig)]


def layout():
    return html.Div([
        html.Div("analyse · validate", className="af-eyebrow"),
        html.H1("Validate"),
        html.P("Runs four test suites: conservation laws, boundary cases, "
               "monotonicity, statistical checks.",
               className="page-caption"),

        html.Button("Run validation", id="val-btn", n_clicks=0,
                    className="btn btn-primary btn-full"),
        html.Div(id="val-status", style={"marginTop": "10px"}),

        dcc.Loading(
            html.Div(id="val-results",
                     children=_read_report() + (
                         [html.Hr(className="divider")] + _charts()
                         if store.get("validate_done") and os.path.exists(_REPORT_PATH)
                         else []
                     )),
            type="circle",
        ),
    ])


@callback(
    Output("val-results", "children"),
    Output("val-status",  "children"),
    Input("val-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _run_validate(n_clicks):
    try:
        from analysis.model_validation.validate import run_all
        passed = run_all(show_charts=False, report_dir=_VALIDATE_DIR)
        store.set("validate_done",   True)
        store.set("validate_passed", passed)

        status_msg = ("All checks passed."        if passed
                      else "One or more checks failed — see the report below.")
        status_cls = "alert alert-success" if passed else "alert alert-error"

        children = _read_report() + [html.Hr(className="divider")] + _charts()
        return children, html.Div(status_msg, className=status_cls)

    except Exception as exc:
        return dash.no_update, html.Div(f"Error: {exc}", className="alert alert-error")
