#!/usr/bin/env python3
"""
Full pipeline runner for the Simple Assembly Factory model.

Runs Generate → Simulate → Visualize in one command, reading all
parameters from config.yaml.

Usage
-----
  python run.py              # generate, simulate, then show charts
  python run.py --no-viz     # generate and simulate only
"""

import argparse
import os

# run.py sits at the model root, so Python already adds the root to sys.path.
# Package imports and utils work without any sys.path manipulation.
import utils
from generate.generate import generate_simple_assembly
from simulate.simulate import simulate

SIM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "simulate", "sim_output")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simple Assembly Factory — full pipeline (generate → simulate → visualize)"
    )
    parser.add_argument(
        "--no-viz", action="store_true",
        help="Skip the visualisation step and exit after writing CSVs",
    )
    args = parser.parse_args()

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    cfg = utils.load_config(config_path)
    sim = cfg.get("simulation", {})

    # ── Generate ──────────────────────────────────────────────────────────────
    print("Generating factory…")
    gen_result = generate_simple_assembly(config_path, export_csv=True)
    print(
        f"  {len(gen_result['components'])} components, "
        f"{len(gen_result['configurations'])} configurations, "
        f"{len(gen_result['layout_edges'])} layout edges"
    )

    # ── Simulate ──────────────────────────────────────────────────────────────
    print("Simulating…")
    results = simulate(
        gen_result,
        n_orders           = sim.get("n_orders",           10),
        tick_duration      = sim.get("tick_duration",      0.05),
        buffer_capacity    = sim.get("buffer_capacity",    20),
        order_interarrival = sim.get("order_interarrival", 10),
        n_ticks            = sim.get("n_ticks",            3000),
        log_buffers        = True,
    )

    os.makedirs(SIM_DIR, exist_ok=True)
    for name, df in results.items():
        path = os.path.join(SIM_DIR, f"{name}.csv")
        df.to_csv(path, index=False)
        print(f"  Wrote {path}  ({len(df):,} rows)")

    tp = results["throughput"]
    if not tp.empty:
        print(f"\nOrders completed : {len(tp)}")
        print(f"Total time span  : {tp['Time'].max():.3f} h")
        print(f"Mean lead time   : {tp['LeadTime'].mean():.3f} h")
    else:
        print("\nNo orders completed — consider increasing n_ticks or buffer_capacity.")

    # ── Visualise ─────────────────────────────────────────────────────────────
    if not args.no_viz:
        from simulate.visualize_sim import show
        show(SIM_DIR)


if __name__ == "__main__":
    main()
