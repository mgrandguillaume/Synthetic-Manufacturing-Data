#!/usr/bin/env python3
# Parameter sweep for the Simple Assembly Factory model.
#
# Runs generate + simulate for every combination of the sweep parameters
# defined in PARAM_GRID. Each output row is tagged with the run's parameters
# so results can be filtered and grouped during analysis.
#
# Output: sweep_output/{gantt,utilization,throughput,costs,wait_times}.csv
#
# Run:  python sweep.py
# Dependencies: pip install pyyaml pandas

import os
import sys
import itertools

import pandas as pd

# ── Imports from sibling packages ─────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "generate"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "simulate"))

from generate import generate_from_params  # noqa: E402
from simulate import simulate              # noqa: E402

# ── Sweep parameter grid ───────────────────────────────────────────────────────
# These are the structural parameters we want to study.
# All combinations are tested (162 total).
PARAM_GRID: dict[str, list] = {
    "n_products":        [1, 2, 4],
    "depth":             [1, 2, 3],
    "workstations_count": [2, 4, 8],
    "sharing_ratio":     [0.0, 0.5, 1.0],
    "topology":          ["parallel", "linear"],
}

# ── Fixed parameters ───────────────────────────────────────────────────────────
# These match the ranges in config.yaml and are held constant across all runs.
# Randomness within these ranges introduces natural variation inside each run.
FIXED_PARAMS: dict = {
    "branching":               [2, 3],
    "quantity":                [1, 3],
    "producers_per_component": [1, 2],
    "processing_time":         [0.1, 0.5],
    "setup_time":              [0.5, 2.0],
    "setup_cost":              [50,  300],
    "operating_cost":          [2,   15],
    "flow_capacity":           [50,  200],
    "transport_cost":          [0.5, 5.0],
    "seed":                    42,         # fixed seed → reproducible runs
}

N_ORDERS: int = 10

# ── Output directory ───────────────────────────────────────────────────────────
SWEEP_DIR: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep_output")

# ── Run sweep ──────────────────────────────────────────────────────────────────
def main():
    sweep_keys   = list(PARAM_GRID.keys())
    sweep_values = list(PARAM_GRID.values())
    combinations = list(itertools.product(*sweep_values))
    total_runs   = len(combinations)

    print(f"Starting sweep: {total_runs} combinations × {N_ORDERS} orders each")
    print(f"Sweep parameters: {', '.join(sweep_keys)}\n")

    # Accumulators for each output table
    all_gantt:       list[pd.DataFrame] = []
    all_utilization: list[pd.DataFrame] = []
    all_throughput:  list[pd.DataFrame] = []
    all_costs:       list[pd.DataFrame] = []
    all_wait_times:  list[pd.DataFrame] = []

    for run_id, combo in enumerate(combinations, start=1):
        sweep_params = dict(zip(sweep_keys, combo))
        params       = {**FIXED_PARAMS, **sweep_params}

        # Tag columns prepended to every output row for this run
        tag = {"RunID": run_id, **sweep_params}

        try:
            gen_result = generate_from_params(params)
            sim_result = simulate(gen_result, n_orders=N_ORDERS)
        except Exception as e:
            print(f"  [SKIP] Run {run_id}/{total_runs} failed: {e}")
            continue

        # Tag each DataFrame and accumulate
        for df, acc in [
            (sim_result["gantt"],       all_gantt),
            (sim_result["utilization"], all_utilization),
            (sim_result["throughput"],  all_throughput),
            (sim_result["costs"],       all_costs),
            (sim_result["wait_times"],  all_wait_times),
        ]:
            tagged = df.copy()
            for col, val in reversed(tag.items()):   # insert tag cols at front
                tagged.insert(0, col, val)
            acc.append(tagged)

        if run_id % 20 == 0 or run_id == total_runs:
            print(f"  Progress: {run_id}/{total_runs} runs complete")

    # ── Write combined CSVs ────────────────────────────────────────────────────
    os.makedirs(SWEEP_DIR, exist_ok=True)

    outputs = {
        "gantt":       all_gantt,
        "utilization": all_utilization,
        "throughput":  all_throughput,
        "costs":       all_costs,
        "wait_times":  all_wait_times,
    }

    for name, frames in outputs.items():
        path = os.path.join(SWEEP_DIR, f"{name}.csv")
        pd.concat(frames, ignore_index=True).to_csv(path, index=False)
        print(f"  Wrote {path}")

    print(f"\nSweep complete — results in {SWEEP_DIR}/")


if __name__ == "__main__":
    main()
