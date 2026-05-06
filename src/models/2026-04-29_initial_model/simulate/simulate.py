import pandas as pd
import os

# ── Public simulation function ─────────────────────────────────────────────────

def simulate(gen_result: dict, n_orders: int = 10) -> dict[str, pd.DataFrame]:
    """
    Simulate n_orders production orders through the factory described by gen_result.

    Parameters
    ----------
    gen_result : dict
        Output of generate_simple_assembly() or generate_from_params().
        Must contain: components, bom_edges, workstations, configurations, layout_edges.
    n_orders : int
        Number of production orders to simulate.

    Returns
    -------
    dict with keys: 'gantt', 'utilization', 'throughput', 'costs', 'wait_times'
    Each value is a pandas DataFrame.
    """

    # ── Convert dataclass lists to lookup structures ───────────────────────────
    components    = gen_result["components"]
    bom_edges     = gen_result["bom_edges"]
    workstations  = gen_result["workstations"]
    configurations = gen_result["configurations"]
    layout_edges  = gen_result["layout_edges"]

    # bom_inputs[parent_id] = [(child_id, quantity), ...]
    bom_inputs: dict[str, list[tuple[str, int]]] = {}
    for e in bom_edges:
        bom_inputs.setdefault(e.output, []).append((e.input, e.quantity))

    # comp_level[component_id] = BOM level (0 = raw material, depth = product)
    comp_level: dict[str, int] = {c.id: c.level for c in components}

    # products: all final product IDs
    products: list[str] = [c.id for c in components if c.is_product]

    # comp_configs[component_id] = list of capable workstation dicts
    comp_configs: dict[str, list[dict]] = {}
    for cfg in configurations:
        comp_configs.setdefault(cfg.component, []).append({
            "ws":         cfg.workstation,
            "proc_time":  cfg.processing_time,
            "setup_time": cfg.setup_time,
            "setup_cost": cfg.setup_cost,
            "op_cost":    cfg.operating_cost,
        })

    # transport_cost_map[(origin, destination)] = cost per unit
    transport_cost_map: dict[tuple[str, str], float] = {
        (e.origin, e.destination): e.cost for e in layout_edges
    }

    # ── Simulation state ───────────────────────────────────────────────────────
    production_ws: list[str] = [
        ws.id for ws in workstations if ws.type == "production"
    ]

    # ws_avail[ws]: time at which this workstation next becomes free
    ws_avail: dict[str, float] = {ws: 0.0 for ws in production_ws}

    # ws_comp[ws]: component the workstation is currently configured for
    ws_comp: dict[str, str] = {ws: "" for ws in production_ws}

    # ── Event logs ─────────────────────────────────────────────────────────────
    gantt_rows:      list[dict] = []
    throughput_rows: list[dict] = []
    wait_rows:       list[dict] = []
    cost_acc: dict[str, dict[str, float]] = {
        ws: {"setup": 0.0, "operating": 0.0, "transport": 0.0}
        for ws in production_ws
    }

    # ── BOM explosion ──────────────────────────────────────────────────────────
    def explode_bom(prod: str) -> dict[str, int]:
        """
        Return the total units of every component needed for one unit of prod.
        Walks top-down level by level so shared components accumulate correctly.
        """
        needs: dict[str, int] = {prod: 1}
        max_level: int = comp_level[prod]
        for lvl in range(max_level, 0, -1):
            for comp, qty in list(needs.items()):
                if comp_level[comp] != lvl:
                    continue
                for child, child_qty in bom_inputs.get(comp, []):
                    needs[child] = needs.get(child, 0) + qty * child_qty
        return needs

    # ── Schedule one job ───────────────────────────────────────────────────────
    def schedule(comp: str, qty: int, ready_t: float, order: int) -> float:
        """
        Assign qty units of comp to the workstation that finishes earliest.
        Logs Gantt events, wait times, and costs. Returns the finish time.
        Raw materials (level 0) are sourced instantly from Inventory.
        """
        if comp_level[comp] == 0:
            return ready_t  # raw materials: infinite supply, no delay

        cfgs = comp_configs[comp]

        def finish_time(cfg: dict) -> float:
            avail = max(ws_avail[cfg["ws"]], ready_t)
            setup = 0.0 if ws_comp[cfg["ws"]] == comp else cfg["setup_time"]
            return avail + setup + cfg["proc_time"] * qty

        best       = min(cfgs, key=finish_time)
        ws         = best["ws"]
        avail      = max(ws_avail[ws], ready_t)
        new_setup  = ws_comp[ws] != comp
        setup_t    = best["setup_time"] if new_setup else 0.0

        setup_start = avail
        proc_start  = avail + setup_t
        proc_end    = proc_start + best["proc_time"] * qty

        if new_setup and setup_t > 0:
            gantt_rows.append({
                "Workstation": ws, "Component": "SETUP", "Order": order,
                "Start": setup_start, "Finish": proc_start, "Type": "setup",
            })
            cost_acc[ws]["setup"] += best["setup_cost"]

        gantt_rows.append({
            "Workstation": ws, "Component": comp, "Order": order,
            "Start": proc_start, "Finish": proc_end, "Type": "processing",
        })
        cost_acc[ws]["operating"] += best["op_cost"] * qty
        cost_acc[ws]["transport"] += transport_cost_map.get(("Inv", ws), 0.0) * qty

        wait_rows.append({
            "Workstation": ws, "Component": comp,
            "Order": order, "WaitTime": proc_start - ready_t,
        })

        ws_avail[ws] = proc_end
        ws_comp[ws]  = comp
        return proc_end

    # ── Main simulation loop ───────────────────────────────────────────────────
    for order in range(1, n_orders + 1):
        prod  = products[(order - 1) % len(products)]
        needs = explode_bom(prod)

        comp_ready: dict[str, float] = {}
        max_level = comp_level[prod]

        for lvl in range(0, max_level + 1):
            for comp, qty in needs.items():
                if comp_level[comp] != lvl:
                    continue
                inputs_ready = max(
                    (comp_ready.get(inp, 0.0) for inp, _ in bom_inputs.get(comp, [])),
                    default=0.0,
                )
                comp_ready[comp] = schedule(comp, qty, inputs_ready, order)

        prod_done = comp_ready[prod]
        throughput_rows.append({"Time": prod_done, "Products": order, "Product": prod})

    # ── Utilization ───────────────────────────────────────────────────────────
    total_time = max(ws_avail.values()) if ws_avail else 0.0
    gantt_df   = pd.DataFrame(gantt_rows)

    util_rows: list[dict] = []
    for ws in sorted(production_ws):
        ws_gantt = gantt_df[gantt_df["Workstation"] == ws] if not gantt_df.empty else gantt_df
        busy  = (ws_gantt[ws_gantt["Type"] == "processing"]["Finish"] -
                 ws_gantt[ws_gantt["Type"] == "processing"]["Start"]).sum()
        setup = (ws_gantt[ws_gantt["Type"] == "setup"]["Finish"] -
                 ws_gantt[ws_gantt["Type"] == "setup"]["Start"]).sum()
        idle  = max(total_time - busy - setup, 0.0)
        util_rows.append({"Workstation": ws, "Busy": busy, "Setup": setup, "Idle": idle})

    costs_df = pd.DataFrame([
        {"Workstation": ws,
         "SetupCost":     cost_acc[ws]["setup"],
         "OperatingCost": cost_acc[ws]["operating"],
         "TransportCost": cost_acc[ws]["transport"]}
        for ws in production_ws
    ])

    return {
        "gantt":       gantt_df,
        "utilization": pd.DataFrame(util_rows),
        "throughput":  pd.DataFrame(throughput_rows),
        "costs":       costs_df,
        "wait_times":  pd.DataFrame(wait_rows),
    }


# ── Script entry point (single run from CSV files) ─────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generate"))
    from generate import generate_simple_assembly

    N_ORDERS = 10
    SIM_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim_output")

    script_dir  = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "..", "config.yaml")

    print("Generating factory...")
    gen_result = generate_simple_assembly(config_path, export_csv=True)

    print(f"Running {N_ORDERS} orders...")
    results = simulate(gen_result, n_orders=N_ORDERS)

    os.makedirs(SIM_DIR, exist_ok=True)
    for name, df in results.items():
        df.to_csv(os.path.join(SIM_DIR, f"{name}.csv"), index=False)

    total_time = results["throughput"]["Time"].max()
    print(f"\nSimulation complete → sim_output/")
    print(f"Total time span : {total_time:.3f} h")
    print(f"Orders completed: {len(results['throughput'])}")
