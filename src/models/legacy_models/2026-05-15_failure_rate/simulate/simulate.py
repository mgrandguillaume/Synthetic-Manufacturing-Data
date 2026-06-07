#!/usr/bin/env python3
"""
Optimized Discrete-Time Simulation with Weibull machine failures — NumPy + Numba JIT.

The public simulate() function has an identical base signature and return value
to the initial model so that run.py, sweep.py, and all visualisations need
no changes.  Additional keyword arguments enable Weibull-distributed failures.

How it works
------------
  Pre-processing  (Python)
    All factory objects are converted to flat NumPy arrays.  Per-workstation
    Weibull parameters (β, λ) are sampled from the configured ranges and an
    initial time-to-failure (TTF) is drawn for every workstation.

  Tick loop  (Numba @njit — compiled to machine code on first call)
    Each workstation ages by one tick every tick it is not failed or blocked.
    When its accumulated age reaches the pre-sampled TTF the machine fails.
    After repair the age resets and a new TTF is sampled from Weibull(β, λ).

  Post-processing  (Python + NumPy/Pandas)
    Raw output arrays are converted back to the same DataFrames the initial
    model produces, with two additions: Failed/FailedPct in utilization and
    RepairCost in costs.

Workstation state codes
-----------------------
  0  idle        1  setup       2  processing
  3  blocked     4  starved     5  failed
"""

from __future__ import annotations

import math
import os
import sys
from collections import defaultdict

import numpy as np
import numba
import pandas as pd


# ── Integer state / phase codes (used in both Python and Numba) ───────────────

_IDLE       = 0
_SETUP      = 1
_PROCESSING = 2
_BLOCKED    = 3
_STARVED    = 4
_FAILED     = 5

_PHASE_SETUP = 0
_PHASE_PROC  = 1

_STATE_NAMES = ["idle", "setup", "processing", "blocked", "starved", "failed"]


# ── Numba helper: convert hours → ticks ──────────────────────────────────────

@numba.njit(cache=True)
def _to_ticks(hours: float, tick_duration: float) -> int:
    """Convert a duration in hours to ticks (minimum 1)."""
    t = int(math.ceil(hours / tick_duration))
    return t if t >= 1 else 1


# ── Numba helper: check whether a demand's BOM inputs are in stock ────────────

@numba.njit(cache=True)
def _inputs_ok(
    di:           int,
    demand_comp:  np.ndarray,   # int32[max_demands]
    demand_qty:   np.ndarray,   # int32[max_demands]
    bom_ptr:      np.ndarray,   # int32[n_comps + 1]   CSR row pointers
    bom_inputs:   np.ndarray,   # int32[n_bom_edges]   CSR column indices
    bom_qtys:     np.ndarray,   # int32[n_bom_edges]   qty per BOM edge
    comp_level:   np.ndarray,   # int32[n_comps]
    stock:        np.ndarray,   # int32[n_comps]
) -> bool:
    ci  = demand_comp[di]
    qty = demand_qty[di]
    for k in range(bom_ptr[ci], bom_ptr[ci + 1]):
        inp_ci  = bom_inputs[k]
        inp_qty = bom_qtys[k]
        # Raw materials (level 0) have infinite supply — skip the stock check.
        if comp_level[inp_ci] > 0 and stock[inp_ci] < inp_qty * qty:
            return False
    return True


# ── Core Numba tick loop ──────────────────────────────────────────────────────

