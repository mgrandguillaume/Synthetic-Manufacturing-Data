"""
Pre-processing for the Assembly Factory simulator.

Converts factory dataclass objects (from generate.py) into the flat NumPy
arrays required by the Numba tick loop.  All array allocation and BOM
explosion happen here; the tick loop itself touches no Python objects.

Public function
---------------
preprocess(gen_result, n_orders, tick_duration, buffer_capacity,
           order_interarrival, n_ticks, log_buffers,
           failures_enabled, weibull_beta_range, weibull_lambda_range,
           mttr_range, repair_cost_range, seed) -> dict

The returned dict is consumed by postprocess.py and used to unpack
arguments for _numba_tick_loop.
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from .tick_loop import _IDLE


# ── Sentinel for raw-material infinite stock ───────────────────────────────────
_INF = 10_000_000


def preprocess(
    gen_result:           dict,
    n_orders:             int,
    tick_duration:        float,
    buffer_capacity:      int,
    order_interarrival:   int,
    n_ticks:              int,
    log_buffers:          bool,
    failures_enabled:     bool,
    weibull_beta_range:   list,
    weibull_lambda_range: list,
    mttr_range:           list,
    repair_cost_range:    list,
    seed:                 int | None,
) -> dict:
    """
    Build all NumPy arrays needed by the Numba tick loop.

    Returns a dict with the following groups of keys:

    Metadata (Python objects, used by postprocess):
        ws_ids          list[str]   workstation IDs in loop order
        comp_ids        list[str]   component IDs in loop order
        components      list        original Component dataclass list
        comp_level_arr  np.ndarray  int32 level per component
        n_ws, n_comps, n_products   int

    Arrays passed directly to _numba_tick_loop (same name as the param):
        ws_state, ws_ticks_left, ws_current_comp, ws_job_demand,
        ws_job_phase, ws_job_qty,
        capable, proc_time_m, setup_time_m, setup_cost_m, op_cost_m,
        transport_cost,
        bom_ptr, bom_inputs, bom_qtys, comp_level_arr, is_product_arr,
        stock,
        demand_comp, demand_level_arr, demand_qty_arr, demand_order_arr,
        demand_created, demand_assigned, demand_fulfilled,
        expl_comps, expl_qtys, expl_n,
        cost_setup_arr, cost_operating_arr, cost_transport_arr,
        state_log, tp_log, buf_log,
        ws_beta, ws_lambda, ws_age, ws_ttf,
        ws_repair_left, cost_repair_arr,

    Scalars passed to _numba_tick_loop:
        mttr_min, mttr_max, repair_cost_min, repair_cost_max, rng_seed,
        n_ticks, n_orders, order_interarrival, buffer_capacity,
        tick_duration, n_products, log_buffers, failures_enabled,
    """

    # ── Unpack factory ─────────────────────────────────────────────────────────
    components     = gen_result["components"]
    bom_edges      = gen_result["bom_edges"]
    workstations   = gen_result["workstations"]
    configurations = gen_result["configurations"]
    layout_edges   = gen_result.get("layout_edges", [])

    prod_ws = [ws for ws in workstations if ws.type == "production"]

    # ── Integer index maps ─────────────────────────────────────────────────────
    comp_ids = [c.id for c in components]
    comp_idx = {cid: i for i, cid in enumerate(comp_ids)}
    n_comps  = len(comp_ids)

    ws_ids = [ws.id for ws in prod_ws]
    ws_idx = {wid: i for i, wid in enumerate(ws_ids)}
    n_ws   = len(ws_ids)

    # ── Component property arrays ──────────────────────────────────────────────
    comp_level_arr = np.array([c.level     for c in components], dtype=np.int32)
    is_product_arr = np.array([c.is_product for c in components], dtype=np.bool_)

    stock = np.array(
        [_INF if c.level == 0 else 0 for c in components], dtype=np.int32
    )

    # ── BOM in CSR format ──────────────────────────────────────────────────────
    # Use a dict-of-dicts to aggregate quantities for duplicate (parent, child)
    # pairs.  Duplicate edges arise when sharing_ratio > 0 causes the same
    # component to be picked more than once as a child of the same parent in
    # _build_subtree (random.choice can return the same element on two
    # iterations of the branching loop).  Without deduplication, _inputs_ok
    # would check each edge independently (passing if stock >= qty for each
    # edge separately) while Phase 4 would decrement stock for every edge —
    # consuming qty * n_duplicates even when stock only held qty, causing
    # stock to go negative.  Summing quantities into a single CSR entry
    # ensures both the availability check and the decrement use the same
    # total quantity.
    bom_adj: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for e in bom_edges:
        bom_adj[comp_idx[e.output]][comp_idx[e.input]] += e.quantity

    ptr_list    = [0]
    inputs_flat = []
    qtys_flat   = []
    for ci in range(n_comps):
        for inp_ci, qty in bom_adj.get(ci, {}).items():
            inputs_flat.append(inp_ci)
            qtys_flat.append(qty)
        ptr_list.append(len(inputs_flat))

    bom_ptr    = np.array(ptr_list,                            dtype=np.int32)
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

    # ── Pre-compute BOM explosions for each product ────────────────────────────
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

    # ── Workstation runtime state ──────────────────────────────────────────────
    ws_state        = np.full(n_ws, _IDLE, dtype=np.int8)
    ws_ticks_left   = np.zeros(n_ws,       dtype=np.int32)
    ws_current_comp = np.full(n_ws, -1,    dtype=np.int32)
    ws_job_demand   = np.full(n_ws, -1,    dtype=np.int32)
    ws_job_phase    = np.zeros(n_ws,       dtype=np.int8)
    ws_job_qty      = np.zeros(n_ws,       dtype=np.int32)

    # ── Demand queue ───────────────────────────────────────────────────────────
    max_demands          = n_orders * max_comps_per_order + 16
    demand_comp          = np.zeros(max_demands, dtype=np.int32)
    demand_level_arr     = np.zeros(max_demands, dtype=np.int32)
    demand_qty_arr       = np.zeros(max_demands, dtype=np.int32)
    # demand_remaining: units still to be produced.  Starts equal to
    # demand_qty_arr and is decremented by 1 in the tick loop each time a
    # single unit is successfully deposited into the output buffer.
    # When it reaches 0, demand_fulfilled is set to True.
    demand_remaining_arr = np.zeros(max_demands, dtype=np.int32)
    demand_order_arr     = np.zeros(max_demands, dtype=np.int32)
    demand_created       = np.zeros(max_demands, dtype=np.int32)
    demand_assigned      = np.zeros(max_demands, dtype=np.bool_)
    demand_fulfilled     = np.zeros(max_demands, dtype=np.bool_)

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
        beta_lo,  beta_hi  = float(weibull_beta_range[0]),   float(weibull_beta_range[1])
        lam_lo,   lam_hi   = float(weibull_lambda_range[0]), float(weibull_lambda_range[1])
        ws_beta   = py_rng.uniform(beta_lo, beta_hi, size=n_ws).astype(np.float64)
        ws_lambda = py_rng.uniform(lam_lo,  lam_hi,  size=n_ws).astype(np.float64)
        ws_ttf    = np.array([
            max(1, math.ceil(ws_lambda[wi] * py_rng.weibull(ws_beta[wi]) / tick_duration))
            for wi in range(n_ws)
        ], dtype=np.int32)
    else:
        ws_beta   = np.ones(n_ws,  dtype=np.float64)
        ws_lambda = np.ones(n_ws,  dtype=np.float64)
        ws_ttf    = np.full(n_ws, 2**30, dtype=np.int32)   # effectively infinite

    ws_age          = np.zeros(n_ws, dtype=np.int32)
    ws_repair_left  = np.zeros(n_ws, dtype=np.int32)
    cost_repair_arr = np.zeros(n_ws, dtype=np.float64)

    # ── Output log arrays ──────────────────────────────────────────────────────
    # Buffer logging is strided: only every buf_stride-th tick is recorded so
    # that (n_ticks, n_comps) never materialises as a multi-GB array.
    # Target ≤ BUF_MAX_TICKS rows in the chart regardless of simulation length.
    BUF_MAX_TICKS = 5_000
    buf_stride    = max(1, n_ticks // BUF_MAX_TICKS)
    buf_n_rows    = math.ceil(n_ticks / buf_stride)

    state_log = np.zeros((n_ticks,    n_ws),    dtype=np.int8)
    tp_log    = np.zeros((n_orders,   5),       dtype=np.float64)
    buf_log   = (np.zeros((buf_n_rows, n_comps), dtype=np.int32)
                 if log_buffers else np.zeros((1, 1), dtype=np.int32))

    return dict(
        # ── Metadata ───────────────────────────────────────────────────────
        ws_ids         = ws_ids,
        comp_ids       = comp_ids,
        components     = components,
        comp_level_arr = comp_level_arr,
        n_ws           = n_ws,
        n_comps        = n_comps,
        n_products     = n_products,
        # ── Scalars for tick loop ──────────────────────────────────────────
        n_ticks            = n_ticks,
        n_orders           = n_orders,
        order_interarrival = order_interarrival,
        buffer_capacity    = buffer_capacity,
        tick_duration      = tick_duration,
        log_buffers        = log_buffers,
        failures_enabled   = failures_enabled,
        mttr_min           = float(mttr_range[0]),
        mttr_max           = float(mttr_range[1]),
        repair_cost_min    = float(repair_cost_range[0]),
        repair_cost_max    = float(repair_cost_range[1]),
        rng_seed           = int(seed) if seed is not None else 0,
        # ── Workstation state arrays ───────────────────────────────────────
        ws_state        = ws_state,
        ws_ticks_left   = ws_ticks_left,
        ws_current_comp = ws_current_comp,
        ws_job_demand   = ws_job_demand,
        ws_job_phase    = ws_job_phase,
        ws_job_qty      = ws_job_qty,
        # ── Configuration matrices ─────────────────────────────────────────
        capable         = capable,
        proc_time_m     = proc_time_m,
        setup_time_m    = setup_time_m,
        setup_cost_m    = setup_cost_m,
        op_cost_m       = op_cost_m,
        transport_cost  = transport_cost,
        # ── BOM CSR arrays ─────────────────────────────────────────────────
        bom_ptr         = bom_ptr,
        bom_inputs      = bom_inputs,
        bom_qtys        = bom_qtys,
        comp_level_arrN = comp_level_arr,   # alias (same object, Numba arg name)
        is_product_arr  = is_product_arr,
        stock           = stock,
        # ── Demand queue ───────────────────────────────────────────────────
        demand_comp          = demand_comp,
        demand_level_arr     = demand_level_arr,
        demand_qty_arr       = demand_qty_arr,
        demand_remaining_arr = demand_remaining_arr,
        demand_order_arr     = demand_order_arr,
        demand_created       = demand_created,
        demand_assigned      = demand_assigned,
        demand_fulfilled     = demand_fulfilled,
        # ── BOM explosions ─────────────────────────────────────────────────
        expl_comps = expl_comps,
        expl_qtys  = expl_qtys,
        expl_n     = expl_n,
        # ── Cost accumulators ──────────────────────────────────────────────
        cost_setup_arr     = cost_setup_arr,
        cost_operating_arr = cost_operating_arr,
        cost_transport_arr = cost_transport_arr,
        # ── Output logs ────────────────────────────────────────────────────
        state_log  = state_log,
        tp_log     = tp_log,
        buf_log    = buf_log,
        buf_stride = buf_stride,
        # ── Weibull failure arrays ─────────────────────────────────────────
        ws_beta        = ws_beta,
        ws_lambda      = ws_lambda,
        ws_age         = ws_age,
        ws_ttf         = ws_ttf,
        ws_repair_left = ws_repair_left,
        cost_repair_arr = cost_repair_arr,
    )
