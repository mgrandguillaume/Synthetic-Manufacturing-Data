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

Factory Physics metrics
-----------------------
The utilization DataFrame includes additional columns based on concepts from
Hopp & Spearman, *Factory Physics* (3rd ed., 2008), Chapters 7–8.

  MTBF_h          — mean time between failures (hours) per workstation.
                    The simulator draws failure inter-arrival times from a
                    Weibull(λ, β) distribution; the exact mean is:
                        MTBF = λ · Γ(1 + 1/β)
                    where Γ is the standard gamma function.
                    NOTE: this formula comes from Weibull distribution
                    theory, not from Hopp & Spearman directly.  The book
                    uses a generic m_0 (mean time between failures) without
                    tying it to a specific failure distribution.

  Availability    — long-run fraction of time the machine is operational.
                    Following Hopp & Spearman (Ch. 8), availability is:
                        A = m_0 / (m_0 + m_r)
                    where m_0 = MTBF and m_r = mean repair time (MTTR_mean).
                    In this model MTTR_mean = (mttr_min + mttr_max) / 2.

  t_e_h           — effective process time (hours): the mean time to produce
                    one unit when machine failures are accounted for.
                    Hopp & Spearman, Equation 8.2:
                        t_e = t_0 / A
                    where t_0 is the mean natural (failure-free) processing
                    time averaged over all components the workstation can make.

  IsPredictedBottleneck — True for the workstation with the highest t_e.
                    Hopp & Spearman (Ch. 7) define the bottleneck as the
                    workstation with the highest utilization (u = r / r_e),
                    where r_e = m / t_e is effective capacity.  For a fixed
                    demand rate r, this is exactly the station with the
                    highest t_e.  In a multi-product factory the demand mix
                    matters too, so this is an approximation; it correctly
                    flags the machine most penalised by failures and long
                    processing times.

