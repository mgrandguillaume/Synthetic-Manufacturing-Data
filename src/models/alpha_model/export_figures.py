#!/usr/bin/env python3
"""
Export all model figures in report style (white background, print-friendly colours).

Reads the pre-computed CSV files that are already on disk and re-renders each
figure using report_theme.py instead of the normal dark UI theme.

By default each figure is saved as a self-contained interactive HTML file —
no extra packages required.  Open the HTML in any browser to inspect, zoom,
and screenshot for your report.

Pass --static to also write PNG + SVG files for the Plotly figures.  This
requires Kaleido:
    pip install kaleido

Note: the factory layout graph (--generate) is a Pyvis/vis.js figure and can
only be exported as HTML — PNG/SVG is not available for it.

Usage
-----
    # From the model root:
    python export_figures.py                  # generate + sweep + verify → HTML (fast)
    python export_figures.py --static         # same + PNG + SVG for Plotly figures
    python export_figures.py --generate       # factory layout graph only
    python export_figures.py --sweep          # sweep only
    python export_figures.py --verify         # verification + monotonicity only
    python export_figures.py --availability   # availability (re-runs Monte Carlo)
    python export_figures.py --all            # everything

Output
------
    export/
        generation.html
        sweep.html
        verification_diagnostics.html
        verification_monotonicity.html
        availability.html                     (only with --availability / --all)

        # also with --static (Plotly figures only):
        sweep.png / sweep.svg
        verification_diagnostics.png / verification_diagnostics.svg
        …

Prerequisites
-------------
CSV data must exist on disk before running:
    - Generation:    run generate in the UI, or:  python run.py --generate-only
    - Sweep:         run the sweep in the UI, or:  python run.py --sweep
    - Verification:  run verification in the UI, or:  python run.py --verify-only
    - Availability:  generated on the fly when --availability / --all is passed.
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser

# ── Path setup ─────────────────────────────────────────────────────────────────
_MODEL_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _MODEL_ROOT)

# ── Patch the live theme module BEFORE any visualiser is imported ──────────────
#
# All visualiser modules reference shared_utils.theme at *call* time (not import
# time), so replacing the module's attributes here — before the first show() /
# plot_*() call — is sufficient to make every figure use the report palette.
import shared_utils.theme as _theme
from shared_utils import report_theme as _rt


def _apply_report_theme() -> None:
    """Overwrite the live theme module with report-style values."""
    _theme.BG               = _rt.BG
    _theme.SURFACE          = _rt.SURFACE
    _theme.BORDER           = _rt.BORDER
    _theme.TEXT             = _rt.TEXT
    _theme.SUBTEXT          = _rt.SUBTEXT
    _theme.PALETTE          = _rt.PALETTE
    _theme.STATE_COLORS     = _rt.STATE_COLORS
    _theme.COST_COLORS      = _rt.COST_COLORS
    _theme.palette          = _rt.palette
    _theme.apply_axis_style = _rt.apply_axis_style


# ── Constants ──────────────────────────────────────────────────────────────────

_EXPORT_DIR   = os.path.join(_MODEL_ROOT, "export")
_SWEEP_DIR    = os.path.join(_MODEL_ROOT, "analysis", "sweep", "sweep_output")
_VERIFY_DIR   = os.path.join(
    _MODEL_ROOT, "analysis", "model_verification", "verification_output"
)
_GENERATE_DIR = os.path.join(_MODEL_ROOT, "engine", "generate", "gen_output")

# Static image settings (only used with --static)
_EXPORT_WIDTH = 1_200
_EXPORT_SCALE = 2       # effective 2 400 px wide ≈ 150 dpi on A4


# ── Save helpers ───────────────────────────────────────────────────────────────

def _save_html(fig, name: str) -> None:
    """Write a self-contained interactive HTML file.  No extra packages needed."""
    os.makedirs(_EXPORT_DIR, exist_ok=True)
    path = os.path.join(_EXPORT_DIR, f"{name}.html")
    fig.write_html(path, include_plotlyjs="cdn")
    print(f"  ✓  {path}")


def _save_static(fig, name: str) -> None:
    """Write PNG + SVG.  Requires kaleido (pip install kaleido)."""
    os.makedirs(_EXPORT_DIR, exist_ok=True)
    height = int(fig.layout.height or 800)

    for ext, scale in [("png", _EXPORT_SCALE), ("svg", 1)]:
        path = os.path.join(_EXPORT_DIR, f"{name}.{ext}")
        try:
            fig.write_image(path, width=_EXPORT_WIDTH, height=height, scale=scale)
            print(f"  ✓  {path}")
        except Exception as exc:
            print(f"  ✗  {ext.upper()} export failed ({name}): {exc}")
            if "kaleido" in str(exc).lower():
                print("       Install it with:  pip install kaleido")
            break   # if PNG fails SVG will too — skip it


def _save(fig, name: str, static: bool) -> None:
    # Write HTML first, then open as a local file:// URL — no server needed.
    _save_html(fig, name)
    html_path = os.path.join(_EXPORT_DIR, f"{name}.html")
    webbrowser.open(f"file:///{html_path.replace(os.sep, '/')}")
    if static:
        _save_static(fig, name)


# ── Individual exporters ───────────────────────────────────────────────────────

def _export_generation() -> None:
    """Build and save the factory layout graph as a report-style HTML file.

    Reads the pre-generated CSVs from engine/generate/gen_output/.
    Note: Pyvis/vis.js figures cannot be exported as PNG/SVG — HTML only.
    """
    import pandas as pd
    from types import SimpleNamespace
    from engine.generate.visualize_gen import build_html

    print("\n[generate] building factory layout figure from gen_output CSVs…")

    layout_df = pd.read_csv(os.path.join(_GENERATE_DIR, "layout.csv"))
    ws_df     = pd.read_csv(os.path.join(_GENERATE_DIR, "workstations.csv"))
    cfg_df    = pd.read_csv(os.path.join(_GENERATE_DIR, "configurations.csv"))
    bom_df    = pd.read_csv(os.path.join(_GENERATE_DIR, "bom.csv"))

    gen_result = {
        "workstations": [
            SimpleNamespace(id=row["ID"], name=row["Name"], type=row["Type"])
            for _, row in ws_df.iterrows()
        ],
        "layout_edges": [
            SimpleNamespace(
                origin=row["Origin"], destination=row["Destination"],
                capacity=row["Capacity"], cost=row["Cost"],
            )
            for _, row in layout_df.iterrows()
        ],
        "configurations": [
            SimpleNamespace(
                workstation=row["Workstation"], component=row["Component"],
                processing_time=row["ProcessingTime"], setup_time=row["SetupTime"],
            )
            for _, row in cfg_df.iterrows()
        ],
        "bom_edges": [
            SimpleNamespace(input=row["Input"], output=row["Output"])
            for _, row in bom_df.iterrows()
        ],
    }

    html = build_html(gen_result, height="900px", report_theme=True)

    os.makedirs(_EXPORT_DIR, exist_ok=True)
    path = os.path.join(_EXPORT_DIR, "generation.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"  ✓  {path}")
    webbrowser.open(f"file:///{path.replace(os.sep, '/')}")


def _export_sweep(static: bool) -> None:
    from analysis.sweep.visualize_sweep import show

    print("\n[sweep] building figure from sweep_output CSVs…")
    fig = show(_SWEEP_DIR)
    fig.update_layout(margin=dict(r=220))
    _save(fig, "sweep", static)


def _export_verification(static: bool) -> None:
    from analysis.model_verification.visualize_verification import show, plot_monotonicity

    print("\n[verify] building verification-diagnostics figure…")
    _save(show(_VERIFY_DIR), "verification_diagnostics", static)

    mono_path = os.path.join(_VERIFY_DIR, "val_monotonicity.csv")
    if os.path.exists(mono_path):
        print("\n[verify] building monotonicity figure…")
        _save(plot_monotonicity(_VERIFY_DIR, n_cols=2), "verification_monotonicity", static)
    else:
        print(
            "\n[verify] val_monotonicity.csv not found — skipping monotonicity chart.\n"
            "         Run verification first (UI → Verify, or python run.py --verify-only)."
        )


def _export_availability(static: bool) -> None:
    """Re-run the availability analysis and export the resulting figure."""
    import math
    from shared_utils import utils, validate_config
    from engine.generate.generate import generate_simple_assembly
    from analysis.use_cases.availability_analysis import theoretical_integrated, experimental
    from analysis.use_cases.availability_analysis.availability import (
        _show_plots,
        WARMUP_MTBF_MULT,
        HORIZON_MTBF_MULT,
        POINTS_PER_MIN_MTTR,
        N_TIMEPOINTS_FLOOR,
    )

    config_path = os.path.join(_MODEL_ROOT, "config.yaml")
    cfg      = utils.load_config(config_path)
    validate_config.validate(cfg)

    seed     = cfg.get("metadata", {}).get("seed", 42)
    fail_cfg = cfg.get("failures", {})

    N_REPLICATIONS = 5_000

    if not fail_cfg.get("enabled", False):
        print(
            "\n[availability] SKIPPED — failures.enabled = false in config.yaml.\n"
            "               Set failures.enabled: true and re-run with --availability."
        )
        return

    print("\n[availability] generating factory…")
    gen_result = generate_simple_assembly(config_path, export_csv=False)

    beta_rep   = (float(fail_cfg["weibull_beta"][0])   + float(fail_cfg["weibull_beta"][1]))   / 2
    lambda_rep = (float(fail_cfg["weibull_lambda"][0]) + float(fail_cfg["weibull_lambda"][1])) / 2
    mttr_min   = float(fail_cfg["mttr"][0])
    mtbf_h     = lambda_rep * math.gamma(1.0 + 1.0 / beta_rep)

    warmup_hours  = WARMUP_MTBF_MULT  * mtbf_h
    horizon_hours = warmup_hours + HORIZON_MTBF_MULT * mtbf_h
    n_timepoints  = max(
        N_TIMEPOINTS_FLOOR,
        int(math.ceil((horizon_hours - warmup_hours) / (mttr_min / POINTS_PER_MIN_MTTR))) + 1,
    )

    print(
        f"[availability] running Monte Carlo  "
        f"({N_REPLICATIONS} reps × {horizon_hours:.0f} h, "
        f"warm-up {warmup_hours:.0f} h)…"
    )
    theo_int = theoretical_integrated.compute(gen_result, fail_cfg)
    exp_res  = experimental.run(
        gen_result, fail_cfg,
        n_replications = N_REPLICATIONS,
        horizon_hours  = horizon_hours,
        warmup_hours   = warmup_hours,
        n_timepoints   = n_timepoints,
        seed           = seed,
    )
    print("[availability] Monte Carlo done.")

    fig = _show_plots(theo_int, exp_res, gen_result, n_replications=N_REPLICATIONS)
    _save(fig, "availability", static)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export Assembly Factory figures in report style "
            "(white background, print-friendly colours)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Default (no flags): exports generate + sweep + verification as HTML files.\n"
            "Add --static to also write PNG + SVG for Plotly figures (requires:  pip install kaleido).\n"
            "The factory layout (--generate) is HTML-only (Pyvis/vis.js, no PNG/SVG).\n"
            "Add --availability or --all to include the availability figure,\n"
            "which re-runs the full Monte Carlo analysis (~1–3 min)."
        ),
    )
    parser.add_argument("--generate",     action="store_true",
                        help="Export the factory layout graph (HTML only — Pyvis figure)")
    parser.add_argument("--sweep",        action="store_true",
                        help="Export the parameter-sweep figure")
    parser.add_argument("--verify",       action="store_true",
                        help="Export the verification-diagnostics and monotonicity figures")
    parser.add_argument("--availability", action="store_true",
                        help="Export the availability figure (re-runs Monte Carlo)")
    parser.add_argument("--all",          action="store_true",
                        help="Export all figures (generate + sweep + verify + availability)")
    parser.add_argument("--static",       action="store_true",
                        help="Also write PNG + SVG files for Plotly figures (requires kaleido)")
    args = parser.parse_args()

    no_flags   = not any([args.generate, args.sweep, args.verify, args.availability, args.all])
    do_generate = args.generate or args.all or no_flags
    do_sweep    = args.sweep    or args.all or no_flags
    do_verify   = args.verify   or args.all or no_flags
    do_avail    = args.availability or args.all

    _apply_report_theme()

    if do_generate:
        try:
            _export_generation()
        except FileNotFoundError as exc:
            print(f"\n[generate] Data not found: {exc}")
            print("           Run generate first (UI → Generate, or python run.py --generate-only).")
        except Exception as exc:
            print(f"\n[generate] ERROR: {exc}")

    if do_sweep:
        try:
            _export_sweep(args.static)
        except FileNotFoundError as exc:
            print(f"\n[sweep] Data not found: {exc}")
            print("        Run the sweep first (UI → Sweep, or python run.py --sweep).")
        except Exception as exc:
            print(f"\n[sweep] ERROR: {exc}")

    if do_verify:
        try:
            _export_verification(args.static)
        except FileNotFoundError as exc:
            print(f"\n[verify] Data not found: {exc}")
            print("         Run verification first (UI → Verify, or python run.py --verify-only).")
        except Exception as exc:
            print(f"\n[verify] ERROR: {exc}")

    if do_avail:
        try:
            _export_availability(args.static)
        except Exception as exc:
            print(f"\n[availability] ERROR: {exc}")

    print(f"\nDone.  Files written to:  {_EXPORT_DIR}")


if __name__ == "__main__":
    main()
