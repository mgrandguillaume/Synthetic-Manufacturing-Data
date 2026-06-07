"""
Shared visual theme for all Assembly Factory plots.

Import this module in any visualisation script:

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import theme

Then reference theme.BG, theme.STATE_COLORS, theme.palette(i), etc.
"""

# ── Base colours ───────────────────────────────────────────────────────────────
BG      = "#0d1117"   # figure / page background
SURFACE = "#161b22"   # legend / card background
BORDER  = "#21262d"   # grid lines, legend borders
TEXT    = "#e6edf3"   # primary labels and titles
SUBTEXT = "#8b949e"   # secondary labels (axes, subtitles)

# ── Categorical palette (use palette(i) for series colouring) ─────────────────
PALETTE = [
    "#58a6ff",   # blue
    "#d29922",   # amber
    "#3fb950",   # green
    "#f78166",   # red-orange
    "#a371f7",   # purple
    "#39d353",   # bright green
    "#e3b341",   # yellow
    "#79c0ff",   # light blue
]


def palette(i: int) -> str:
    """Return a palette colour by index, wrapping around if needed."""
    return PALETTE[i % len(PALETTE)]


# ── Workstation state colours ──────────────────────────────────────────────────
STATE_COLORS: dict[str, str] = {
    "processing": "#58a6ff",
    "setup":      "#d29922",
    "blocked":    "#f78166",
    "starved":    "#a371f7",
    "idle":       "#30363d",
    "failed":     "#da3633",   # red — machine breakdown
}

STATES_ORDER = ["processing", "setup", "blocked", "starved", "idle", "failed"]

# ── Cost-type colours (keyed by CSV column name) ───────────────────────────────
COST_COLORS: dict[str, str] = {
    "SetupCost":     STATE_COLORS["setup"],       # amber
    "OperatingCost": STATE_COLORS["processing"],  # blue
    "TransportCost": SUBTEXT,                     # grey
}


# ── Axis styling helper ────────────────────────────────────────────────────────
def apply_axis_style(fig) -> None:
    """Apply the standard dark-theme grid/tick style to every axis in fig."""
    style = dict(
        gridcolor=BORDER,
        zerolinecolor=BORDER,
        tickcolor=SUBTEXT,
        tickfont=dict(color=SUBTEXT, size=11),
        linecolor=BORDER,
    )
    for key in fig.layout:
        if key.startswith(("xaxis", "yaxis")):
            fig.layout[key].update(style)
