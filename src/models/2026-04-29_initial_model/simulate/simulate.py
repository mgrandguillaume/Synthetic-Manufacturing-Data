#!/usr/bin/env python3
"""
Discrete-Time Simulation (DTS) for the Simple Assembly Factory model.

Every tick (Δt = tick_duration hours) all workstations are evaluated
simultaneously.  This enables three phenomena absent in the original
analytical scheduler:

  Concurrency   – multiple workstations produce different components in
                  parallel, respecting BOM dependencies.
  Starvation    – a workstation is ready but its BOM inputs are not yet
                  in stock; it waits instead of starting.
  Blocking      – a workstation finished a job but the output buffer is
                  full; it holds the units until space opens up.

Workstation states
------------------
  idle        No demand is waiting for this workstation.
  setup       Performing a changeover (switching to a new component type).
  processing  Actively producing units.
  blocked     Processing finished; output buffer is full — holding units.
  starved     Has pending demand but input components are not yet in stock.

Run:  python simulate.py
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

import pandas as pd


# ── Internal data structures ─────────────────────────────────────────────────

@dataclass
class _Demand:
    """One unit of work: produce `qty` units of `component` for `order_id`."""
    demand_id:    int
    order_id:     int
    component:    str
    level:        int
    qty:          int
    created_tick: int
    assigned:     bool = False
    fulfilled:    bool = False


@dataclass
class _Job:
    """A job currently running (or blocked) on a workstation."""
    demand:     _Demand
    cfg:        dict       # {ws, proc_time, setup_time, setup_cost, op_cost}
    phase:      str        # 'setup' | 'processing'
    ticks_left: int


@dataclass
class _WS:
    """Mutable runtime state of one production workstation."""
    ws_id:        str
    current_comp: str        = ""
    state:        str        = "idle"
    job:          _Job | None = None


# ── Public simulation function ───────────────────────────────────────────────

def simulate(
    gen_result:          dict,
    n_orders:            int   = 10,
    tick_duration:       float = 0.05,   # hours per tick (~3 min)
    buffer_capacity:     int   = 20,     # max units per non-raw component buffer
    order_interarrival:  int   = 10,     # ticks between order releases
    n_ticks:             int   = 3000,   # hard simulation limit
    log_buffers:         bool  = True,   # False in sweep runs to save memory
) -> dict[str, pd.DataFrame]:
    """
    Simulate n_orders production orders through the factory in gen_result.

    Parameters
    ----------
    gen_result          Output of generate_from_params() or
                        generate_simple_assembly().
    n_orders            Number of production orders to release.
    tick_duration       Simulated hours represented by each tick.
    buffer_capacity     Maximum units any non-raw component buffer may hold.
                        When full, the producing workstation becomes blocked.
    order_interarrival  Ticks between successive order releases.
    n_ticks             Upper bound on simulation length (safety valve).
    log_buffers         When False, the 'buffers' DataFrame is empty.
                        Disable in sweep runs to keep output files small.

    Returns
    -------
    dict with five DataFrames:

      'states'      Tick, Time, Workstation, State
                    Per-tick record of every workstation's state.

      'utilization' Workstation, Busy, Setup, Blocked, Starved, Idle (hours)
                    BusyPct, SetupPct, BlockedPct, StarvedPct, IdlePct (%)

      'throughput'  Time, Products, Order, Product, LeadTime
                    One row per completed order.

      'costs'       Workstation, SetupCost, OperatingCost, TransportCost

      'buffers'     Tick, Time, Component, Stock, Level
                    Per-tick stock level for every non-raw component.
                    Empty DataFrame when log_buffers=False.
    """

    # ── Unpack factory ─────────────────────────────────────────────────────────
    components     = gen_result["components"]
    bom_edges      = gen_result["bom_edges"]
    workstations   = gen_result["workstations"]
    configurations = gen_result["configurations"]
    layout_edges   = gen_result.get("layout_edges", [])

    comp_level:  dict[str, int]  = {c.id: c.level     for c in components}
    is_product:  dict[str, bool] = {c.id: c.is_product for c in components}
    products:    list[str]       = [c.id for c in components if c.is_product]

    # bom_inputs[parent] = [(child_id, qty_per_unit_of_parent), ...]
    bom_inputs: dict[str, list[tuple[str, int]]] = {}
    for e in bom_edges:
        bom_inputs.setdefault(e.output, []).append((e.input, e.quantity))

    # comp_configs[comp] = [{ws, proc_time, setup_time, setup_cost, op_cost}, ...]
    comp_configs: dict[str, list[dict]] = {}
    for cfg in configurations:
        comp_configs.setdefault(cfg.component, []).append({
            "ws":         cfg.workstation,
            "proc_time":  cfg.processing_time,
            "setup_time": cfg.setup_time,
            "setup_cost": cfg.setup_cost,
            "op_cost":    cfg.operating_cost,
        })

    # ws_transport_cost[ws_id] = average cost of all edges arriving at that WS.
    # Stage-1 workstations are fed by Inv; higher-stage workstations are fed by
    # the previous stage.  Averaging over incoming edges gives a fair per-unit
    # transport charge regardless of which upstream workstation supplied the parts.
    from collections import defaultdict
    _incoming: dict[str, list[float]] = defaultdict(list)
    for e in layout_edges:
        if e.destination not in ("Inv", "QI"):
            _incoming[e.destination].append(e.cost)
    ws_transport_cost: dict[str, float] = {
        ws_id: (sum(_incoming[ws_id]) / len(_incoming[ws_id])
                if _incoming[ws_id] else 0.0)
        for ws_id in [ws.id for ws in workstations if ws.type == "production"]
    }

    # Production workstation IDs (excludes the Inv source and QI sink)
    prod_ws_ids: list[str] = [ws.id for ws in workstations if ws.type == "production"]

    # ── BOM explosion ──────────────────────────────────────────────────────────
    def _explode(prod: str) -> dict[str, int]:
        """
        Return the total units of every component required for one unit of
        prod.  Walks top-down level by level so shared sub-assemblies
        accumulate correctly.
        """
        needs: dict[str, int] = {prod: 1}
        max_lvl = comp_level[prod]
        for lvl in range(max_lvl, 0, -1):
            for comp, qty in list(needs.items()):
                if comp_level[comp] != lvl:
                    continue
                for child, child_qty in bom_inputs.get(comp, []):
                    needs[child] = needs.get(child, 0) + qty * child_qty
        return needs

    # ── Simulation state ───────────────────────────────────────────────────────
    # Raw materials (level 0) have effectively infinite stock.
    _INF = 10_000_000
    stock: dict[str, int] = {
        c.id: (_INF if c.level == 0 else 0) for c in components
    }

    ws_map: dict[str, _WS] = {ws_id: _WS(ws_id) for ws_id in prod_ws_ids}

    demand_queue:    list[_Demand] = []
    demand_counter:  int = 0
    orders_released: int = 0
    orders_done:     int = 0

    cost_acc: dict[str, dict[str, float]] = {
        ws_id: {"setup": 0.0, "operating": 0.0, "transport": 0.0}
        for ws_id in prod_ws_ids
    }

    state_rows:      list[dict] = []
    throughput_rows: list[dict] = []
    buffer_rows:     list[dict] = []

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _ticks(hours: float) -> int:
        """Convert a duration in hours to an integer number of ticks (≥ 1)."""
        return max(1, math.ceil(hours / tick_duration))

    def _inputs_ok(d: _Demand) -> bool:
        """True when every non-raw BOM input is in stock in sufficient quantity."""
        for child, qty_per in bom_inputs.get(d.component, []):
            if comp_level[child] == 0:
                continue   # raw materials: infinite supply
            if stock[child] < qty_per * d.qty:
                return False
        return True

    def _consume(d: _Demand) -> None:
        """Deduct BOM input quantities from stock (raw materials are free)."""
        for child, qty_per in bom_inputs.get(d.component, []):
            if comp_level[child] > 0:
                stock[child] -= qty_per * d.qty

    def _try_deposit(ws: _WS, tick: int) -> None:
        """
        Try to move a finished job's output into the component buffer.
        If the buffer is full the workstation transitions to 'blocked' and
        retries on subsequent ticks.  Final products ship immediately (no
        buffer limit) and count toward order throughput.
        """
        nonlocal orders_done
        job  = ws.job
        comp = job.demand.component
        qty  = job.demand.qty
        time = tick * tick_duration

        if is_product.get(comp, False):
            # Final product → ship directly to QI, no buffer needed.
            job.demand.fulfilled = True
            orders_done += 1
            throughput_rows.append({
                "Time":      time,
                "Products":  orders_done,
                "Order":     job.demand.order_id,
                "Product":   comp,
                "LeadTime":  (tick - job.demand.created_tick) * tick_duration,
            })
            ws.job   = None
            ws.state = "idle"

        elif stock[comp] + qty <= buffer_capacity:
            # Non-final component: space in buffer.
            stock[comp]          += qty
            job.demand.fulfilled  = True
            ws.job                = None
            ws.state              = "idle"

        else:
            # Buffer full: block until space opens.
            ws.state = "blocked"

    # ── Order release ──────────────────────────────────────────────────────────
    def _release(order_id: int, tick: int) -> None:
        """
        Explode the BOM for the next product and add one demand item per
        non-raw component to the global demand queue.
        """
        nonlocal demand_counter
        prod = products[(order_id - 1) % len(products)]
        for comp, qty in _explode(prod).items():
            if comp_level[comp] == 0:
                continue   # raw materials require no production
            demand_counter += 1
            demand_queue.append(_Demand(
                demand_id    = demand_counter,
                order_id     = order_id,
                component    = comp,
                level        = comp_level[comp],
                qty          = qty,
                created_tick = tick,
            ))

    # ── Main tick loop ─────────────────────────────────────────────────────────
    for tick in range(n_ticks):
        time = tick * tick_duration

        # 1. Release a new order every order_interarrival ticks.
        if tick % order_interarrival == 0 and orders_released < n_orders:
            orders_released += 1
            _release(orders_released, tick)

        # 2. Advance in-progress jobs by one tick.
        for ws in ws_map.values():
            if ws.state not in ("setup", "processing") or ws.job is None:
                continue

            ws.job.ticks_left -= 1
            if ws.job.ticks_left > 0:
                continue   # still running

            if ws.job.phase == "setup":
                # Changeover complete → begin processing.
                cost_acc[ws.ws_id]["setup"] += ws.job.cfg["setup_cost"]
                proc_ticks          = _ticks(ws.job.cfg["proc_time"] * ws.job.demand.qty)
                ws.job.phase        = "processing"
                ws.job.ticks_left   = proc_ticks
                ws.state            = "processing"
            else:
                # Processing complete → charge operating cost, then deposit.
                cost_acc[ws.ws_id]["operating"] += (
                    ws.job.cfg["op_cost"] * ws.job.demand.qty
                )
                _try_deposit(ws, tick)

        # 3. Retry blocked workstations (buffer space may have opened up).
        for ws in ws_map.values():
            if ws.state == "blocked" and ws.job is not None:
                _try_deposit(ws, tick)

        # 4. Assign idle workstations to unmet demand (process lowest BOM
        #    levels first so inputs are produced before the assemblies that
        #    require them).
        pending = sorted(
            [d for d in demand_queue if not d.assigned and not d.fulfilled],
            key=lambda d: d.level,
        )
        for d in pending:
            if not _inputs_ok(d):
                continue   # inputs not yet in stock; skip for now

            # Find available workstations capable of producing this component.
            avail_cfgs = [
                cfg for cfg in comp_configs.get(d.component, [])
                if ws_map[cfg["ws"]].state in ("idle", "starved")
            ]
            if not avail_cfgs:
                continue   # all capable workstations are busy

            # Pick the configuration that finishes earliest.
            def _eta(cfg: dict, demand: _Demand = d) -> int:
                ws = ws_map[cfg["ws"]]
                setup_h = cfg["setup_time"] if ws.current_comp != demand.component else 0.0
                return _ticks(setup_h) + _ticks(cfg["proc_time"] * demand.qty)

            best  = min(avail_cfgs, key=_eta)
            ws_id = best["ws"]
            ws    = ws_map[ws_id]

            # Consume input stock and claim the demand item.
            _consume(d)
            d.assigned = True

            # Transport cost: moving inputs into this WS from the upstream stage.
            cost_acc[ws_id]["transport"] += ws_transport_cost[ws_id] * d.qty

            # Start setup (if component changes) or processing immediately.
            needs_setup = ws.current_comp != d.component
            ws.current_comp = d.component
            if needs_setup:
                ws.state = "setup"
                ticks_left = _ticks(best["setup_time"])
                phase      = "setup"
            else:
                ws.state = "processing"
                ticks_left = _ticks(best["proc_time"] * d.qty)
                phase      = "processing"

            ws.job = _Job(demand=d, cfg=best, phase=phase, ticks_left=ticks_left)

        # 5. Classify idle workstations as 'starved' when they have pending
        #    demand that cannot start due to missing input stock.
        idle_ws = [ws for ws in ws_map.values() if ws.state in ("idle", "starved")]
        if idle_ws:
            unassigned = [
                d for d in demand_queue if not d.assigned and not d.fulfilled
            ]
            for ws in idle_ws:
                ws_comps = {
                    cfg["ws"] for cfgs in comp_configs.values()
                    for cfg in cfgs if cfg["ws"] == ws.ws_id
                }
                starved = any(
                    any(cfg["ws"] == ws.ws_id
                        for cfg in comp_configs.get(d.component, []))
                    and not _inputs_ok(d)
                    for d in unassigned
                )
                ws.state = "starved" if starved else "idle"

        # 6. Log workstation states for this tick.
        for ws in ws_map.values():
            state_rows.append({
                "Tick":        tick,
                "Time":        round(time, 6),
                "Workstation": ws.ws_id,
                "State":       ws.state,
            })

        # 7. Log component buffer levels for this tick.
        if log_buffers:
            for c in components:
                if c.level > 0:   # skip raw materials (infinite supply)
                    buffer_rows.append({
                        "Tick":      tick,
                        "Time":      round(time, 6),
                        "Component": c.id,
                        "Stock":     stock[c.id],
                        "Level":     c.level,
                    })

        # 8. Stop as soon as all orders are fulfilled.
        if orders_done >= n_orders:
            break

    # ── Build output DataFrames ────────────────────────────────────────────────
    states_df = pd.DataFrame(state_rows)

    util_rows: list[dict] = []
    if not states_df.empty:
        for ws_id in sorted(prod_ws_ids):
            ws_df   = states_df[states_df["Workstation"] == ws_id]
            total_t = len(ws_df)
            vc      = ws_df["State"].value_counts()
            counts  = {s: int(vc.get(s, 0))
                       for s in ("idle", "setup", "processing", "blocked", "starved")}
            h = {s: counts[s] * tick_duration for s in counts}
            util_rows.append({
                "Workstation": ws_id,
                "Busy":        h["processing"],
                "Setup":       h["setup"],
                "Blocked":     h["blocked"],
                "Starved":     h["starved"],
                "Idle":        h["idle"],
                "BusyPct":     100.0 * counts["processing"] / total_t if total_t else 0.0,
                "SetupPct":    100.0 * counts["setup"]      / total_t if total_t else 0.0,
                "BlockedPct":  100.0 * counts["blocked"]    / total_t if total_t else 0.0,
                "StarvedPct":  100.0 * counts["starved"]    / total_t if total_t else 0.0,
                "IdlePct":     100.0 * counts["idle"]       / total_t if total_t else 0.0,
            })

    costs_df = pd.DataFrame([
        {
            "Workstation":   ws_id,
            "SetupCost":     cost_acc[ws_id]["setup"],
            "OperatingCost": cost_acc[ws_id]["operating"],
            "TransportCost": cost_acc[ws_id]["transport"],
        }
        for ws_id in prod_ws_ids
    ])

    return {
        "states":      states_df,
        "utilization": pd.DataFrame(util_rows),
        "throughput":  pd.DataFrame(throughput_rows),
        "costs":       costs_df,
        "buffers":     pd.DataFrame(buffer_rows),
    }


# ── Script entry point (single run) ─────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generate"))
    from generate import generate_simple_assembly

    import yaml

    SIM_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim_output")
    script_dir  = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "..", "config.yaml")

    with open(config_path) as _f:
        _cfg = yaml.safe_load(_f)
    _sim = _cfg.get("simulation", {})

    print("Generating factory…")
    gen_result = generate_simple_assembly(config_path, export_csv=True)

    print("Running discrete-time simulation…")
    results = simulate(
        gen_result,
        n_orders            = _sim.get("n_orders",            10),
        tick_duration       = _sim.get("tick_duration",       0.05),
        buffer_capacity     = _sim.get("buffer_capacity",     20),
        order_interarrival  = _sim.get("order_interarrival",  10),
        n_ticks             = _sim.get("n_ticks",             3000),
        log_buffers         = True,
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
