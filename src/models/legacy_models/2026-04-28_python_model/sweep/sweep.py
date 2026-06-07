#!/usr/bin/env python3
# Parameter sweep for the Simple Assembly Factory model.
#
# Runs generate + simulate for every combination of the sweep parameters
# defined in config.yaml (sweep: section). Each output row is tagged with
# the run's parameters so results can be filtered and grouped during analysis.
#
# Sweep dimensions (see config.yaml → sweep:):
#   n_products    — number of distinct products in the BOM
#   depth         — number of BOM levels (raw → … → product)
#   sharing_ratio — probability of reusing an existing component at each level
#   topology      — layout graph structure: "parallel" or "linear"
#
# Output: sweep_output/{gen_stats,state_summary,utilization,throughput,costs}.csv
#
# Run:  python sweep.py   (or python -m sweep.sweep from the model root)
# Dependencies: pip install pyyaml pandas

import os
import sys
import itertools

import pandas as pd
import yaml

# ── Imports from the model root ────────────────────────────────────────────────
_MODEL_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, _MODEL_ROOT)

from generate.generate import generate_from_params  # noqa: E402
from simulate.simulate import simulate              # noqa: E402

_CONFIG_PATH = os.path.join(_MODEL_ROOT, "config.yaml")


# ── Parameter expansion helper ─────────────────────────────────────────────────
def _expand(val) -> list:
    """
    Convert a sweep parameter value from config.yaml into a flat list of values.

    Three formats are supported:
      fixed   scalar        depth: 2
              → [2]

      list    explicit      depth: [1, 2, 3]
              → [1, 2, 3]

      range   min/max/step  sharing_ratio: {min: 0.0, max: 1.0, step: 0.5}
              → [0.0, 0.5, 1.0]
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


# ── Run sweep ──────────────────────────────────────────────────────────────────
def main():
    with open(_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    # ── Sweep parameter grid (from config.yaml → sweep:) ──────────────────────
    param_grid: dict[str, list] = {k: _expand(v) for k, v in cfg["sweep"].items()}

    # ── Fixed parameters (held constant across all runs) ──────────────────────
    fixed_params: dict = {
        "branching":               cfg["bom"]["branching"],
        "quantity":                cfg["bom"]["quantity"],
        "workstations_count":      cfg["workstations"]["count"],
        "producers_per_component": cfg["configurations"]["producers_per_component"],
        "processing_time":         cfg["configurations"]["processing_time"],
        "setup_time":              cfg["configurations"]["setup_time"],
        "setup_cost":              cfg["configurations"]["setup_cost"],
        "operating_cost":          cfg["configurations"]["operating_cost"],
        "flow_capacity":           cfg["layout"]["flow_capacity"],
        "transport_cost":          cfg["layout"]["transport_cost"],
        "seed":                    cfg["metadata"].get("seed"),
    }

    # ── Simulation parameters (from config.yaml → simulation:) ────────────────
    _sim = cfg["simulation"]
    sim_params: dict = {
        "n_orders":           _sim["n_orders"],
        "tick_duration":      _sim["tick_duration"],
        "buffer_capacity":    _sim["buffer_capacity"],
        "order_interarrival": _sim["order_interarrival"],
        "n_ticks":            _sim["n_ticks"],
    }

    # ── Output directory ───────────────────────────────────────────────────────
    sweep_dir: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep_output")

    sweep_keys   = list(param_grid.keys())
    sweep_values = list(param_grid.values())
    combinations = list(itertools.product(*sweep_values))
    total_runs   = len(combinations)

    print(f"Starting sweep: {total_runs} combinations × {sim_params['n_orders']} orders each")
    print(f"Sweep parameters: {', '.join(sweep_keys)}\n")

    all_gen_stats:     list[dict]          = []
    all_state_summary: list[pd.DataFrame] = []
    all_utilization:   list[pd.DataFrame] = []
    all_throughput:    list[pd.DataFrame] = []
    all_costs:         list[pd.DataFrame] = []

    for run_id, combo in enumerate(combinations, start=1):
        sweep_params = dict(zip(sweep_keys, combo))
        # Sweep params override fixed params (topology in sweep overrides layout default).
        params = {**fixed_params, **sweep_params}

        tag = {"RunID": run_id, **sweep_params}

        try:
            gen_result = generate_from_params(params)

            all_gen_stats.append({
                **tag,
                "n_raw":        sum(1 for c in gen_result["components"] if c.level == 0),
                "n_components": sum(1 for c in gen_result["components"] if c.level > 0),
                "n_configs":    len(gen_result["configurations"]),
                "n_edges":      len(gen_result["layout_edges"]),
            })

            sim_result = simulate(
                gen_result,
                n_orders           = sim_params["n_orders"],
                tick_duration      = sim_params["tick_duration"],
                buffer_capacity    = sim_params["buffer_capacity"],
                order_interarrival = sim_params["order_interarrival"],
                n_ticks            = sim_params["n_ticks"],
                log_buffers        = False,
            )
        except Exception as e:
            print(f"  [SKIP] Run {run_id}/{total_runs} failed: {e}")
            continue

        # Compute per-tick state % averaged across workstations (CLEMATIS chart).
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

        for df, acc in [
            (sim_result["utilization"], all_utilization),
            (sim_result["throughput"],  all_throughput),
            (sim_result["costs"],       all_costs),
        ]:
            tagged = df.copy()
            for col, val in reversed(tag.items()):
                tagged.insert(0, col, val)
            acc.append(tagged)

        if run_id % 20 == 0 or run_id == total_runs:
            print(f"  Progress: {run_id}/{total_runs} runs complete")

    # ── Write combined CSVs ────────────────────────────────────────────────────
    os.makedirs(sweep_dir, exist_ok=True)

    outputs = {
        "gen_stats":     [pd.DataFrame(all_gen_stats)] if all_gen_stats else [],
        "state_summary": all_state_summary,
        "utilization":   all_utilization,
        "throughput":    all_throughput,
        "costs":         all_costs,
    }

    for name, frames in outputs.items():
        if not frames:
            print(f"  [WARN] No data for {name}.csv — all runs may have failed.")
            continue
        path = os.path.join(sweep_dir, f"{name}.csv")
        pd.concat(frames, ignore_index=True).to_csv(path, index=False)
        print(f"  Wrote {path}")

    print(f"\nSweep complete — results in {sweep_dir}/")

    from sweep.visualize_sweep import show
    show(sweep_dir)


if __name__ == "__main__":
    main()
