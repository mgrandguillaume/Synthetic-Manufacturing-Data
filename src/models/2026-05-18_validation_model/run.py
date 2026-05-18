#!/usr/bin/env python3
"""
Full pipeline runner for the Assembly Factory model.

Runs Generate → Sweep → Visualize in one command, reading all
parameters from config.yaml.  Pass --validate to also run the
validation suite after the sweep, or --validate-only to skip
generate/sweep and jump straight to validation.

Usage
-----
  python run.py                   # generate, sweep, then show sweep charts
  python run.py --no-viz          # generate and sweep only (no charts)
  python run.py --validate        # generate → sweep → sweep charts → validate
  python run.py --validate-only   # validation suite only (sweep output must exist)
"""

import argparse
import os
import sys

# run.py sits at the model root, so Python already adds the root to sys.path.
# Package imports and utils work without any sys.path manipulation.
from generate.generate import generate_simple_assembly
from sweep.sweep import main as run_sweep

SWEEP_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep", "sweep_output")
VALIDATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "validate", "validation_output")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Assembly Factory — full pipeline (generate → sweep → visualize → validate)"
        )
    )
    parser.add_argument(
        "--no-viz",
        action="store_true",
        help="Skip the sweep visualisation step and exit after writing CSVs.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help=(
            "Run the full pipeline (generate → sweep → sweep charts) and then "
            "execute the validation suite."
        ),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        dest="validate_only",
        help=(
            "Skip generate / sweep and run the validation suite immediately. "
            "Sweep output (sweep/sweep_output/) must already exist."
        ),
    )
    args = parser.parse_args()

    # ── Validate-only mode: skip generate/sweep ────────────────────────────────
    if args.validate_only:
        _run_validation(show_charts=True)
        return

    # ── Generate ───────────────────────────────────────────────────────────────
    print("Generating factory…")
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    gen_result  = generate_simple_assembly(config_path, export_csv=True)
    print(
        f"  {len(gen_result['components'])} components, "
        f"{len(gen_result['configurations'])} configurations, "
        f"{len(gen_result['layout_edges'])} layout edges"
    )

    # ── Sweep ──────────────────────────────────────────────────────────────────
    run_sweep()

    # ── Sweep visualisation ────────────────────────────────────────────────────
    if not args.no_viz:
        from sweep.visualize_sweep import show
        show(SWEEP_DIR)

    # ── Validation (optional) ──────────────────────────────────────────────────
    if args.validate:
        _run_validation(show_charts=not args.no_viz)


def _run_validation(show_charts: bool = True) -> None:
    """Import and run the validation suite."""
    print("\n" + "═" * 72)
    print("  Running validation suite…")
    print("═" * 72 + "\n")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(VALIDATE_DIR, exist_ok=True)
    from validate.validate import run_all
    passed = run_all(show_charts=show_charts, report_dir=VALIDATE_DIR)
    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
