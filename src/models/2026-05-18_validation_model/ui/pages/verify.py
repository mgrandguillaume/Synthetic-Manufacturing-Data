"""Verify page — run all verification checks and show the report."""

import os
import dash
from dash import html, dcc, Input, Output, callback
import store

dash.register_page(__name__, path="/verify", title="Verify")

_VERIFY_DIR  = os.path.join(store.MODEL_ROOT, "analysis", "model_verification", "verification_output")
_REPORT_PATH = os.path.join(_VERIFY_DIR, "verification_report.txt")


def _read_report() -> list:
    """Return layout children for the report section."""
    if not os.path.exists(_REPORT_PATH):
        return [html.Div("Click Run verification to generate the report.",
                         className="alert alert-info")]

    with open(_REPORT_PATH, encoding="utf-8") as f:
        text = f.read()

    passed = store.get("verify_passed")
    banner = []
    if passed is True:
        banner.append(html.Div("Overall: ALL CHECKS PASSED", className="alert alert-success"))
    elif passed is False:
        banner.append(html.Div("Overall: ONE OR MORE CHECKS FAILED", className="alert alert-error"))

    return banner + [
        html.Details([
            html.Summary("Full verification report"),
            html.Div(html.Pre(text), className="exp-body"),
        ], open=True),
    ]


def _charts() -> list:
    """Return chart children; generates data if CSVs are missing."""
    verify_csvs = [os.path.join(_VERIFY_DIR, f)
                   for f in ["val_orders.csv", "val_buffers.csv", "val_availability.csv"]]
    if not all(os.path.exists(p) for p in verify_csvs):
        from analysis.model_verification.visualize_verification import generate_data
        generate_data(_VERIFY_DIR)

    from analysis.model_verification.visualize_verification import show as verify_show
    fig = verify_show(_VERIFY_DIR)
    return [html.H2("Diagnostic charts"), dcc.Graph(figure=fig)]


def layout():
    return html.Div([
        html.Div("analyse · verify", className="af-eyebrow"),
        html.H1("Verify"),
        html.P("Runs four test suites: conservation laws, boundary cases, "
               "monotonicity, statistical checks.",
               className="page-caption"),

        html.Button("Run verification", id="verify-btn", n_clicks=0,
                    className="btn btn-primary btn-full"),
        html.Div(id="verify-status", style={"marginTop": "10px"}),

        dcc.Loading(
            html.Div(id="verify-results",
                     children=_read_report() + (
                         [html.Hr(className="divider")] + _charts()
                         if store.get("verify_done") and os.path.exists(_REPORT_PATH)
                         else []
                     )),
            type="circle",
        ),
    ])


@callback(
    Output("verify-results", "children"),
    Output("verify-status",  "children"),
    Input("verify-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _run_verify(n_clicks):
    try:
        from analysis.model_verification.verification import run_all
        passed = run_all(show_charts=False, report_dir=_VERIFY_DIR)
        store.set("verify_done",   True)
        store.set("verify_passed", passed)

        status_msg = ("All checks passed."
                      if passed else "One or more checks failed — see the report below.")
        status_cls = "alert alert-success" if passed else "alert alert-error"

        children = _read_report() + [html.Hr(className="divider")] + _charts()
        return children, html.Div(status_msg, className=status_cls)

    except Exception as exc:
        return dash.no_update, html.Div(f"Error: {exc}", className="alert alert-error")
