#!/usr/bin/env python3
"""
System availability analysis — theoretical vs experimental.

Runs two independent estimates of steady-state system availability and
compares them:

  1. Theoretical (integrated)  — exact RBD calculation using E[A_ws]
                                  integrated over the full (β, λ) distributions
                                  with mean MTTR.
  2. Experimental              — Monte Carlo simulation of Weibull failure-repair
                                  cycles.

Both use the same factory topology (from gen_result) and the same failure
configuration (from config.yaml).

Usage
-----
  uv run src/models/alpha_model/analysis/use_cases/availability_analysis/availability.py

Output
------
  Console  : summary table with theoretical (integrated), experimental, verdict
  Plotly   : three-panel figure:
               (1) Histogram of per-replication availability + theoretical line
               (2) Outage duration distribution — histogram of system-down episode
                   lengths across all replications, with mean annotation
               (3) Monte Carlo convergence — cumulative A_sys vs replication count
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
from . import theoretical_integrated, experimental
from shared_utils import theme

# ── Config ────────────────────────────────────────────────────────────────────
_CONFIG_PATH = os.path.join(_MODEL_ROOT, "config.yaml")

# Monte Carlo settings — increase n_replications for a tighter CI at the
# cost of longer runtime (~1 min for 200 reps on a typical laptop).
N_REPLICATIONS = 1000

# The simulation horizon and warm-up are scaled to the workstation MTBF rather
# than hardcoded.  A fixed 2000 h horizon is meaningless across configs: it is
# far too short for a 1500 h MTBF (too few failure-repair cycles observed) and
# wastefully long for a 50 h one.  Scaling keeps the estimate well-conditioned
# regardless of the configured Weibull parameters.
WARMUP_MTBF_MULT  = 4.0    # discard the first ~4x MTBF as start-up transient
HORIZON_MTBF_MULT = 50.0   # then measure ~50 failure-repair cycles

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
    gap     = min(abs(theo - lo), abs(theo - hi))
    gap_pp  = gap * 100
    if gap_pp < 3.0:
        return f"NEAR PASS - {gap_pp:.2f}pp outside CI"
    if gap_pp < 10.0:
        return f"DIVERGE - theoretical {gap_pp:.2f}pp outside CI  (check parameter ranges)"
    return f"FAIL - theoretical {gap_pp:.2f}pp outside CI  (likely a modelling error)"


# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> None:
    # ── Load and validate config ───────────────────────────────────────────────
    cfg = utils.load_config(_CONFIG_PATH)
    validate_config.validate(cfg)

    seed     = cfg.get("metadata", {}).get("seed", 42)
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

    # ── Theoretical (integrated) ──────────────────────────────────────────────
    print("\nComputing theoretical availability (integrated)...")
    theo_int = theoretical_integrated.compute(gen_result, fail_cfg)

    # ── Scale the simulation horizon to the MTBF ──────────────────────────────
    # Compute representative MTBF from midpoint params for horizon/warmup scaling.
    beta_rep   = (float(fail_cfg["weibull_beta"][0])   + float(fail_cfg["weibull_beta"][1]))   / 2
    lambda_rep = (float(fail_cfg["weibull_lambda"][0]) + float(fail_cfg["weibull_lambda"][1])) / 2
    mttr_rep   = (float(fail_cfg["mttr"][0])           + float(fail_cfg["mttr"][1]))           / 2
    mtbf_h     = lambda_rep * math.gamma(1.0 + 1.0 / beta_rep)
    mttr_min   = float(fail_cfg["mttr"][0])

    warmup_hours  = WARMUP_MTBF_MULT * mtbf_h
    horizon_hours = warmup_hours + HORIZON_MTBF_MULT * mtbf_h

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
        seed           = seed,
    )
    print("  Done.")

    # ── Console report ────────────────────────────────────────────────────────
    ci_lo, ci_hi = exp["A_sys_ci95"]

    _print_separator("=")
    print("  SYSTEM AVAILABILITY ANALYSIS")
    _print_separator("=")

    print(f"\n  Weibull parameters  (midpoint values used for horizon scaling)")
    print(f"    beta     = {beta_rep:.3f}  (range {fail_cfg['weibull_beta']})")
    print(f"    lambda   = {lambda_rep:.1f} h  (range {fail_cfg['weibull_lambda']})")
    print(f"    MTBF     = {mtbf_h:.2f} h  per workstation")
    print(f"    mean MTTR = {mttr_rep:.2f} h  per workstation")
    print(f"    A_ws (integrated E[A_ws]) = {_fmt_pct(theo_int['A_ws'])}")

    _print_separator()
    print(f"  {'':30s}  {'Integrated':>10s}  {'Experimental':>12s}")
    _print_separator()
    print(
        f"  {'System availability  A_sys':30s}  "
        f"{_fmt_pct(theo_int['A_sys']):>10s}  "
        f"{_fmt_pct(exp['A_sys_mean']):>12s}"
    )
    print(
        f"  {'95% CI (experimental)':30s}  "
        f"{'--':>10s}  "
        f"[{_fmt_pct(ci_lo)}, {_fmt_pct(ci_hi)}]"
    )
    print(
        f"  {'Std dev (across runs)':30s}  "
        f"{'--':>10s}  "
        f"{_fmt_pct(exp['A_sys_std']):>12s}"
    )
    _print_separator()
    print(f"  Verdict: {_divergence_verdict(theo_int['A_sys'], ci_lo, ci_hi)}")
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
    _show_plots(theo_int, exp, gen_result,
                n_replications=N_REPLICATIONS).show()


def _show_plots(theo_int: dict, exp: dict, gen_result: dict,
                n_replications: int | None = None):
    """Build and return a three-panel Plotly figure."""

    COL_INT = theme.STATE_COLORS["failed"]   # red — integrated theoretical

    fig = make_subplots(
        rows=3, cols=1,
        subplot_titles=[
            "(1) Per-replication availability distribution",
            "(2) Outage duration distribution  (all replications)",
            "(3) Monte Carlo convergence",
        ],
        vertical_spacing=0.10,
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

    fig.add_vline(
        x=exp["A_sys_mean"], row=1, col=1,
        line=dict(color=theme.STATE_COLORS["processing"], width=2.5, dash="solid"),
        annotation_text=f"MC mean: {exp['A_sys_mean']*100:.3f}%",
        annotation_font=dict(color=theme.STATE_COLORS["processing"], size=10),
        annotation_position="top right",
    )
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
    fig.add_vline(
        x=theo_int["A_sys"], row=1, col=1,
        line=dict(color=COL_INT, width=2, dash="dash"),
        annotation_text=f"Theoretical: {theo_int['A_sys']*100:.3f}%",
        annotation_font=dict(color=COL_INT, size=10),
        annotation_position="top left",
    )

    # ── (2) Outage duration distribution ─────────────────────────────────────
    outage_h = exp.get("outage_durations_h", [])
    if outage_h:
        mean_outage = float(np.mean(outage_h))
        fig.add_trace(go.Histogram(
            x=outage_h,
            nbinsx=40,
            name="Outage durations",
            marker_color=theme.STATE_COLORS["failed"],
            marker_line_color=theme.BG,
            marker_line_width=0.5,
            opacity=0.85,
            showlegend=False,
            hovertemplate="Duration: %{x:.2f} h<br>Count: %{y}<extra></extra>",
        ), row=2, col=1)
        fig.add_vline(
            x=mean_outage, row=2, col=1,
            line=dict(color=theme.STATE_COLORS["failed"], width=2, dash="dash"),
            annotation_text=f"Mean outage: {mean_outage:.2f} h",
            annotation_font=dict(color=theme.STATE_COLORS["failed"], size=10),
            annotation_position="top right",
        )
    else:
        # No outages recorded — factory is always up
        fig.add_annotation(
            text="No system outages recorded across all replications",
            xref="x2", yref="y2", x=0.5, y=0.5,
            showarrow=False,
            font=dict(color=theme.SUBTEXT, size=13),
        )

    # ── (3) Monte Carlo convergence ───────────────────────────────────────────
    # Shows how the cumulative mean A_sys evolves as more replications are added,
    # together with a narrowing 95% CI band and the theoretical reference line.
    A_arr    = np.array(exp["A_per_run"])
    n_runs   = np.arange(1, len(A_arr) + 1)
    cum_mean = np.cumsum(A_arr) / n_runs

    # Running standard deviation via the online variance formula
    cum_sq_mean = np.cumsum(A_arr ** 2) / n_runs
    cum_var     = np.maximum(cum_sq_mean - cum_mean ** 2, 0.0)
    cum_std     = np.sqrt(cum_var)
    ci_half     = 1.96 * cum_std / np.sqrt(n_runs)
    conv_lo     = cum_mean - ci_half
    conv_hi     = cum_mean + ci_half

    # CI band (shaded)
    fig.add_trace(go.Scatter(
        x=np.concatenate([n_runs, n_runs[::-1]]),
        y=np.concatenate([conv_hi, conv_lo[::-1]]),
        fill="toself",
        fillcolor="rgba(88,166,255,0.12)",
        line=dict(width=0),
        showlegend=False,
        hoverinfo="skip",
        name="95% CI band",
    ), row=3, col=1)

    # Cumulative mean line
    fig.add_trace(go.Scatter(
        x=n_runs,
        y=cum_mean,
        mode="lines",
        name="Cumulative MC mean",
        line=dict(color=theme.STATE_COLORS["processing"], width=2),
        hovertemplate="Run %{x}<br>Cumulative A_sys = %{y:.5f}<extra></extra>",
    ), row=3, col=1)

    # Theoretical reference line
    fig.add_hline(
        y=theo_int["A_sys"], row=3, col=1,
        line=dict(color=COL_INT, width=1.5, dash="dash"),
        annotation_text=f"Theoretical {theo_int['A_sys']*100:.3f}%",
        annotation_font=dict(color=COL_INT, size=9),
        annotation_position="top right",
    )

    # ── Layout ────────────────────────────────────────────────────────────────
    n_reps = n_replications or N_REPLICATIONS
    fig.update_layout(
        paper_bgcolor=theme.BG,
        plot_bgcolor=theme.BG,
        font=dict(color=theme.TEXT, family="Inter, system-ui, sans-serif", size=12),
        height=1050,
        title=dict(
            text=(
                "System Availability Analysis — "
                f"Theoretical vs Monte Carlo  ({n_reps} replications)"
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

    fig.update_xaxes(title_text="System availability  A_sys",      row=1, col=1)
    fig.update_yaxes(title_text="Number of replications",          row=1, col=1)
    fig.update_xaxes(title_text="Outage duration  (hours)",        row=2, col=1)
    fig.update_yaxes(title_text="Count",                           row=2, col=1)
    fig.update_xaxes(title_text="Number of replications",          row=3, col=1)
    fig.update_yaxes(title_text="Cumulative A_sys",                row=3, col=1)

    for ann in fig.layout.annotations:
        if ann.text and ann.text[:1] == "(":
            ann.update(font=dict(color=theme.TEXT, size=13))

    return fig


if __name__ == "__main__":
    run()