@numba.njit(cache=True)
def _numba_tick_loop(
    # Scalars
    n_ticks:            int,
    n_orders:           int,
    order_interarrival: int,
    buffer_capacity:    int,
    tick_duration:      float,
    n_products:         int,
    # Workstation runtime state  [n_ws]
    ws_state:           np.ndarray,   # int8
    ws_ticks_left:      np.ndarray,   # int32
    ws_current_comp:    np.ndarray,   # int32  (-1 = none)
    ws_job_demand:      np.ndarray,   # int32  (-1 = no active job)
    ws_job_phase:       np.ndarray,   # int8   (0=setup, 1=processing)
    ws_job_qty:         np.ndarray,   # int32
    # Configuration matrices  [n_ws, n_comps]
    capable:            np.ndarray,   # bool
    proc_time_m:        np.ndarray,   # float64  hours per unit
    setup_time_m:       np.ndarray,   # float64  hours per changeover
    setup_cost_m:       np.ndarray,   # float64  cost per changeover
    op_cost_m:          np.ndarray,   # float64  cost per unit produced
    transport_cost:     np.ndarray,   # float64  [n_ws] avg incoming edge cost
    # BOM in CSR format
    bom_ptr:            np.ndarray,   # int32[n_comps + 1]
    bom_inputs:         np.ndarray,   # int32[n_bom_edges]
    bom_qtys:           np.ndarray,   # int32[n_bom_edges]
    comp_level:         np.ndarray,   # int32[n_comps]
    is_product:         np.ndarray,   # bool[n_comps]
    # Stock  [n_comps]  (raw materials pre-filled with _INF)
    stock:              np.ndarray,
    # Demand queue (pre-allocated fixed-size arrays)
    demand_comp:        np.ndarray,   # int32[max_demands]
    demand_level:       np.ndarray,   # int32[max_demands]
    demand_qty:         np.ndarray,   # int32[max_demands]
    demand_order:       np.ndarray,   # int32[max_demands]
    demand_created:     np.ndarray,   # int32[max_demands]
    demand_assigned:    np.ndarray,   # bool[max_demands]
    demand_fulfilled:   np.ndarray,   # bool[max_demands]
    # Pre-exploded BOM per product
    expl_comps:         np.ndarray,   # int32[n_products, max_comps_per_order]
    expl_qtys:          np.ndarray,   # int32[n_products, max_comps_per_order]
    expl_n:             np.ndarray,   # int32[n_products]
    # Cost accumulators  [n_ws]
    cost_setup:         np.ndarray,   # float64
    cost_operating:     np.ndarray,   # float64
    cost_transport:     np.ndarray,   # float64
    # Output log arrays (pre-allocated)
    state_log:          np.ndarray,   # int8[n_ticks, n_ws]
    tp_log:             np.ndarray,   # float64[n_orders, 5]
    buf_log:            np.ndarray,   # int32[n_ticks, n_comps]
    log_buffers:        bool,
    # ── Machine failure parameters (Weibull model) ────────────────────────────
    failures_enabled:   bool,
    ws_beta:            np.ndarray,   # float64[n_ws]  Weibull shape β per WS
    ws_lambda:          np.ndarray,   # float64[n_ws]  Weibull scale λ (hours)
    ws_age:             np.ndarray,   # int32[n_ws]    age in ticks since repair
    ws_ttf:             np.ndarray,   # int32[n_ws]    ticks until next failure
    mttr_min:           float,        # min repair duration (hours)
    mttr_max:           float,        # max repair duration (hours)
    repair_cost_min:    float,        # min cost per repair event
    repair_cost_max:    float,        # max cost per repair event
    ws_repair_left:     np.ndarray,   # int32[n_ws]  ticks remaining in repair
    cost_repair:        np.ndarray,   # float64[n_ws] accumulated repair cost
    rng_seed:           int,          # seed for Numba's internal RNG
) -> tuple:
    """
    Core tick loop compiled to machine code by Numba.

    Returns
    -------
    (last_tick, n_throughput)
        last_tick     : index of the final tick executed
        n_throughput  : number of completed orders logged to tp_log
    """
    if failures_enabled:
        np.random.seed(rng_seed)

    n_ws        = ws_state.shape[0]
    n_comps     = stock.shape[0]
    max_level   = int(np.max(comp_level))

    n_demands       = 0
    orders_released = 0
    orders_done     = 0
    n_throughput    = 0
    last_tick       = 0

    for tick in range(n_ticks):
        last_tick = tick

        # ── 0. Failures & repairs (Weibull model) ────────────────────────────
        # Each workstation accumulates age every tick it is not failed or
        # blocked.  When age reaches the pre-sampled TTF (time-to-failure) the
        # machine fails.  After repair the age resets and a new TTF is sampled
        # from the same Weibull(β, λ) distribution.
        #
        # Blocked workstations are excluded: their job is already complete and
        # they only need buffer space, so mechanical age should not advance and
        # they cannot suddenly break down mid-wait.
        if failures_enabled:
            for wi in range(n_ws):
                if ws_state[wi] == _FAILED:
                    # Count down the repair timer.
                    ws_repair_left[wi] -= 1
                    if ws_repair_left[wi] <= 0:
                        ws_state[wi]       = _IDLE
                        ws_repair_left[wi] = 0
                        # Reset age and draw a new time-to-failure.
                        ws_age[wi] = 0
                        ttf_h      = ws_lambda[wi] * np.random.weibull(ws_beta[wi])
                        ws_ttf[wi] = _to_ticks(ttf_h, tick_duration)

                elif ws_state[wi] != _BLOCKED:
                    # Advance age; check whether the TTF has been reached.
                    ws_age[wi] += 1
                    if ws_age[wi] >= ws_ttf[wi]:
                        # Machine fails: charge repair cost, sample MTTR.
                        cost_repair[wi] += (repair_cost_min
                                            + np.random.random()
                                            * (repair_cost_max - repair_cost_min))
                        mttr_h = mttr_min + np.random.random() * (mttr_max - mttr_min)
                        ws_repair_left[wi] = _to_ticks(mttr_h, tick_duration)

                        # If mid-job: return consumed BOM inputs to stock and
                        # re-queue the demand item.
                        di = ws_job_demand[wi]
                        if di >= 0:
                            ci  = demand_comp[di]
                            qty = ws_job_qty[wi]
                            for k in range(bom_ptr[ci], bom_ptr[ci + 1]):
                                inp_ci  = bom_inputs[k]
                                inp_qty = bom_qtys[k]
                                if comp_level[inp_ci] > 0:
                                    stock[inp_ci] += inp_qty * qty
                            demand_assigned[di] = False
                            ws_job_demand[wi]   = -1

                        ws_state[wi] = _FAILED

        # ── 1. Release a new order every order_interarrival ticks ────────────
        if tick % order_interarrival == 0 and orders_released < n_orders:
            orders_released += 1
            prod_idx = (orders_released - 1) % n_products
            for k in range(expl_n[prod_idx]):
                ci  = expl_comps[prod_idx, k]
                qty = expl_qtys[prod_idx, k]
                demand_comp[n_demands]      = ci
                demand_level[n_demands]     = comp_level[ci]
                demand_qty[n_demands]       = qty
                demand_order[n_demands]     = orders_released
                demand_created[n_demands]   = tick
                demand_assigned[n_demands]  = False
                demand_fulfilled[n_demands] = False
                n_demands += 1

        # ── 2. Advance in-progress jobs by one tick ───────────────────────────
        for wi in range(n_ws):
            s = ws_state[wi]
            if s != _SETUP and s != _PROCESSING:
                continue
            di = ws_job_demand[wi]
            if di < 0:
                continue

            ws_ticks_left[wi] -= 1
            if ws_ticks_left[wi] > 0:
                continue   # still running

            ci  = demand_comp[di]
            qty = ws_job_qty[wi]

            if ws_job_phase[wi] == _PHASE_SETUP:
                # Changeover complete → begin processing
                cost_setup[wi]         += setup_cost_m[wi, ci]
                ws_job_phase[wi]        = _PHASE_PROC
                ws_ticks_left[wi]       = _to_ticks(proc_time_m[wi, ci] * qty, tick_duration)
                ws_state[wi]            = _PROCESSING

            else:
                # Processing complete → charge operating cost, then deposit
                cost_operating[wi] += op_cost_m[wi, ci] * qty

                if is_product[ci]:
                    # Final product → ship to QI (no buffer limit)
                    demand_fulfilled[di]        = True
                    orders_done                += 1
                    tp_log[n_throughput, 0]     = tick * tick_duration
                    tp_log[n_throughput, 1]     = float(orders_done)
                    tp_log[n_throughput, 2]     = float(demand_order[di])
                    tp_log[n_throughput, 3]     = float(ci)
                    tp_log[n_throughput, 4]     = (tick - demand_created[di]) * tick_duration
                    n_throughput               += 1
                    ws_job_demand[wi]           = -1
                    ws_state[wi]               = _IDLE

                elif stock[ci] + qty <= buffer_capacity:
                    # Non-final: space in buffer
                    stock[ci]            += qty
                    demand_fulfilled[di]  = True
                    ws_job_demand[wi]     = -1
                    ws_state[wi]          = _IDLE

                else:
                    # Buffer full → block until space opens
                    ws_state[wi] = _BLOCKED

        # ── 3. Retry blocked workstations (buffer space may have opened) ──────
        for wi in range(n_ws):
            if ws_state[wi] != _BLOCKED:
                continue
            di = ws_job_demand[wi]
            if di < 0:
                continue

            ci  = demand_comp[di]
            qty = ws_job_qty[wi]

            if is_product[ci]:
                demand_fulfilled[di]        = True
                orders_done                += 1
                tp_log[n_throughput, 0]     = tick * tick_duration
                tp_log[n_throughput, 1]     = float(orders_done)
                tp_log[n_throughput, 2]     = float(demand_order[di])
                tp_log[n_throughput, 3]     = float(ci)
                tp_log[n_throughput, 4]     = (tick - demand_created[di]) * tick_duration
                n_throughput               += 1
                ws_job_demand[wi]           = -1
                ws_state[wi]               = _IDLE

            elif stock[ci] + qty <= buffer_capacity:
                stock[ci]            += qty
                demand_fulfilled[di]  = True
                ws_job_demand[wi]     = -1
                ws_state[wi]          = _IDLE

        # ── 4. Assign idle workstations to pending demand ─────────────────────
        for lvl in range(1, max_level + 1):
            for di in range(n_demands):
                if demand_assigned[di] or demand_fulfilled[di]:
                    continue
                if demand_level[di] != lvl:
                    continue
                if not _inputs_ok(di, demand_comp, demand_qty,
                                  bom_ptr, bom_inputs, bom_qtys,
                                  comp_level, stock):
                    continue

                ci  = demand_comp[di]
                qty = demand_qty[di]

                best_wi  = -1
                best_eta = 999_999_999
                for wi in range(n_ws):
                    if ws_state[wi] != _IDLE and ws_state[wi] != _STARVED:
                        continue
                    if not capable[wi, ci]:
                        continue
                    st = setup_time_m[wi, ci] if ws_current_comp[wi] != ci else 0.0
                    eta = (_to_ticks(st, tick_duration)
                           + _to_ticks(proc_time_m[wi, ci] * qty, tick_duration))
                    if eta < best_eta:
                        best_eta = eta
                        best_wi  = wi

                if best_wi < 0:
                    continue

                for k in range(bom_ptr[ci], bom_ptr[ci + 1]):
                    inp_ci  = bom_inputs[k]
                    inp_qty = bom_qtys[k]
                    if comp_level[inp_ci] > 0:
                        stock[inp_ci] -= inp_qty * qty

                demand_assigned[di]          = True
                cost_transport[best_wi]     += transport_cost[best_wi] * qty

                needs_setup                  = ws_current_comp[best_wi] != ci
                ws_current_comp[best_wi]     = ci
                ws_job_demand[best_wi]       = di
                ws_job_qty[best_wi]          = qty

                if needs_setup:
                    ws_state[best_wi]      = _SETUP
                    ws_job_phase[best_wi]  = _PHASE_SETUP
                    ws_ticks_left[best_wi] = _to_ticks(setup_time_m[best_wi, ci], tick_duration)
                else:
                    ws_state[best_wi]      = _PROCESSING
                    ws_job_phase[best_wi]  = _PHASE_PROC
                    ws_ticks_left[best_wi] = _to_ticks(proc_time_m[best_wi, ci] * qty, tick_duration)

        # ── 5. Classify idle workstations as starved ──────────────────────────
        for wi in range(n_ws):
            if ws_state[wi] != _IDLE and ws_state[wi] != _STARVED:
                continue
            starved = False
            for di in range(n_demands):
                if demand_assigned[di] or demand_fulfilled[di]:
                    continue
                if not capable[wi, demand_comp[di]]:
                    continue
                if not _inputs_ok(di, demand_comp, demand_qty,
                                  bom_ptr, bom_inputs, bom_qtys,
                                  comp_level, stock):
                    starved = True
                    break
            ws_state[wi] = _STARVED if starved else _IDLE

        # ── 6. Log workstation states ─────────────────────────────────────────
        for wi in range(n_ws):
            state_log[tick, wi] = ws_state[wi]

        # ── 7. Log buffer levels (optional) ───────────────────────────────────
        if log_buffers:
            for ci in range(n_comps):
                buf_log[tick, ci] = stock[ci]

        # ── 8. Stop when all orders are fulfilled ─────────────────────────────
        if orders_done >= n_orders:
            break

    return last_tick, n_throughput


