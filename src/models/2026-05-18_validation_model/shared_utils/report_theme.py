"""
Report-quality visual theme for the Assembly Factory.

Drop-in replacement for theme.py, used by export_figures.py when producing
static images (PNG / SVG) for papers or reports.

All names match those in theme.py so the two modules are interchangeable.
The palette and state colours are darkened variants of the UI palette,
chosen to remain clearly distinguishable on a white page without appearing
washed-out when printed in greyscale.
"""

# ── Base colours (light / white background) ────────────────────────────────────
BG      = "#ffffff"   # figure / page background
SURFACE = "#f6f8fa"   # legend / card background  (very light grey box)
BORDER  = "#d0d7de"   # grid lines, axis lines, legend borders
TEXT    = "#1f2328"   # primary labels and titles   (near-black)
SUBTEXT = "#57606a"   # secondary labels (axis titles, subplot headings)

# ── Categorical palette — darkened for white-background legibility ─────────────
# Each colour maps to the same hue as the UI palette (theme.PALETTE) but is
# darker so it has sufficient contrast against white at typical report DPI.
PALETTE = [
    "#0969da",   # blue          (UI: #58a6ff)
    "#9a6700",   # amber         (UI: #d29922)
    "#1a7f37",   # green         (UI: #3fb950)
    "#cf222e",   # red-orange    (UI: #f78166)
    "#8250df",   # purple        (UI: #a371f7)
    "#2da44e",   # bright green  (UI: #39d353)
    "#bf8700",   # yellow        (UI: #e3b341)
    "#0550ae",   # dark blue     (UI: #79c0ff)
]


def palette(i: int) -> str:
    """Return a palette colour by index, wrapping around if needed."""
    return PALETTE[i % len(PALETTE)]


# ── Workstation state colours ──────────────────────────────────────────────────
STATE_COLORS: dict[str, str] = {
    "processing": "#0969da",   # blue        — machine working
    "setup":      "#9a6700",   # amber       — machine in setup
    "blocked":    "#cf222e",   # red         — machine blocked
    "starved":    "#8250df",   # purple      — machine starved
    "idle":       "#8c959f",   # mid-grey    — machine idle
    "failed":     "#a40e26",   # deep red    — machine failure
}

STATES_ORDER = ["processing", "setup", "blocked", "starved", "idle", "failed"]

# ── Cost-type colours (keyed by CSV column name) ───────────────────────────────
COST_COLORS: dict[str, str] = {
    "SetupCost":     STATE_COLORS["setup"],
    "OperatingCost": STATE_COLORS["processing"],
    "TransportCost": SUBTEXT,
    "RepairCost":    STATE_COLORS["failed"],
}


# ── Axis styling helper ────────────────────────────────────────────────────────
def apply_axis_style(fig) -> None:
    """Apply the light-theme grid / tick style to every axis in fig."""
    style = dict(
        gridcolor  = BORDER,
        zerolinecolor = BORDER,
        tickcolor  = SUBTEXT,
        tickfont   = dict(color=SUBTEXT, size=11),
        linecolor  = BORDER,
        showgrid   = True,
    )
    for key in fig.layout:
        if key.startswith(("xaxis", "yaxis")):
            fig.layout[key].update(style)
