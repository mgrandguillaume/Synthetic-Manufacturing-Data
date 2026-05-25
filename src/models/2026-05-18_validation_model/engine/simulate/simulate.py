#!/usr/bin/env python3
"""
Public API for the Assembly Factory simulator.

How it works
------------
  preprocess  (Python)
    Factory objects → flat NumPy arrays.  Per-workstation Weibull
    parameters are sampled and initial TTFs are drawn here.

  tick loop   (Numba @njit — compiled to machine code on first call)
    Each tick: failures/repairs, order release, job advance, blocked
    retry, assignment, starved classification, state & buffer logging.

  postprocess  (Python + NumPy/Pandas)
    Raw arrays → five DataFrames identical to the original model's
    output, plus Failed/FailedPct (utilization) and RepairCost (costs).

Workstation state codes
-----------------------
  0 idle   1 setup   2 processing   3 blocked   4 starved   5 failed

Run standalone:  python simulate.py   (reads config.yaml two levels up)
"""

from __future__ import annotations

import os
import sys

import pandas as pd

# ── Path setup ─────────────────────────────────────────────────────────────────
_HERE       = os.path.dirname(os.path.abspath(__file__))
_MODEL_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _MODEL_ROOT not in sys.path:
    sys.path.insert(0, _MODEL_ROOT)

from engine.simulate.preprocess  import preprocess          # noqa: E402
from engine.simulate.tick_loop   import _numba_tick_loop    # noqa: E402
from engine.simulate.postprocess import postprocess         # noqa: E402


# ── Public simulate() ──────────────────────────────────────────────────────────

def simulate(
    gen_result:           dict,
    n_orders:             int   = 10,
    tick_duration:        float = 0.05,
    buffer_capacity:      int   = 20,
    order_interarrival:   int   = 10,
    n_ticks:              int   = 3000,
    log_buffers:          bool  = True,
    failures_enabled:     bool  = False,
    weibull_beta_range:   list  = None,   # [min, max] Weibull shape β
    weibull_lambda_range: list  = None,   # [min, max] Weibull scale λ (hours)
    mttr_range:           list  = None,   # [min, max] repair duration (hours)
    repair_cost_range:    list  = None,   # [min, max] cost per repair event
    seed:                 int   = None,
) -> dict[str, pd.DataFrame]:
    """
    Simulate n_orders production orders through the factory in gen_result.

    Parameters
    ----------
    gen_result            Output of generate_from_params() or
                          generate_simple_assembly().
    n_orders              Number of production orders to release.
    tick_duration         Simulated hours per tick.
    buffer_capacity       Maximum units any non-raw component buffer may hold.
    order_interarrival    Ticks between successive order releases.
    n_ticks               Hard upper bound on simulation length.
    log_buffers           When False, the 'buffers' DataFrame is empty.
    failures_enabled      Whether machine failures are active.
    weibull_beta_range    [min, max] Weibull shape β per workstation.
                          β > 1 → wear-out behaviour.
    weibull_lambda_range  [min, max] Weibull scale λ in hours (characteristic life).
    mttr_range            [min, max] repair duration in hours, sampled per event.
    repair_cost_range     [min, max] cost charged per failure event.
    seed                  RNG seed for reproducibility.

    Returns
    -------
    dict with five DataFrames: 'states', 'utilization', 'throughput',
    'costs', 'buffers'.
    'utilization' includes Failed / FailedPct columns.
    'costs' includes a RepairCost column.
    """
    if weibull_beta_range   is None: weibull_beta_range   = [2.0,   2.0]
    if weibull_lambda_range is None: weibull_lambda_range = [100.0, 100.0]
    if mttr_range           is None: mttr_range           = [1.0,   1.0]
    if repair_cost_range    is None: repair_cost_range    = [0.0,   0.0]

    # ── Pre-process: factory objects → NumPy arrays ────────────────────────────
    pre = preprocess(
        gen_result, n_orders, tick_duration, buffer_capacity,
        order_interarrival, n_ticks, log_buffers, failures_enabled,
        weibull_beta_range, weibull_lambda_range,
        mttr_range, repair_cost_range, seed,
    )

    # ── Run Numba tick loop ────────────────────────────────────────────────────
    print("  [Numba] Compiling tick loop on first call (cached for later runs)…")
    last_tick, n_throughput = _numba_tick_loop(
        pre["n_ticks"], pre["n_orders"], pre["order_interarrival"],
        pre["buffer_capacity"], pre["tick_duration"], pre["n_products"],
        pre["ws_state"], pre["ws_ticks_left"], pre["ws_current_comp"],
        pre["ws_job_demand"], pre["ws_job_phase"], pre["ws_job_qty"],
        pre["capable"], pre["proc_time_m"], pre["setup_time_m"],
        pre["setup_cost_m"], pre["op_cost_m"], pre["transport_cost"],
        pre["bom_ptr"], pre["bom_inputs"], pre["bom_qtys"],
        pre["comp_level_arr"], pre["is_product_arr"],
        pre["stock"],
        pre["demand_comp"], pre["demand_level_arr"], pre["demand_qty_arr"],
        pre["demand_remaining_arr"],
        pre["demand_order_arr"], pre["demand_created"],
        pre["demand_assigned"], pre["demand_fulfilled"],
        pre["expl_comps"], pre["expl_qtys"], pre["expl_n"],
        pre["cost_setup_arr"], pre["cost_operating_arr"], pre["cost_transport_arr"],
        pre["state_log"], pre["tp_log"], pre["buf_log"], pre["log_buffers"],
        pre["failures_enabled"],
        pre["ws_beta"], pre["ws_lambda"], pre["ws_age"], pre["ws_ttf"],
        pre["mttr_min"], pre["mttr_max"],
        pre["repair_cost_min"], pre["repair_cost_max"],
        pre["ws_repair_left"], pre["cost_repair_arr"], pre["rng_seed"],
    )
    print("  [Numba] Tick loop complete.")

    # ── Post-process: NumPy arrays → DataFrames ────────────────────────────────
    dfs = postprocess(pre, last_tick + 1, n_throughput)

    # ── Validate simulation output ─────────────────────────────────────────────
    from engine.simulate.validate_output import validate as _validate_simulate
    _validate_simulate(dfs, buffer_capacity, gen_result)

    return dfs