# ── Public simulate() function ────────────────────────────────────────────────

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

    Identical base signature and return value to the initial model's simulate().
    Internally uses a Numba-compiled tick loop with Weibull machine failures.

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
    weibull_beta_range    [min, max] Weibull shape β. Each workstation gets a
                          value sampled uniformly from this range.
                          β > 1 → wear-out (most realistic for machinery).
    weibull_lambda_range  [min, max] Weibull scale λ in hours. Controls the
                          characteristic life of each machine.  A larger λ
                          means the machine lives longer on average.
    mttr_range            [min, max] repair duration in hours, sampled per
                          failure event.
    repair_cost_range     [min, max] cost charged per failure event.
    seed                  RNG seed for reproducibility.

    Returns
    -------
    dict with five DataFrames: 'states', 'utilization', 'throughput',
    'costs', 'buffers'.
    'utilization' gains Failed / FailedPct columns.
    'costs' gains a RepairCost column.
    """
    if weibull_beta_range   is None: weibull_beta_range   = [2.0, 2.0]
    if weibull_lambda_range is None: weibull_lambda_range = [100.0, 100.0]
    if mttr_range           is None: mttr_range           = [1.0, 1.0]
    if repair_cost_range    is None: repair_cost_range    = [0.0, 0.0]

    # ── Unpack factory ─────────────────────────────────────────────────────────
    components     = gen_result["components"]
    bom_edges      = gen_result["bom_edges"]
    workstations   = gen_result["workstations"]
    configurations = gen_result["configurations"]
    layout_edges   = gen_result.get("layout_edges", [])

    prod_ws = [ws for ws in workstations if ws.type == "production"]

    # ── Build integer index maps ───────────────────────────────────────────────
    comp_ids = [c.id for c in components]
    comp_idx = {cid: i for i, cid in enumerate(comp_ids)}
    n_comps  = len(comp_ids)

    ws_ids = [ws.id for ws in prod_ws]
    ws_idx = {wid: i for i, wid in enumerate(ws_ids)}
    n_ws   = len(ws_ids)

    # ── Component property arrays ──────────────────────────────────────────────
    comp_level_arr = np.array([c.level     for c in components], dtype=np.int32)
    is_product_arr = np.array([c.is_product for c in components], dtype=np.bool_)

    _INF = 10_000_000
    stock = np.array(
        [_INF if c.level == 0 else 0 for c in components], dtype=np.int32
    )

    # ── BOM in CSR format ──────────────────────────────────────────────────────
    bom_adj: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for e in bom_edges:
        bom_adj[comp_idx[e.output]].append((comp_idx[e.input], e.quantity))

    ptr_list    = [0]
    inputs_flat = []
    qtys_flat   = []
    for ci in range(n_comps):
        for inp_ci, qty in bom_adj.get(ci, []):
            inputs_flat.append(inp_ci)
            qtys_flat.append(qty)
        ptr_list.append(len(inputs_flat))

    bom_ptr    = np.array(ptr_list,                         dtype=np.int32)
    bom_inputs = np.array(inputs_flat if inputs_flat else [0], dtype=np.int32)
    bom_qtys   = np.array(qtys_flat   if qtys_flat   else [0], dtype=np.int32)

    # ── Configuration matrices [n_ws, n_comps] ────────────────────────────────
    capable      = np.zeros((n_ws, n_comps), dtype=np.bool_)
    proc_time_m  = np.zeros((n_ws, n_comps), dtype=np.float64)
    setup_time_m = np.zeros((n_ws, n_comps), dtype=np.float64)
    setup_cost_m = np.zeros((n_ws, n_comps), dtype=np.float64)
    op_cost_m    = np.zeros((n_ws, n_comps), dtype=np.float64)

    for cfg in configurations:
        wi = ws_idx.get(cfg.workstation)
        ci = comp_idx.get(cfg.component)
        if wi is None or ci is None:
            continue
        capable[wi, ci]      = True
        proc_time_m[wi, ci]  = cfg.processing_time
        setup_time_m[wi, ci] = cfg.setup_time
        setup_cost_m[wi, ci] = cfg.setup_cost
        op_cost_m[wi, ci]    = cfg.operating_cost

    # ── Transport cost per workstation ─────────────────────────────────────────
    _incoming: dict[str, list[float]] = defaultdict(list)
    for e in layout_edges:
        if e.destination in ws_idx:
            _incoming[e.destination].append(e.cost)
    transport_cost = np.array([
        sum(_incoming[wid]) / len(_incoming[wid]) if _incoming[wid] else 0.0
        for wid in ws_ids
    ], dtype=np.float64)

    # ── Pre-compute BOM explosions for each product ───────────────────────────
    bom_inputs_py: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for e in bom_edges:
        bom_inputs_py[e.output].append((e.input, e.quantity))

    products   = [c for c in components if c.is_product]
    n_products = len(products)

    def _explode(prod_id: str) -> dict[str, int]:
        needs: dict[str, int] = {prod_id: 1}
        max_lvl = comp_level_arr[comp_idx[prod_id]]
        for lvl in range(max_lvl, 0, -1):
            for cid, qty in list(needs.items()):
                if comp_level_arr[comp_idx[cid]] != lvl:
                    continue
                for child, child_qty in bom_inputs_py.get(cid, []):
                    needs[child] = needs.get(child, 0) + qty * child_qty
        return {k: v for k, v in needs.items()
                if comp_level_arr[comp_idx[k]] > 0}

    prod_explosions     = [_explode(p.id) for p in products]
    max_comps_per_order = max((len(e) for e in prod_explosions), default=1)

    expl_comps = np.full((n_products, max_comps_per_order), -1, dtype=np.int32)
    expl_qtys  = np.zeros((n_products, max_comps_per_order),    dtype=np.int32)
    expl_n     = np.zeros(n_products,                           dtype=np.int32)

    for pi, explosion in enumerate(prod_explosions):
        for k, (cid, qty) in enumerate(explosion.items()):
            expl_comps[pi, k] = comp_idx[cid]
            expl_qtys[pi, k]  = qty
        expl_n[pi] = len(explosion)

    # ── Workstation runtime state arrays ──────────────────────────────────────
    ws_state        = np.full(n_ws, _IDLE, dtype=np.int8)
    ws_ticks_left   = np.zeros(n_ws,       dtype=np.int32)
    ws_current_comp = np.full(n_ws, -1,    dtype=np.int32)
    ws_job_demand   = np.full(n_ws, -1,    dtype=np.int32)
    ws_job_phase    = np.zeros(n_ws,       dtype=np.int8)
    ws_job_qty      = np.zeros(n_ws,       dtype=np.int32)

    # ── Demand queue pre-allocation ────────────────────────────────────────────
    max_demands = n_orders * max_comps_per_order + 16
    demand_comp      = np.zeros(max_demands, dtype=np.int32)
    demand_level_arr = np.zeros(max_demands, dtype=np.int32)
    demand_qty_arr   = np.zeros(max_demands, dtype=np.int32)
    demand_order_arr = np.zeros(max_demands, dtype=np.int32)
    demand_created   = np.zeros(max_demands, dtype=np.int32)
    demand_assigned  = np.zeros(max_demands, dtype=np.bool_)
    demand_fulfilled = np.zeros(max_demands, dtype=np.bool_)

    # ── Cost accumulators ──────────────────────────────────────────────────────
    cost_setup_arr     = np.zeros(n_ws, dtype=np.float64)
    cost_operating_arr = np.zeros(n_ws, dtype=np.float64)
    cost_transport_arr = np.zeros(n_ws, dtype=np.float64)

    # ── Weibull failure arrays ─────────────────────────────────────────────────
    # Per-workstation β and λ are sampled once in Python before the loop.
    # The initial TTF is also sampled here so the Numba loop starts with a
    # fully-initialised failure schedule.
    py_rng = np.random.default_rng(seed)

    if failures_enabled:
        beta_lo,   beta_hi   = float(weibull_beta_range[0]),   float(weibull_beta_range[1])
        lam_lo,    lam_hi    = float(weibull_lambda_range[0]), float(weibull_lambda_range[1])
        ws_beta   = py_rng.uniform(beta_lo,  beta_hi,  size=n_ws).astype(np.float64)
        ws_lambda = py_rng.uniform(lam_lo,   lam_hi,   size=n_ws).astype(np.float64)
        # Initial TTF: sample Weibull(β, λ) → convert hours → ticks.
        ws_ttf = np.array([
            max(1, math.ceil(ws_lambda[wi] * py_rng.weibull(ws_beta[wi]) / tick_duration))
            for wi in range(n_ws)
        ], dtype=np.int32)
    else:
        ws_beta   = np.ones(n_ws,  dtype=np.float64)    # unused
        ws_lambda = np.ones(n_ws,  dtype=np.float64)    # unused
        ws_ttf    = np.full(n_ws, 2**30, dtype=np.int32)  # effectively infinite

    ws_age          = np.zeros(n_ws, dtype=np.int32)
    ws_repair_left  = np.zeros(n_ws, dtype=np.int32)
    cost_repair_arr = np.zeros(n_ws, dtype=np.float64)

    mttr_min        = float(mttr_range[0])
    mttr_max        = float(mttr_range[1])
    repair_cost_min = float(repair_cost_range[0])
    repair_cost_max = float(repair_cost_range[1])
    rng_seed        = int(seed) if seed is not None else 0

    # ── Output log arrays ──────────────────────────────────────────────────────
    state_log = np.zeros((n_ticks, n_ws),   dtype=np.int8)
    tp_log    = np.zeros((n_orders, 5),     dtype=np.float64)
    buf_log   = (np.zeros((n_ticks, n_comps), dtype=np.int32)
                 if log_buffers else np.zeros((1, 1), dtype=np.int32))

    # ── Run Numba tick loop ────────────────────────────────────────────────────
    print("  [Numba] Compiling tick loop on first call (cached for later runs)…")
    last_tick, n_throughput = _numba_tick_loop(
        n_ticks, n_orders, order_interarrival, buffer_capacity, tick_duration,
        n_products,
        ws_state, ws_ticks_left, ws_current_comp,
        ws_job_demand, ws_job_phase, ws_job_qty,
        capable, proc_time_m, setup_time_m, setup_cost_m, op_cost_m,
        transport_cost,
        bom_ptr, bom_inputs, bom_qtys, comp_level_arr, is_product_arr,
        stock,
        demand_comp, demand_level_arr, demand_qty_arr, demand_order_arr,
        demand_created, demand_assigned, demand_fulfilled,
        expl_comps, expl_qtys, expl_n,
        cost_setup_arr, cost_operating_arr, cost_transport_arr,
        state_log, tp_log, buf_log, log_buffers,
        failures_enabled, ws_beta, ws_lambda, ws_age, ws_ttf,
        mttr_min, mttr_max, repair_cost_min, repair_cost_max,
        ws_repair_left, cost_repair_arr, rng_seed,
    )
    print("  [Numba] Tick loop complete.")

    actual_ticks = last_tick + 1

    # ── Post-process: arrays → DataFrames ────────────────────────────────────
    tick_idx = np.repeat(np.arange(actual_ticks), n_ws)
    wi_idx   = np.tile(np.arange(n_ws), actual_ticks)
    states_df = pd.DataFrame({
        "Tick":        tick_idx,
        "Time":        np.round(tick_idx * tick_duration, 6),
        "Workstation": [ws_ids[wi] for wi in wi_idx],
        "State":       [_STATE_NAMES[int(state_log[t, wi])]
                        for t, wi in zip(tick_idx, wi_idx)],
    })

    # Utilisation — includes the "failed" state.
    util_rows = []
    for ws_id in sorted(ws_ids):
        wi    = ws_ids.index(ws_id)
        col   = state_log[:actual_ticks, wi]
        total = actual_ticks
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

    # Throughput
    tp_df = pd.DataFrame({
        "Time":     tp_log[:n_throughput, 0],
        "Products": tp_log[:n_throughput, 1].astype(int),
        "Order":    tp_log[:n_throughput, 2].astype(int),
        "Product":  [comp_ids[int(tp_log[i, 3])] for i in range(n_throughput)],
        "LeadTime": tp_log[:n_throughput, 4],
    }) if n_throughput > 0 else pd.DataFrame(
        columns=["Time", "Products", "Order", "Product", "LeadTime"])

    # Costs — includes RepairCost column.
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

    # Buffers (optional)
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


# ── Script entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from generate.generate import generate_simple_assembly
    import utils

    SIM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim_output")

    _config_path = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml")
    )
    _cfg  = utils.load_config(_config_path)
    _sim  = _cfg.get("simulation", {})
    _fail = _cfg.get("failures", {})

    print("Generating factory…")
    gen_result = generate_simple_assembly(_config_path, export_csv=True)

    print("Running optimized discrete-time simulation with Weibull machine failures…")
    results = simulate(
        gen_result,
        n_orders              = _sim.get("n_orders",           10),
        tick_duration         = _sim.get("tick_duration",      0.05),
        buffer_capacity       = _sim.get("buffer_capacity",    20),
        order_interarrival    = _sim.get("order_interarrival", 10),
        n_ticks               = _sim.get("n_ticks",            3000),
        log_buffers           = True,
        failures_enabled      = _fail.get("enabled",          False),
        weibull_beta_range    = _fail.get("weibull_beta",     [2.0, 2.0]),
        weibull_lambda_range  = _fail.get("weibull_lambda",   [100.0, 100.0]),
        mttr_range            = _fail.get("mttr",             [1.0, 1.0]),
        repair_cost_range     = _fail.get("repair_cost",      [0.0, 0.0]),
        seed                  = _cfg["metadata"].get("seed"),
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
