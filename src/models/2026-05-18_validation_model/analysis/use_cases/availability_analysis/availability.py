#!/usr/bin/env python3
"""
System availability analysis — theoretical vs experimental.

Runs two independent estimates of steady-state system availability and
compares them:

  1. Theoretical  — exact RBD calculation using midpoint Weibull params.
  2. Experimental — Monte Carlo simulation of Weibull failure-repair cycles.

Both use the same factory topology (from gen_result) and the same failure
configuration (from config.yaml).

Usage
-----
  uv run src/models/2026-05-18_validation_model/analysis/use_cases/availability_analysis/availability.py

Output
------
  Console  : summary table with theoretical, experimental, and divergence
  Plotly   : three-panel figure:
               (1) Histogram of per-replication availability + theoretical line
               (2) Component bottleneck chart (A_comp per component, sorted)
               (3) System availability timeline (last replication)
"""

import math
import os
import sys

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Path setup ────────────────────────────────────────────────────────────────
_THIS_DIR   = os.path.dirname(os.path.abspath(__file__))
_MODEL_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", ".."))
sys.path.insert(0, _MODEL_ROOT)

from shared_utils import utils
from shared_utils import validate_config
from engine.generate.generate import generate_simple_assembly
from . import theoretical, theoretical_integrated, experimental
from shared_utils import theme

# ── Config ────────────────────────────────────────────────────────────────────
_CONFIG_PATH = os.path.join(_MODEL_ROOT, "config.yaml")

# Monte Carlo settings — increase n_replications for a tighter CI at the
# cost of longer runtime (~1 min for 200 reps on a typical laptop).
N_REPLICATIONS = 1000
SEED           = 42

# The simulation horizon and warm-up are scaled to the workstation MTTF rather
# than hardcoded.  A fixed 2000 h horizon is meaningless across configs: it is
# far too short for a 1500 h MTTF (too few failure-repair cycles observed) and
# wastefully long for a 50 h one.  Scaling keeps the estimate well-conditioned
# regardless of the configured Weibull parameters.
WARMUP_MTTF_MULT  = 4.0    # discard the first ~4x MTTF as start-up transient
HORIZON_MTTF_MULT = 50.0   # then measure ~50 failure-repair cycles

# Time-grid resolution.  The grid must be fine enough to resolve the SHORTEST
# possible repair, otherwise brief outages can fall entirely between two grid
# points and system availability is silently over-estimated.  We require at
# least this many grid points within one minimum-MTTR window, subject to a
# floor so short horizons still get a smooth estimate.
POINTS_PER_MIN_MTTR = 5
N_TIMEPOINTS_FLOOR  = 5_000


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_separator(char: str = "-", width: int = 68) -> None:
    print(char * width)


def _fmt_pct(v: float) -> str:
    return f"{v * 100:.3f}%"


def _divergence_verdict(theo: float, lo: float, hi: float) -> str:
    if lo <= theo <= hi:
        return "PASS - theoretical within 95% CI"
    gap = min(abs(theo - lo), abs(theo - hi))
    gap_pp = gap * 100
    if gap_pp < 3.0:
        note = "(expected: Jensen's inequality bias from wide parameter ranges)"
        return f"NEAR PASS - {gap_pp:.2f}pp outside CI  {note}"
    if gap_pp < 10.0:
        return f"DIVERGE - theoretical {gap_pp:.2f}pp outside CI  (check parameter ranges)"
    return f"FAIL - theoretical {gap_pp:.2f}pp outside CI  (likely a modelling error)"


# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> None:
    # ── Load and validate config ───────────────────────────────────────────────
    cfg = utils.load_config(_CONFIG_PATH)
    validate_config.validate(cfg)

    fail_cfg = cfg.get("failures", {})
    if not fail_cfg.get("enabled", False):
        print(
            "[availability] WARNING: failures.enabled = false in config.yaml.\n"
            "  The availability analysis requires failures to be enabled.\n"
            "  Set failures.enabled: true and re-run."
        )
        sys.exit(1)

    # ── Generate factory ───────────────────────────────────────────────────────
    print("\nGenerating factory...")
    gen_result = generate_simple_assembly(_CONFIG_PATH, export_csv=False)
    n_comps    = sum(1 for c in gen_result["components"] if c.level > 0)
    n_ws       = sum(1 for w in gen_result["workstations"] if w.type == "production")
    print(f"  {n_ws} production workstations, {n_comps} producible components")

    # ── Theoretical ───────────────────────────────────────────────────────────
    print("\nComputing theoretical availability (midpoint)...")
    theo_mid = theoretical.compute(gen_result, fail_cfg)

    print("Computing theoretical availability (integrated)...")
    theo_int = theoretical_integrated.compute(gen_result, fail_cfg)

    # ── Scale the simulation horizon to the MTTF (fix: no hardcoded horizon) ──
    mttf_h        = theo_mid["MTTF_h"]
    mttr_min      = float(fail_cfg["mttr"][0])
    warmup_hours  = WARMUP_MTTF_MULT * mttf_h
    horizon_hours = warmup_hours + HORIZON_MTTF_MULT * mttf_h

    # Resolve the grid finely enough to capture the shortest possible repair.
    span         = horizon_hours - warmup_hours
    n_timepoints = max(
        N_TIMEPOINTS_FLOOR,
        int(math.ceil(span / (mttr_min / POINTS_PER_MIN_MTTR))) + 1,
    )

    # ── Experimental ─────────────────────────────────────────────────────────
    print(
        f"Running Monte Carlo ({N_REPLICATIONS} replications x "
        f"{horizon_hours:.0f} h, warm-up {warmup_hours:.0f} h, "
        f"{n_timepoints} grid points)..."
    )
    exp = experimental.run(
        gen_result,
        fail_cfg,
        n_replications = N_REPLICATIONS,
        horizon_hours  = horizon_hours,
        warmup_hours   = warmup_hours,
        n_timepoints   = n_timepoints,
        seed           = SEED,
    )
    print("  Done.")

    # ── Console report ────────────────────────────────────────────────────────
    ci_lo, ci_hi = exp["A_sys_ci95"]

    _print_separator("=")
    print("  SYSTEM AVAILABILITY ANALYSIS")
    _print_separator("=")

    print(f"\n  Weibull parameters")
    print(f"    beta          = {theo_mid['beta_rep']:.3f}  (range {fail_cfg['weibull_beta']})")
    print(f"    lambda        = {theo_mid['lambda_rep']:.1f} h  (range {fail_cfg['weibull_lambda']})")
    print(f"    MTTF          = {theo_mid['MTTF_h']:.2f} h  per workstation  (at midpoint)")
    print(f"    MTTR          = {theo_mid['MTTR_h']:.2f} h  per workstation  (midpoint)")
    print(f"    A_ws midpoint = {_fmt_pct(theo_mid['A_ws'])}")
    print(f"    A_ws integrated = {_fmt_pct(theo_int['A_ws'])}")

    _print_separator()
    print(f"  {'':30s}  {'Midpoint':>10s}  {'Integrated':>10s}  {'Experimental':>12s}")
    _print_separator()
    print(
        f"  {'System availability  A_sys':30s}  "
        f"{_fmt_pct(theo_mid['A_sys']):>10s}  "
        f"{_fmt_pct(theo_int['A_sys']):>10s}  "
        f"{_fmt_pct(exp['A_sys_mean']):>12s}"
    )
    print(
        f"  {'95% CI (experimental)':30s}  "
        f"{'--':>10s}  "
        f"{'--':>10s}  "
        f"[{_fmt_pct(ci_lo)}, {_fmt_pct(ci_hi)}]"
    )
    print(
        f"  {'Std dev (across runs)':30s}  "
        f"{'--':>10s}  "
        f"{'--':>10s}  "
        f"{_fmt_pct(exp['A_sys_std']):>12s}"
    )
    _print_separator()
    print(f"  Verdict (midpoint):   {_divergence_verdict(theo_mid['A_sys'], ci_lo, ci_hi)}")
    print(f"  Verdict (integrated): {_divergence_verdict(theo_int['A_sys'], ci_lo, ci_hi)}")
    _print_separator()

    print(f"\n  Top 5 weakest components (bottlenecks):")
    for comp_id, A_c in theo_int["bottlenecks"][:5]:
        n_capable = sum(
            1 for c in gen_result["configurations"]
            if c.component == comp_id
        )
        print(
            f"    {comp_id:40s}  A = {_fmt_pct(A_c)}"
            f"  ({n_capable} producer{'s' if n_capable != 1 else ''})"
        )
    _print_separator("=")

    # ── Visualisation ─────────────────────────────────────────────────────────
    _show_plots(theo_mid, theo_int, exp, gen_result,
                n_replications=N_REPLICATIONS).show()