When failures are disabled, A = 1, MTBF_h = None, and t_e_h = t_0
(the mean processing time; no availability penalty).
"""

from __future__ import annotations

import math

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

    state_log          = pre["state_log"]
    tp_log             = pre["tp_log"]
    buf_log            = pre["buf_log"]
    cost_setup_arr     = pre["cost_setup_arr"]
    cost_operating_arr = pre["cost_operating_arr"]
    cost_transport_arr = pre["cost_transport_arr"]
    cost_repair_arr    = pre["cost_repair_arr"]

    # ── States DataFrame ───────────────────────────────────────────────────────
    # Vectorised construction — avoid Python-level list comprehensions over
    # millions of rows.  pd.Categorical.from_codes stores only an int32 code
    # array + a small category list, so memory and build time are both far
    # lower than materialising millions of Python strings.
    #
    # state_log[:actual_ticks] has shape (actual_ticks, n_ws).
    # Ravelling in C (row-major) order is identical to the old
    # np.repeat/np.tile pattern: for each tick t, workstations 0…n_ws-1.
    tick_idx    = np.repeat(np.arange(actual_ticks, dtype=np.int32), n_ws)
    flat_states = state_log[:actual_ticks].ravel().astype(np.int8)   # state codes

    states_df = pd.DataFrame({
        "Tick":        tick_idx,
        "Time":        np.round(tick_idx * tick_duration, 6),
        "Workstation": pd.Categorical.from_codes(
                           np.tile(np.arange(n_ws, dtype=np.int32), actual_ticks),
                           categories=ws_ids,
                       ),
        "State":       pd.Categorical.from_codes(
                           flat_states,
                           categories=_STATE_NAMES,
                       ),
    })

    # ── Factory Physics: effective process time and availability ───────────────
    #
    # For each workstation the following quantities are computed:
    #
    #   MTBF (mean time between failures, hours)
    #     The simulator uses Weibull(λ, β) inter-failure times.  The mean of
    #     a Weibull distribution is:
    #         MTBF = λ · Γ(1 + 1/β)
    #     where Γ is the standard gamma function.
    #     This is standard Weibull distribution theory, not specific to
    #     Hopp & Spearman.  The book (Ch. 8) uses a generic m_0 = mean time
    #     between failures without specifying the underlying failure distribution.
    #
    #   Availability A
    #     Hopp & Spearman (Ch. 8) define availability as:
    #         A = m_0 / (m_0 + m_r)
    #     where m_0 = MTBF and m_r = mean repair time (MTTR).
    #     Here MTTR_mean = (mttr_min + mttr_max) / 2 is used as m_r because
    #     the config specifies a uniform repair-time range; this is a model
    #     adaptation, not stated in the book.
    #
    #   Effective process time t_e  (Hopp & Spearman, Eq. 8.2)
    #     Failures inflate the time to produce each unit from the natural
    #     (failure-free) process time t_0:
    #         t_e = t_0 / A
    #     t_0 is the mean processing time across all components this workstation
    #     is capable of making (mean over capable (ws, comp) configuration pairs).
    #
    #   Predicted bottleneck
    #     Hopp & Spearman (Ch. 7) define the bottleneck as the workstation with
    #     the highest utilization u = r / r_e, where r_e = m / t_e is its
    #     effective capacity rate.  For a fixed demand rate r, the station with
    #     the highest t_e has the lowest r_e and hence the highest u.  In a
    #     multi-product factory the demand mix varies by station, so this is an
    #     approximation; it flags the machine most penalised by failures.
    #
    # When failures are disabled, MTBF = ∞, A = 1, and t_e = t_0.

    ws_beta          = pre["ws_beta"]
    ws_lambda        = pre["ws_lambda"]
    capable          = pre["capable"]
    proc_time_m      = pre["proc_time_m"]
    mttr_min         = pre["mttr_min"]
    mttr_max         = pre["mttr_max"]
    failures_enabled = pre["failures_enabled"]

    mttr_mean = (mttr_min + mttr_max) / 2.0

    # Build per-workstation Factory Physics metrics keyed by ws_id.
    _fp: dict[str, dict] = {}
    for wi, ws_id in enumerate(ws_ids):
        # t_0: mean processing time over all components this workstation can make.
        capable_mask = capable[wi]                       # bool array [n_comps]
        capable_pts  = proc_time_m[wi][capable_mask]    # processing times for capable pairs
        t0 = float(np.mean(capable_pts)) if len(capable_pts) > 0 else 0.0

        if failures_enabled and ws_lambda[wi] > 0 and ws_beta[wi] > 0:
            # Weibull MTBF: E[X] = λ·Γ(1+1/β)  (standard Weibull distribution formula)
            mtbf  = ws_lambda[wi] * math.gamma(1.0 + 1.0 / ws_beta[wi])
            denom = mtbf + mttr_mean
            avail = mtbf / denom if denom > 0 else 1.0
            t_e   = t0 / avail if avail > 0 else float("inf")
            _fp[ws_id] = {
                "MTBF_h":      round(mtbf,  4),
                "Availability": round(avail, 4),
                "t_e_h":        round(t_e,   4),
            }
        else:
            # Failures disabled: machine is always available.
            _fp[ws_id] = {
                "MTBF_h":      None,   # undefined when failures are off
                "Availability": 1.0,
                "t_e_h":        round(t0, 4),
            }

    # Predicted bottleneck: workstation with the highest t_e.
    bottleneck_id = max(_fp, key=lambda ws_id: _fp[ws_id]["t_e_h"])

    # ── Utilization DataFrame ──────────────────────────────────────────────────
    util_rows = []
    for ws_id in sorted(ws_ids):
        wi     = ws_ids.index(ws_id)
        col    = state_log[:actual_ticks, wi]
        total  = actual_ticks
        counts = {s: int(np.sum(col == i)) for i, s in enumerate(_STATE_NAMES)}
        h      = {s: counts[s] * tick_duration for s in counts}
        fp     = _fp[ws_id]
        util_rows.append({
            # ── Observed time-in-state ─────────────────────────────────────────
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
            # ── Factory Physics metrics ────────────────────────────────────────
            "MTBF_h":              fp["MTBF_h"],        # Weibull MTBF = λ·Γ(1+1/β) [Weibull theory]
            "Availability":        fp["Availability"],  # A = MTBF/(MTBF+MTTR)  [H&S Ch. 8]
            "t_e_h":               fp["t_e_h"],         # t_e = t_0/A  [H&S Eq. 8.2]
            "IsPredictedBottleneck": ws_id == bottleneck_id,
        })
    util_df = pd.DataFrame(util_rows)

    # ── Throughput DataFrame ───────────────────────────────────────────────────
    if n_throughput > 0:
        tp_df = pd.DataFrame({
            "Time":     tp_log[:n_throughput, 0],
            "Products": tp_log[:n_throughput, 1].astype(int),
            "Order":    tp_log[:n_throughput, 2].astype(int),
            "Product":  np.array(comp_ids)[tp_log[:n_throughput, 3].astype(int)],
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
        # buf_log was written every buf_stride ticks, so rows correspond to
        # actual ticks 0, stride, 2·stride, …  Only the first n_buf_samples
        # rows were written (simulation may have stopped before n_ticks).
        buf_stride    = pre.get("buf_stride", 1)
        n_buf_samples = (actual_ticks - 1) // buf_stride + 1
        sample_ticks  = np.arange(n_buf_samples, dtype=np.int32) * buf_stride

        non_raw    = np.array([ci for ci, c in enumerate(components) if c.level > 0],
                              dtype=np.int32)
        n_non_raw  = len(non_raw)

        # Vectorised component labels — use Categorical.from_codes so that
        # only n_non_raw Python strings are ever created (not millions of copies).
        comp_cats  = [comp_ids[ci] for ci in non_raw]   # tiny: one label per component
        comp_codes = np.tile(np.arange(n_non_raw, dtype=np.int32), n_buf_samples)
        t_idx      = np.repeat(sample_ticks, n_non_raw)

        buf_df = pd.DataFrame({
            "Tick":      t_idx,
            "Time":      np.round(t_idx * tick_duration, 6),
            "Component": pd.Categorical.from_codes(comp_codes, categories=comp_cats),
            "Stock":     buf_log[:n_buf_samples][:, non_raw].ravel().astype(np.int32),
            "Level":     comp_level_arr[np.tile(non_raw, n_buf_samples)],
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
