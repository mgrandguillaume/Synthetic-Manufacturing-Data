#!/usr/bin/env python3
"""
Full pipeline runner for the Optimized Assembly Factory model.

Runs Generate → Sweep → Visualize in one command, reading all
parameters from config.yaml.

Usage
-----
  python run.py              # generate, sweep, then show sweep charts
  python run.py --no-viz     # generate and sweep only
"""

import argparse
import os

# run.py sits at the model root, so Python already adds the root to sys.path.
# Package imports and utils work without any sys.path manipulation.
from generate.generate import generate_simple_assembly
from sweep.sweep import main as run_sweep

SWEEP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep", "sweep_output")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Optimized Assembly Factory — full pipeline (generate → sweep → visualize)"
    )
    parser.add_argument(
        "--no-viz", action="store_true",
        help="Skip the visualisation step and exit after writing CSVs",
    )
    args = parser.parse_args()

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

    # ── Generate ──────────────────────────────────────────────────────────────
    print("Generating factory…")
    gen_result = generate_simple_assembly(config_path, export_csv=True)
    print(
        f"  {len(gen_result['components'])} components, "
        f"{len(gen_result['configurations'])} configurations, "
        f"{len(gen_result['layout_edges'])} layout edges"
    )

    # ── Sweep ─────────────────────────────────────────────────────────────────
    run_sweep()

    # ── Visualise ─────────────────────────────────────────────────────────────
    if not args.no_viz:
        from sweep.visualize_sweep import show
        show(SWEEP_DIR)


if __name__ == "__main__":
    main()
