#!/usr/bin/env python3
# Parameter sweep for the Simple Assembly Factory model.
#
# Runs generate + simulate for every combination of the sweep parameters
# defined in config.yaml (sweep: section). Each output row is tagged with
# the run's parameters so results can be filtered and grouped during analysis.
#
# Output: sweep_output/{gen_stats,state_summary,utilization,throughput,costs}.csv
#
# Run:  python sweep.py   (or python -m sweep.sweep from the model root)
# Dependencies: pip install pyyaml pandas

import os
import random as _random
import sys
import itertools

import pandas as pd

# ── Imports from the model root ────────────────────────────────────────────────
# One insert puts the model root on the path; package imports then work cleanly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from engine.generate.generate import generate_from_params  # noqa: E402
from engine.generate.factory  import pt_range             # noqa: E402
from engine.simulate.simulate import simulate              # noqa: E402
from shared_utils import utils                             # noqa: E402

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

# ── Run sweep ──────────────────────────────────────────────────────────────────
def main(progress_callback=None, max_runs: int | None = None):
    """
    Run the full parameter sweep.

    Parameters
    ----------
    progress_callback : callable | None
        Optional function called after every completed run (and once before the
        loop to report the total).  Signature::

            progress_callback(done: int, total: int, current: str) -> None

        ``done``    — number of runs completed so far (0 = before first run)
        ``total``   — total number of runs that will actually be executed
        ``current`` — human-readable label of the combination just finished
    max_runs : int | None
        When given, randomly sample exactly ``min(max_runs, n_valid)``
        combinations from the full valid grid instead of running all of them.
        The config seed (metadata.seed) is used for reproducibility; when the
        seed is None a fresh random sample is drawn each time.
    """
    cfg = utils.load_config()

    # ── Sweep parameter grid (from config.yaml → sweep:) ──────────────────────
    # Each entry is expanded to a list using _expand(); every combination is tested.
    param_grid: dict[str, list] = {k: _expand(v) for k, v in cfg["sweep"].items()}

    # ── Fixed parameters (from config.yaml) ───────────────────────────────────
    # Held constant across all runs; randomness within ranges gives natural variation.
    fixed_params: dict = {
        "branching":               cfg["bom"]["branching"],
        "quantity":                cfg["bom"]["quantity"],
        "producers_per_component": cfg["workstations"]["producers_per_component"],
        "processing_time":         (
            pt_range(
                cfg["workstations"]["assembly_type"],
                cfg["bom"]["depth"],
                cfg["workstations"].get("variation", 0.10),
            )
            if "assembly_type" in cfg["workstations"]
            else cfg["workstations"]["processing_time"]
        ),
        "setup_time":              cfg["workstations"]["setup_time"],
        "setup_cost":              cfg["workstations"]["setup_cost"],
        "operating_cost":          cfg["workstations"]["operating_cost"],
        "flow_capacity":           cfg["layout"]["flow_capacity"],
        "transport_cost":          cfg["layout"]["transport_cost"],
        "seed":                    cfg["metadata"].get("seed"),
    }

    # ── Simulation parameters (from config.yaml → simulation: + failures:) ──────
    _fail = cfg.get("failures", {})
    sim_params: dict = {
        "n_orders":             cfg["simulation"]["n_orders"],
        "tick_duration":        cfg["simulation"]["tick_duration"],
        "buffer_capacity":      cfg["simulation"]["buffer_capacity"],
        "order_interarrival":   cfg["simulation"]["order_interarrival"],
        "n_ticks":              cfg["simulation"]["n_ticks"],
        "failures_enabled":     _fail.get("enabled",          False),
        "weibull_beta_range":   _fail.get("weibull_beta",    [2.0, 2.0]),
        "weibull_lambda_range": _fail.get("weibull_lambda",  [100.0, 100.0]),
        "mttr_range":           _fail.get("mttr",            [1.0, 1.0]),
        "repair_cost_range":    _fail.get("repair_cost",     [0.0, 0.0]),
        "seed":                 cfg["metadata"].get("seed"),
    }

    # ── Output directory ───────────────────────────────────────────────────────
    sweep_dir: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep_output")

    sweep_keys   = list(param_grid.keys())
    sweep_values = list(param_grid.values())
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
    n_valid      = len(combinations)

    # ── Optional sub-sampling ──────────────────────────────────────────────────
    if max_runs is not None and 0 < max_runs < n_valid:
        seed_val = cfg["metadata"].get("seed")
        rng      = _random.Random(seed_val)
        combinations = rng.sample(combinations, max_runs)
        print(
            f"  Sampling {max_runs} of {n_valid} valid combinations "
            f"(seed={seed_val!r})"
        )

    total_runs   = len(combinations)

    print(f"Starting sweep: {total_runs} combinations × {sim_params['n_orders']} orders each")
    print(f"Sweep parameters: {', '.join(sweep_keys)}\n")

    # Report total before the loop so the UI can show 0 / N immediately.
    if progress_callback:
        progress_callback(0, total_runs, "")

    all_gen_stats:    list[dict]          = []
    all_state_summary: list[pd.DataFrame] = []
    all_utilization:  list[pd.DataFrame] = []
    all_throughput:   list[pd.DataFrame] = []
    all_costs:        list[pd.DataFrame] = []

    for run_id, combo in enumerate(combinations, start=1):
        sweep_params = dict(zip(sweep_keys, combo))
        params       = {**fixed_params, **sweep_params}

        # Tag columns prepended to every output row for this run.
        # Alpha (α = depth / workstations_count) is a derived topology metric:
        # α ≈ 1 → serial (one WS per BOM stage), α ≈ 0 → parallel (many WSs per stage).
        alpha = round(sweep_params["depth"] / sweep_params["workstations_count"], 4)
        tag = {"RunID": run_id, "alpha": alpha, **sweep_params}

        try:
            gen_result = generate_from_params(params)

            # Collect generation-phase structural metrics for the generation graphs.
            _c_vals = list(gen_result.get("complexity", {}).values())
            all_gen_stats.append({
                **tag,
                "n_raw":           sum(1 for c in gen_result["components"] if c.level == 0),
                "n_components":    sum(1 for c in gen_result["components"] if c.level > 0),
                "n_configs":       len(gen_result["configurations"]),
                "n_edges":         len(gen_result["layout_edges"]),
                "mean_complexity": round(sum(_c_vals) / len(_c_vals), 2) if _c_vals else 0,
                "max_complexity":  max(_c_vals) if _c_vals else 0,
            })

            sim_result = simulate(
                gen_result,
                n_orders              = sim_params["n_orders"],
                tick_duration         = sim_params["tick_duration"],
                buffer_capacity       = sim_params["buffer_capacity"],
                order_interarrival    = sim_params["order_interarrival"],
                n_ticks               = sim_params["n_ticks"],
                log_buffers           = False,   # skip per-tick buffer log in sweep
                failures_enabled      = sim_params["failures_enabled"],
                weibull_beta_range    = sim_params["weibull_beta_range"],
                weibull_lambda_range  = sim_params["weibull_lambda_range"],
                mttr_range            = sim_params["mttr_range"],
                repair_cost_range     = sim_params["repair_cost_range"],
                seed                  = sim_params["seed"],
            )
        except Exception as e:
            print(f"  [SKIP] Run {run_id}/{total_runs} failed: {e}")
            if progress_callback:
                combo_str = ", ".join(f"{k}={v}" for k, v in sweep_params.items())
                progress_callback(run_id, total_runs, combo_str)
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
            for col in ["processing", "setup", "starved", "blocked", "idle", "failed"]:
                if col not in tick_pct.columns:
                    tick_pct[col] = 0.0
            tick_pct = tick_pct.rename(columns={
                "processing": "ProcessingPct",
                "setup":      "SetupPct",
                "starved":    "StarvedPct",
                "blocked":    "BlockedPct",
                "idle":       "IdlePct",
                "failed":     "FailedPct",
            })[["Tick", "ProcessingPct", "SetupPct", "StarvedPct",
                "BlockedPct", "IdlePct", "FailedPct"]]
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

        if progress_callback:
            combo_str = ", ".join(f"{k}={v}" for k, v in sweep_params.items())
            progress_callback(run_id, total_runs, combo_str)

    # ── Write combined CSVs ────────────────────────────────────────────────────
    os.makedirs(sweep_dir, exist_ok=True)

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
        path = os.path.join(sweep_dir, f"{name}.csv")
        pd.concat(frames, ignore_index=True).to_csv(path, index=False)
        print(f"  Wrote {path}")

    print(f"\nSweep complete — results in {sweep_dir}/")


if __name__ == "__main__":
    main()
