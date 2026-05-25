"""
Assembly Factory — Dash UI entry point.

Run with:  python app.py
           (from the ui/ directory, or via __main__.py from the model root)
"""

import os
import sys

_UI_DIR     = os.path.dirname(os.path.abspath(__file__))
_MODEL_ROOT = os.path.normpath(os.path.join(_UI_DIR, ".."))
if _UI_DIR     not in sys.path: sys.path.insert(0, _UI_DIR)
if _MODEL_ROOT not in sys.path: sys.path.insert(0, _MODEL_ROOT)

import dash
from dash import html, dcc, Input, Output, callback

# ── App ────────────────────────────────────────────────────────────────────────
app = dash.Dash(
    __name__,
    use_pages          = True,
    suppress_callback_exceptions = True,
    title              = "Assembly Factory",
)

# ── Navigation items ───────────────────────────────────────────────────────────
_NAV = [
    # (href, label, nav-link-id, section)
    ("/",             "Home",         "nl-home",         None),
    ("/configure",    "Configure",    "nl-configure",    None),
    ("/generate",     "Generate",     "nl-generate",     "Engine"),
    ("/simulate",     "Simulate",     "nl-simulate",     "Engine"),
    ("/sweep",        "Sweep",        "nl-sweep",        "Analyse"),
    ("/validate",     "Validate",     "nl-validate",     "Analyse"),
    ("/availability", "Availability", "nl-availability", "Analyse"),
]


def _sidebar() -> html.Nav:
    """Build the static sidebar skeleton; active link is set by callback."""
    sections: list = [
        html.Div("Synthetic Manufacturing Data Generation", className="sidebar-brand"),
    ]

    current_section = object()  # sentinel so first section always triggers
    block: list = []

    for href, label, nav_id, section in _NAV:
        if section != current_section:
            if block:
                sections.append(html.Div(block, className="sidebar-section"))
                block = []
            if section is not None:
                sections.append(html.Div(section, className="sidebar-section-label"))
            current_section = section

        block.append(
            dcc.Link(label, href=href, id=nav_id, className="sidebar-nav-link")
        )

    if block:
        sections.append(html.Div(block, className="sidebar-section"))

    return html.Nav(sections, className="sidebar")


# ── Layout ─────────────────────────────────────────────────────────────────────
app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    _sidebar(),
    html.Main(dash.page_container, className="main-content"),
], className="app-wrapper")


# ── Active nav-link highlight ──────────────────────────────────────────────────
@callback(
    [Output(nav_id, "className") for _, _, nav_id, _ in _NAV],
    Input("url", "pathname"),
)
def _highlight_nav(pathname: str):
    return [
        "sidebar-nav-link active" if pathname == href else "sidebar-nav-link"
        for href, _, _, _ in _NAV
    ]


# ── Dev server ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8501)
