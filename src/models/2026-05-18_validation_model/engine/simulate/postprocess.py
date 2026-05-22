"""
Post-processing for the Assembly Factory simulator.

Converts the raw NumPy output arrays from the Numba tick loop back into
the five DataFrames that simulate() returns.

Public function
---------------
postprocess(pre, actual_ticks, n_throughput) -> dict[str, pd.DataFrame]

    pre           : dict returned by preprocess()
    actual_ticks  : last_tick + 1  (number of ticks actually executed)
    n_throughput  : number of completed orders written to pre["tp_log"]

Returns a dict with keys: 'states', 'utilization', 'throughput',
'costs', 'buffers'.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .tick_loop import _STATE_NAMES


def postprocess(
    pre:          dict,
    actual_ticks: int,
    n_throughput: int,
) -> dict[str, pd.DataFrame]:
    """
    Convert tick-loop output arrays into DataFrames.

    Parameters
    ----------
    pre           : dict returned by preprocess()
    actual_ticks  : number of ticks executed (last_tick + 1)
    n_throughput  : number of orders that completed

    Returns
    -------
    dict with five DataFrames: 'states', 'utilization', 'throughput',
    'costs', 'buffers'.
    """
    # Unpack needed items from the preprocess dict.
    ws_ids         = pre["ws_ids"]
    comp_ids       = pre["comp_ids"]
    components     = pre["components"]
    comp_level_arr = pre["comp_level_arr"]
    tick_duration  = pre["tick_duration"]
    log_buffers    = pre["log_buffers"]
    n_ws           = pre["n_ws"]

    state_log       = pre["state_log"]
    tp_log          = pre["tp_log"]
    buf_log         = pre["buf_log"]
    cost_setup_arr  = pre["cost_setup_arr"]
    cost_operating_arr = pre["cost_operating_arr"]
    cost_transport_arr = pre["cost_transport_arr"]
    cost_repair_arr    = pre["cost_repair_arr"]

    # ── States DataFrame ───────────────────────────────────────────────────────
    tick_idx  = np.repeat(np.arange(actual_ticks), n_ws)
    wi_idx    = np.tile(np.arange(n_ws), actual_ticks)
    states_df = pd.DataFrame({
        "Tick":        tick_idx,
        "Time":        np.round(tick_idx * tick_duration, 6),
        "Workstation": [ws_ids[wi] for wi in wi_idx],
        "State":       [_STATE_NAMES[int(state_log[t, wi])]
                        for t, wi in zip(tick_idx, wi_idx)],
    })

    # ── Utilization DataFrame ──────────────────────────────────────────────────
    util_rows = []
    for ws_id in sorted(ws_ids):
        wi     = ws_ids.index(ws_id)
        col    = state_log[:actual_ticks, wi]
        total  = actual_ticks
        counts = {s: int(np.sum(col == i)) for i, s in enumerate(_STATE_NAMES)}
        h      = {s: counts[s] * tick_duration for s in counts}
        util_rows.append({
            "Workstation": ws_id,
            "Busy":        h["processing"],
            "Setup":       h["setup"],
            "Blocked":     h["blocked"],
            "Starved":     h["starved"],
            "Idle":        h["idle"],
            "Failed":      h["failed"],
            "BusyPct":     100.0 * counts["processing"] / total if total else 0.0,
            "SetupPct":    100.0 * counts["setup"]      / total if total else 0.0,
            "BlockedPct":  100.0 * counts["blocked"]    / total if total else 0.0,
            "StarvedPct":  100.0 * counts["starved"]    / total if total else 0.0,
            "IdlePct":     100.0 * counts["idle"]       / total if total else 0.0,
            "FailedPct":   100.0 * counts["failed"]     / total if total else 0.0,
        })
    util_df = pd.DataFrame(util_rows)

    # ── Throughput DataFrame ───────────────────────────────────────────────────
    if n_throughput > 0:
        tp_df = pd.DataFrame({
            "Time":     tp_log[:n_throughput, 0],
            "Products": tp_log[:n_throughput, 1].astype(int),
            "Order":    tp_log[:n_throughput, 2].astype(int),
            "Product":  [comp_ids[int(tp_log[i, 3])] for i in range(n_throughput)],
            "LeadTime": tp_log[:n_throughput, 4],
        })
    else:
        tp_df = pd.DataFrame(columns=["Time", "Products", "Order", "Product", "LeadTime"])

    # ── Costs DataFrame ────────────────────────────────────────────────────────
    costs_df = pd.DataFrame([
        {
            "Workstation":   ws_ids[wi],
            "SetupCost":     cost_setup_arr[wi],
            "OperatingCost": cost_operating_arr[wi],
            "TransportCost": cost_transport_arr[wi],
            "RepairCost":    cost_repair_arr[wi],
        }
        for wi in range(n_ws)
    ])

    # ── Buffers DataFrame (optional) ───────────────────────────────────────────
    if log_buffers:
        non_raw = [ci for ci, c in enumerate(components) if c.level > 0]
        t_idx   = np.repeat(np.arange(actual_ticks), len(non_raw))
        ci_idx  = np.tile(non_raw, actual_ticks)
        buf_df  = pd.DataFrame({
            "Tick":      t_idx,
            "Time":      np.round(t_idx * tick_duration, 6),
            "Component": [comp_ids[ci] for ci in ci_idx],
            "Stock":     buf_log[:actual_ticks][:, non_raw].ravel().astype(int),
            "Level":     comp_level_arr[ci_idx],
        })
    else:
        buf_df = pd.DataFrame(columns=["Tick", "Time", "Component", "Stock", "Level"])

    return {
        "states":      states_df,
        "utilization": util_df,
        "throughput":  tp_df,
        "costs":       costs_df,
        "buffers":     buf_df,
    }
