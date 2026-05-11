#!/usr/bin/env python3
# Parameter sweep for the Simple Assembly Factory model.
#
# Runs generate + simulate for every combination of the sweep parameters
# defined in PARAM_GRID. Each output row is tagged with the run's parameters
# so results can be filtered and grouped during analysis.
#
# Output: sweep_output/{gen_stats,utilization,throughput,costs}.csv
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
    "n_products":         [1, 2, 4],
    "depth":              [1, 2, 3],
    "workstations_count": [2, 4, 8],
    "sharing_ratio":      [0.0, 0.5, 1.0],
}

# ── Fixed parameters ───────────────────────────────────────────────────────────
# Factory structure parameters — held constant across all runs.
# Randomness within ranges introduces natural variation inside each run.
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
    "seed":                    42,
}

# DTS simulation parameters — same for every run.
SIM_PARAMS: dict = {
    "n_orders":            10,
    "tick_duration":       0.05,   # hours per tick (~3 min)
    "buffer_capacity":     20,     # max units per non-raw component buffer
    "order_interarrival":  10,     # ticks between order releases
    "n_ticks":             3000,   # hard simulation limit
}

# ── Output directory ───────────────────────────────────────────────────────────
SWEEP_DIR: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep_output")

# ── Run sweep ──────────────────────────────────────────────────────────────────
def main():
    sweep_keys   = list(PARAM_GRID.keys())
    sweep_values = list(PARAM_GRID.values())
    combinations = list(itertools.product(*sweep_values))
    total_runs   = len(combinations)

    print(f"Starting sweep: {total_runs} combinations × {SIM_PARAMS['n_orders']} orders each")
    print(f"Sweep parameters: {', '.join(sweep_keys)}\n")

    all_gen_stats:    list[dict]          = []
    all_state_summary: list[pd.DataFrame] = []
    all_utilization:  list[pd.DataFrame] = []
    all_throughput:   list[pd.DataFrame] = []
    all_costs:        list[pd.DataFrame] = []

    for run_id, combo in enumerate(combinations, start=1):
        sweep_params = dict(zip(sweep_keys, combo))
        params       = {**FIXED_PARAMS, **sweep_params}

        # Tag columns prepended to every output row for this run.
        # Alpha (α = depth / workstations_count) is a derived topology metric:
        # α ≈ 1 → serial (one WS per BOM stage), α ≈ 0 → parallel (many WSs per stage).
        alpha = round(sweep_params["depth"] / sweep_params["workstations_count"], 4)
        tag = {"RunID": run_id, "alpha": alpha, **sweep_params}

        try:
            gen_result = generate_from_params(params)

            # Collect generation-phase structural metrics for the generation graphs.
            all_gen_stats.append({
                **tag,
                "n_raw":        sum(1 for c in gen_result["components"] if c.level == 0),
                "n_components": sum(1 for c in gen_result["components"] if c.level > 0),
                "n_configs":    len(gen_result["configurations"]),
                "n_edges":      len(gen_result["layout_edges"]),
            })

            sim_result = simulate(
                gen_result,
                n_orders           = SIM_PARAMS["n_orders"],
                tick_duration      = SIM_PARAMS["tick_duration"],
                buffer_capacity    = SIM_PARAMS["buffer_capacity"],
                order_interarrival = SIM_PARAMS["order_interarrival"],
                n_ticks            = SIM_PARAMS["n_ticks"],
                log_buffers        = False,   # skip per-tick buffer log in sweep
            )
        except Exception as e:
            print(f"  [SKIP] Run {run_id}/{total_runs} failed: {e}")
            continue

        # Compute per-tick state % (averaged across workstations) for the
        # sweep-wide CLEMATIS chart.  Stored compactly: one row per tick per run.
        states_run = sim_result["states"]
        if not states_run.empty:
            n_ws_run = states_run["Workstation"].nunique()
            tick_pct = (
                states_run.groupby(["Tick", "State"])
                .size()
                .unstack(fill_value=0)
                .div(n_ws_run)
                .mul(100)
                .reset_index()
            )
            for col in ["processing", "starved", "blocked"]:
                if col not in tick_pct.columns:
                    tick_pct[col] = 0.0
            tick_pct = tick_pct.rename(columns={
                "processing": "WorkingPct",
                "starved":    "StarvedPct",
                "blocked":    "BlockedPct",
            })[["Tick", "WorkingPct", "StarvedPct", "BlockedPct"]]
            tagged_states = tick_pct.copy()
            for col, val in reversed(tag.items()):
                tagged_states.insert(0, col, val)
            all_state_summary.append(tagged_states)

        # Tag each DataFrame and accumulate.
        for df, acc in [
            (sim_result["utilization"], all_utilization),
            (sim_result["throughput"],  all_throughput),
            (sim_result["costs"],       all_costs),
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
        "gen_stats":     [pd.DataFrame(all_gen_stats)]   if all_gen_stats   else [],
        "state_summary": all_state_summary,
        "utilization":   all_utilization,
        "throughput":    all_throughput,
        "costs":         all_costs,
    }

    for name, frames in outputs.items():
        if not frames:
            print(f"  [WARN] No data for {name}.csv — all runs may have failed.")
            continue
        path = os.path.join(SWEEP_DIR, f"{name}.csv")
        pd.concat(frames, ignore_index=True).to_csv(path, index=False)
        print(f"  Wrote {path}")

    print(f"\nSweep complete — results in {SWEEP_DIR}/")


if __name__ == "__main__":
    main()