def _show_plots(theo_mid: dict, theo_int: dict, exp: dict, gen_result: dict,
                n_replications: int | None = None):
    """Build and display a three-panel Plotly figure."""

    # Colour aliases for the two theoretical lines
    COL_MID = theme.STATE_COLORS["setup"]    # amber — midpoint
    COL_INT = theme.STATE_COLORS["failed"]   # red   — integrated

    fig = make_subplots(
        rows=2, cols=2,
        specs=[[{"colspan": 2}, None], [{}, {}]],
        subplot_titles=[
            "(1) Per-replication availability distribution",
            "(2) Component bottleneck analysis  (A_comp)",
            "(3) System availability over time  (last replication)",
        ],
        vertical_spacing=0.14,
        horizontal_spacing=0.10,
    )

    ci_lo, ci_hi = exp["A_sys_ci95"]

    # ── (1) Histogram of per-replication availabilities ───────────────────────
    fig.add_trace(go.Histogram(
        x=exp["A_per_run"],
        nbinsx=30,
        name="Monte Carlo runs",
        marker_color=theme.STATE_COLORS["processing"],
        marker_line_color=theme.BG,
        marker_line_width=0.5,
        opacity=0.85,
        hovertemplate="Availability: %{x:.4f}<br>Count: %{y}<extra></extra>",
    ), row=1, col=1)

    # Experimental mean
    fig.add_vline(
        x=exp["A_sys_mean"], row=1, col=1,
        line=dict(color=theme.STATE_COLORS["processing"], width=2.5, dash="solid"),
        annotation_text=f"Exp. mean: {exp['A_sys_mean']*100:.3f}%",
        annotation_font=dict(color=theme.STATE_COLORS["processing"], size=10),
        annotation_position="top right",
    )
    # 95% CI bounds
    for x_ci, label, pos in [
        (ci_lo, f"CI lo: {ci_lo*100:.3f}%", "bottom left"),
        (ci_hi, f"CI hi: {ci_hi*100:.3f}%", "bottom right"),
    ]:
        fig.add_vline(
            x=x_ci, row=1, col=1,
            line=dict(color=theme.SUBTEXT, width=1.5, dash="dot"),
            annotation_text=label,
            annotation_font=dict(color=theme.SUBTEXT, size=9),
            annotation_position=pos,
        )
    # Midpoint theoretical
    fig.add_vline(
        x=theo_mid["A_sys"], row=1, col=1,
        line=dict(color=COL_MID, width=2, dash="dash"),
        annotation_text=f"Midpoint: {theo_mid['A_sys']*100:.3f}%",
        annotation_font=dict(color=COL_MID, size=10),
        annotation_position="top left",
    )
    # Integrated theoretical
    fig.add_vline(
        x=theo_int["A_sys"], row=1, col=1,
        line=dict(color=COL_INT, width=2, dash="dash"),
        annotation_text=f"Integrated: {theo_int['A_sys']*100:.3f}%",
        annotation_font=dict(color=COL_INT, size=10),
        annotation_position="bottom left",
    )

    # ── (2) Component bottleneck bar chart ────────────────────────────────────
    # Use integrated theoretical for per-component values (more accurate A_ws)
    sorted_comps = sorted(theo_int["A_per_component"].items(), key=lambda kv: kv[1])

    comp_n_producers = {}
    for c in gen_result["configurations"]:
        comp_n_producers[c.component] = comp_n_producers.get(c.component, 0) + 1

    bar_colors = []
    for comp_id, _ in sorted_comps:
        n = comp_n_producers.get(comp_id, 0)
        if n == 1:
            bar_colors.append(theme.STATE_COLORS["failed"])     # red  — SPOF
        elif n == 2:
            bar_colors.append(theme.STATE_COLORS["setup"])      # amber — limited redundancy
        else:
            bar_colors.append(theme.STATE_COLORS["processing"]) # blue  — good redundancy

    fig.add_trace(go.Bar(
        x=[c for c, _ in sorted_comps],
        y=[a for _, a in sorted_comps],
        marker_color=bar_colors,
        marker_line_width=0,
        showlegend=False,
        hovertemplate=(
            "<b>%{x}</b><br>"
            "A_comp: %{y:.5f}<br>"
            "%{y:.3%}<extra></extra>"
        ),
    ), row=2, col=1)

    # Both theoretical system lines
    fig.add_hline(
        y=theo_mid["A_sys"], row=2, col=1,
        line=dict(color=COL_MID, width=1.5, dash="dot"),
        annotation_text=f"Midpoint {theo_mid['A_sys']*100:.3f}%",
        annotation_font=dict(color=COL_MID, size=9),
        annotation_position="top right",
    )
    fig.add_hline(
        y=theo_int["A_sys"], row=2, col=1,
        line=dict(color=COL_INT, width=1.5, dash="dot"),
        annotation_text=f"Integrated {theo_int['A_sys']*100:.3f}%",
        annotation_font=dict(color=COL_INT, size=9),
        annotation_position="bottom right",
    )

    for label, color in [
        ("1 producer (SPOF)",  theme.STATE_COLORS["failed"]),
        ("2 producers",        theme.STATE_COLORS["setup"]),
        ("3+ producers",       theme.STATE_COLORS["processing"]),
    ]:
        fig.add_trace(go.Bar(
            x=[None], y=[None],
            name=label,
            marker_color=color,
            showlegend=True,
        ), row=2, col=1)

    # ── (3) System availability timeline (last replication) ───────────────────
    time_grid = exp["time_grid"]
    system_up = exp["system_up_last"]

    fig.add_trace(go.Scatter(
        x=time_grid,
        y=system_up.astype(float),
        mode="lines",
        line=dict(color=theme.STATE_COLORS["processing"], width=1.2, shape="hv"),
        fill="tozeroy",
        fillcolor="rgba(88,166,255,0.15)",
        name="System up",
        showlegend=False,
        hovertemplate="t = %{x:.1f} h<br>%{y:.0f} (1=up, 0=down)<extra></extra>",
    ), row=2, col=2)

    window = max(1, len(time_grid) // 100)
    rolling_avail = np.convolve(
        system_up.astype(float),
        np.ones(window) / window,
        mode="same",
    )
    fig.add_trace(go.Scatter(
        x=time_grid,
        y=rolling_avail,
        mode="lines",
        name=f"Rolling avg (window={window})",
        line=dict(color=theme.STATE_COLORS["processing"], width=2),
        showlegend=True,
        hovertemplate="t = %{x:.1f} h<br>Rolling A = %{y:.4f}<extra></extra>",
    ), row=2, col=2)

    # Both theoretical lines on the timeline
    fig.add_hline(
        y=theo_mid["A_sys"], row=2, col=2,
        line=dict(color=COL_MID, width=1.5, dash="dash"),
        annotation_text=f"Midpoint {theo_mid['A_sys']*100:.3f}%",
        annotation_font=dict(color=COL_MID, size=9),
        annotation_position="top right",
    )
    fig.add_hline(
        y=theo_int["A_sys"], row=2, col=2,
        line=dict(color=COL_INT, width=1.5, dash="dash"),
        annotation_text=f"Integrated {theo_int['A_sys']*100:.3f}%",
        annotation_font=dict(color=COL_INT, size=9),
        annotation_position="bottom right",
    )

    # ── Layout ────────────────────────────────────────────────────────────────
    fig.update_layout(
        paper_bgcolor=theme.BG,
        plot_bgcolor=theme.BG,
        font=dict(color=theme.TEXT, family="Inter, system-ui, sans-serif", size=12),
        height=900,
        title=dict(
            text=(
                "System Availability Analysis — "
                f"Theoretical vs Monte Carlo ({n_replications or N_REPLICATIONS} replications)"
            ),
            font=dict(size=18, color=theme.TEXT),
            x=0.02, y=0.99,
        ),
        legend=dict(
            bgcolor=theme.SURFACE, bordercolor=theme.BORDER, borderwidth=1,
            font=dict(color=theme.SUBTEXT, size=11),
            x=1.01, y=0.5,
        ),
        bargap=0.08,
        margin=dict(l=60, r=180, t=72, b=50),
    )

    theme.apply_axis_style(fig)

    fig.update_xaxes(title_text="System availability  A_sys",  row=1, col=1)
    fig.update_yaxes(title_text="Number of replications",      row=1, col=1)
    fig.update_xaxes(title_text="Component",  tickangle=45,    row=2, col=1,
                     tickfont=dict(size=8))
    fig.update_yaxes(title_text="A_comp  (availability)",      row=2, col=1)
    fig.update_xaxes(title_text="Time (h)",                    row=2, col=2)
    fig.update_yaxes(title_text="Available  (1 = yes, 0 = no)",
                     range=[-0.05, 1.1],                       row=2, col=2)

    for ann in fig.layout.annotations:
        if ann.text and ann.text[:1] == "(":
            ann.update(font=dict(color=theme.TEXT, size=13))

    return fig


if __name__ == "__main__":
    run()
