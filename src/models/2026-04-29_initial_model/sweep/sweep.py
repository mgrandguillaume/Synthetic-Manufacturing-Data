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
import yaml

# ── Imports from sibling packages ─────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generate"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "simulate"))

from generate import generate_from_params  # noqa: E402
from simulate import simulate              # noqa: E402

# ── Load config ────────────────────────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
with open(CONFIG_PATH) as _f:
    _cfg = yaml.safe_load(_f)

# ── Parameter expansion helper ─────────────────────────────────────────────────
def _expand(val) -> list:
    """
    Convert a sweep parameter value from config.yaml into a flat list of values.

    Three formats are supported:
      fixed   scalar        depth: 2
              → [2]

      list    explicit      depth: [1, 2, 3]
              → [1, 2, 3]

      range   min/max/step  workstations_count: {min: 2, max: 8, step: 2}
              → [2, 4, 6, 8]
    """
    if isinstance(val, dict):
        start, stop, step = val["min"], val["max"], val["step"]
        result, v = [], start
        while v <= stop + step * 1e-9:   # small epsilon handles float rounding
            result.append(round(v, 10))
            v += step
        return result
    elif isinstance(val, list):
        return val
    else:
        return [val]

# ── Sweep parameter grid (from config.yaml → sweep:) ──────────────────────────
# Each entry is expanded to a list using _expand(); every combination is tested.
PARAM_GRID: dict[str, list] = {k: _expand(v) for k, v in _cfg["sweep"].items()}

# ── Fixed parameters (from config.yaml) ───────────────────────────────────────
# Held constant across all runs; randomness within ranges gives natural variation.
FIXED_PARAMS: dict = {
    "branching":               _cfg["bom"]["branching"],
    "quantity":                _cfg["bom"]["quantity"],
    "producers_per_component": _cfg["configurations"]["producers_per_component"],
    "processing_time":         _cfg["configurations"]["processing_time"],
    "setup_time":              _cfg["configurations"]["setup_time"],
    "setup_cost":              _cfg["configurations"]["setup_cost"],
    "operating_cost":          _cfg["configurations"]["operating_cost"],
    "flow_capacity":           _cfg["layout"]["flow_capacity"],
    "transport_cost":          _cfg["layout"]["transport_cost"],
    "seed":                    _cfg["metadata"].get("seed"),
}

# ── Simulation parameters (from config.yaml → simulation:) ────────────────────
SIM_PARAMS: dict = {
    "n_orders":           _cfg["simulation"]["n_orders"],
    "tick_duration":      _cfg["simulation"]["tick_duration"],
    "buffer_capacity":    _cfg["simulation"]["buffer_capacity"],
    "order_interarrival": _cfg["simulation"]["order_interarrival"],
    "n_ticks":            _cfg["simulation"]["n_ticks"],
}

# ── Output directory ───────────────────────────────────────────────────────────
SWEEP_DIR: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep_output")

# ── Run sweep ──────────────────────────────────────────────────────────────────
def main():
    sweep_keys   = list(PARAM_GRID.keys())
    sweep_values = list(PARAM_GRID.values())
    all_combos   = list(itertools.product(*sweep_values))

    # α = depth / workstations_count must be ≤ 1: every BOM stage needs at
    # least one workstation, so depth cannot exceed workstations_count.
    def _valid(combo: tuple) -> bool:
        params = dict(zip(sweep_keys, combo))
        depth  = params.get("depth")
        n_ws   = params.get("workstations_count")
        if depth is not None and n_ws is not None:
            return depth <= n_ws
        return True

    combinations = [c for c in all_combos if _valid(c)]
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