# ── Script entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

    from shared_utils import utils
    from shared_utils import validate_config
    from engine.generate.generate import generate_simple_assembly

    SIM_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim_output")
    config_path = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "config.yaml")
    )

    cfg   = utils.load_config(config_path)
    validate_config.validate(cfg)
    _sim  = cfg.get("simulation", {})
    _fail = cfg.get("failures",   {})

    print("Generating factory…")
    gen_result = generate_simple_assembly(config_path, export_csv=True)

    print("Running simulation…")
    results = simulate(
        gen_result,
        n_orders             = _sim.get("n_orders",           10),
        tick_duration        = _sim.get("tick_duration",      0.05),
        buffer_capacity      = _sim.get("buffer_capacity",    20),
        order_interarrival   = _sim.get("order_interarrival", 10),
        n_ticks              = _sim.get("n_ticks",            3000),
        log_buffers          = True,
        failures_enabled     = _fail.get("enabled",          False),
        weibull_beta_range   = _fail.get("weibull_beta",     [2.0, 2.0]),
        weibull_lambda_range = _fail.get("weibull_lambda",   [100.0, 100.0]),
        mttr_range           = _fail.get("mttr",             [1.0, 1.0]),
        repair_cost_range    = _fail.get("repair_cost",      [0.0, 0.0]),
        seed                 = cfg["metadata"].get("seed"),
    )

    os.makedirs(SIM_DIR, exist_ok=True)
    for name, df in results.items():
        path = os.path.join(SIM_DIR, f"{name}.csv")
        df.to_csv(path, index=False)
        print(f"  Wrote {path}  ({len(df):,} rows)")

    tp = results["throughput"]
    if not tp.empty:
        print(f"\nSimulation complete → sim_output/")
        print(f"Orders completed : {len(tp)}")
        print(f"Total time span  : {tp['Time'].max():.3f} h")
        print(f"Mean lead time   : {tp['LeadTime'].mean():.3f} h")
    else:
        print("\nNo orders completed — consider increasing n_ticks or buffer_capacity.")
