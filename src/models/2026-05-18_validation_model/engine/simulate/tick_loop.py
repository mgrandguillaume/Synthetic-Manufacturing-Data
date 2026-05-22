"""
Numba-compiled tick loop for the Assembly Factory simulator.

Contains
--------
State / phase integer codes used by both Python and Numba:
    _IDLE, _SETUP, _PROCESSING, _BLOCKED, _STARVED, _FAILED
    _PHASE_SETUP, _PHASE_PROC
    _STATE_NAMES

Helpers (all @njit, cache=True):
    _to_ticks(hours, tick_duration) -> int
    _inputs_ok(di, ...) -> bool

Core loop:
    _numba_tick_loop(...) -> (last_tick, n_throughput)
"""

from __future__ import annotations

import math

import numpy as np
import numba


# ── State / phase codes ────────────────────────────────────────────────────────

_IDLE       = 0
_SETUP      = 1
_PROCESSING = 2
_BLOCKED    = 3
_STARVED    = 4
_FAILED     = 5

_PHASE_SETUP = 0
_PHASE_PROC  = 1

_STATE_NAMES = ["idle", "setup", "processing", "blocked", "starved", "failed"]


# ── Numba helper: hours → ticks ───────────────────────────────────────────────

@numba.njit(cache=True)
def _to_ticks(hours: float, tick_duration: float) -> int:
    """Convert a duration in hours to ticks (minimum 1)."""
    t = int(math.ceil(hours / tick_duration))
    return t if t >= 1 else 1


# ── Numba helper: BOM input availability check ────────────────────────────────

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
    """Return True iff every non-raw BOM input for demand di is in stock."""
    ci  = demand_comp[di]
    qty = demand_qty[di]
    for k in range(bom_ptr[ci], bom_ptr[ci + 1]):
        inp_ci  = bom_inputs[k]
        inp_qty = bom_qtys[k]
        # Raw materials (level 0) have infinite supply — skip the stock check.
        if comp_level[inp_ci] > 0 and stock[inp_ci] < inp_qty * qty:
            return False
    return True


# ── Core Numba tick loop ───────────────────────────────────────────────────────

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

    Each tick executes eight phases (in order):
      0. Failures & repairs (Weibull age model)
      1. Release a new order every order_interarrival ticks
      2. Advance in-progress jobs by one tick
      3. Retry blocked workstations (buffer space may have opened)
      4. Assign idle workstations to pending demand
      5. Classify idle workstations as starved
      6. Log workstation states
      7. Log buffer levels (optional)

    Returns
    -------
    (last_tick, n_throughput)
        last_tick    : index of the final tick executed
        n_throughput : number of completed orders logged to tp_log
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

        # ── 0. Failures & repairs ────────────────────────────────────────────
        # Each workstation accumulates age every tick it is in SETUP or
        # PROCESSING.  Idle, starved, and blocked workstations do not age.
        # When age reaches the pre-sampled TTF the machine fails.  After
        # repair the age resets to 0 and a new TTF is sampled from
        # Weibull(β, λ).
        if failures_enabled:
            for wi in range(n_ws):
                if ws_state[wi] == _FAILED:
                    ws_repair_left[wi] -= 1
                    if ws_repair_left[wi] <= 0:
                        ws_state[wi]       = _IDLE
                        ws_repair_left[wi] = 0
                        ws_age[wi] = 0
                        ttf_h      = ws_lambda[wi] * np.random.weibull(ws_beta[wi])
                        ws_ttf[wi] = _to_ticks(ttf_h, tick_duration)

                elif ws_state[wi] == _SETUP or ws_state[wi] == _PROCESSING:
                    ws_age[wi] += 1
                    if ws_age[wi] >= ws_ttf[wi]:
                        cost_repair[wi] += (repair_cost_min
                                            + np.random.random()
                                            * (repair_cost_max - repair_cost_min))
                        mttr_h = mttr_min + np.random.random() * (mttr_max - mttr_min)
                        ws_repair_left[wi] = _to_ticks(mttr_h, tick_duration)

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

        # ── 1. Release orders ────────────────────────────────────────────────
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

        # ── 2. Advance in-progress jobs ──────────────────────────────────────
        for wi in range(n_ws):
            s = ws_state[wi]
            if s != _SETUP and s != _PROCESSING:
                continue
            di = ws_job_demand[wi]
            if di < 0:
                continue

            ws_ticks_left[wi] -= 1
            if ws_ticks_left[wi] > 0:
                continue

            ci  = demand_comp[di]
            qty = ws_job_qty[wi]

            if ws_job_phase[wi] == _PHASE_SETUP:
                cost_setup[wi]         += setup_cost_m[wi, ci]
                ws_job_phase[wi]        = _PHASE_PROC
                ws_ticks_left[wi]       = _to_ticks(proc_time_m[wi, ci] * qty, tick_duration)
                ws_state[wi]            = _PROCESSING
            else:
                cost_operating[wi] += op_cost_m[wi, ci] * qty

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

                else:
                    ws_state[wi] = _BLOCKED

        # ── 3. Retry blocked workstations ────────────────────────────────────
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

        # ── 4. Assign idle workstations ──────────────────────────────────────
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
                    st  = setup_time_m[wi, ci] if ws_current_comp[wi] != ci else 0.0
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

        # ── 5. Classify idle workstations as starved ─────────────────────────
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

        # ── 6. Log workstation states ────────────────────────────────────────
        for wi in range(n_ws):
            state_log[tick, wi] = ws_state[wi]

        # ── 7. Log buffer levels (optional) ──────────────────────────────────
        if log_buffers:
            for ci in range(n_comps):
                buf_log[tick, ci] = stock[ci]

        # ── 8. Stop when all orders fulfilled ────────────────────────────────
        if orders_done >= n_orders:
            break

    return last_tick, n_throughput
