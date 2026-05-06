import pandas as pd
import os

# ── Configuration ─────────────────────────────────────────────────────────────
# Paths are resolved relative to this script so it can be run from any directory.
OUTPUT_DIR: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "generate", "gen_output")
SIM_DIR: str    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim_output")

# N_ORDERS: how many production orders to simulate.
# Orders are assigned to products in round-robin order (order 1 → product 1,
# order 2 → product 2, order n+1 → product 1 again, etc.).
# All orders are for a single unit of the selected product.
N_ORDERS: int = 10

# ── Load data ─────────────────────────────────────────────────────────────────
components_df:   pd.DataFrame = pd.read_csv(os.path.join(OUTPUT_DIR, "components.csv"))
bom_df:          pd.DataFrame = pd.read_csv(os.path.join(OUTPUT_DIR, "bom.csv"))
workstations_df: pd.DataFrame = pd.read_csv(os.path.join(OUTPUT_DIR, "workstations.csv"))
configs_df:      pd.DataFrame = pd.read_csv(os.path.join(OUTPUT_DIR, "configurations.csv"))
layout_df:       pd.DataFrame = pd.read_csv(os.path.join(OUTPUT_DIR, "layout.csv"))

# ── Lookup structures ─────────────────────────────────────────────────────────
# bom_inputs[parent_id] = [(child_id, quantity), ...]
# Maps each component to the list of direct children it requires and how many
# units of each child are needed to produce one unit of the parent.
bom_inputs: dict[str, list[tuple[str, int]]] = {}
for _, row in bom_df.iterrows():
    bom_inputs.setdefault(row["Output"], []).append((row["Input"], row["Quantity"]))

# comp_level[component_id] = BOM level (0 = raw material, depth = finished product)
comp_level: dict[str, int] = dict(zip(components_df["ID"], components_df["Level"]))

# products: list of component IDs that are final products (IsProduct == True)
products: list[str] = components_df[components_df["IsProduct"] == True]["ID"].tolist()

# comp_configs[component_id] = list of capable workstation configurations.
# Each entry is a dict with the workstation ID and its time/cost parameters.
# A component may be producible on more than one workstation; the scheduler
# picks the one that finishes earliest (see schedule()).
comp_configs: dict[str, list[dict]] = {}
for _, row in configs_df.iterrows():
    comp_configs.setdefault(row["Component"], []).append({
        "ws":         row["Workstation"],   # workstation ID
        "proc_time":  row["ProcessingTime"],# hours per unit produced
        "setup_time": row["SetupTime"],     # hours for a changeover (paid once per new component)
        "setup_cost": row["SetupCost"],     # cost charged once per changeover
        "op_cost":    row["OperatingCost"], # cost per unit produced
    })

# transport_cost_map[(origin, destination)] = cost per unit transported along that edge
transport_cost_map: dict[tuple[str, str], float] = {
    (row["Origin"], row["Destination"]): row["Cost"]
    for _, row in layout_df.iterrows()
}

# ── Simulation state ──────────────────────────────────────────────────────────
# Only production workstations are scheduled; Inv and QI are not modelled as
# capacity-constrained resources.
production_ws: list[str] = workstations_df[workstations_df["Type"] == "production"]["ID"].tolist()

# ws_avail[ws]: the earliest time (in hours) at which workstation ws is free
# to start a new job. Starts at 0 for all workstations (factory is idle).
ws_avail: dict[str, float] = {ws: 0.0 for ws in production_ws}

# ws_comp[ws]: the component the workstation is currently set up for.
# An empty string means no setup has been done yet.
# If the next job is for a different component, a setup changeover is required.
ws_comp: dict[str, str] = {ws: "" for ws in production_ws}

# ── Event logs ────────────────────────────────────────────────────────────────
# These lists are populated during the simulation and later written to CSV.
gantt_rows:      list[dict] = []   # one row per setup or processing event
throughput_rows: list[dict] = []   # one row per completed order
wait_rows:       list[dict] = []   # one row per scheduled job (tracks queue wait)

# cost_acc[ws][cost_type]: cumulative costs per workstation over all orders
cost_acc: dict[str, dict[str, float]] = {
    ws: {"setup": 0.0, "operating": 0.0, "transport": 0.0}
    for ws in production_ws
}

# ── BOM explosion ─────────────────────────────────────────────────────────────
def explode_bom(prod: str) -> dict[str, int]:
    """
    Given a product ID, return the total number of units of every component
    needed to produce exactly one unit of that product.

    The BOM is a tree (possibly with shared nodes). Explosion walks top-down
    level by level so that components shared by multiple parents accumulate
    their quantities correctly before their own children are expanded.

    Example — if PROD_1 needs 2× COMP_A and COMP_A needs 3× RAW_1, the result
    is {PROD_1: 1, COMP_A: 2, RAW_1: 6}.

    Returns: dict mapping component ID → total units required
    """
    needs: dict[str, int] = {prod: 1}
    max_level: int = comp_level[prod]

    # Iterate from the product level down to level 1 (stop before 0 because
    # raw materials have no children to expand).
    for lvl in range(max_level, 0, -1):
        for comp, qty in list(needs.items()):
            if comp_level[comp] != lvl:
                continue
            for child, child_qty in bom_inputs.get(comp, []):
                needs[child] = needs.get(child, 0) + qty * child_qty

    return needs


# ── Schedule one job ──────────────────────────────────────────────────────────
def schedule(comp: str, qty: int, ready_t: float, order: int) -> float:
    """
    Schedule the production of `qty` units of `comp`, starting no earlier than
    `ready_t` (the time by which all input materials for this component are
    available). Logs the resulting events and costs.

    Workstation selection: among all workstations capable of producing `comp`,
    pick the one whose projected finish time is earliest. Finish time accounts
    for the workstation's current availability and any required setup changeover.

    Setup changeover: if the selected workstation is currently configured for a
    different component, a setup period is inserted before processing begins.
    No setup is charged if the workstation is already configured for `comp`.

    Raw materials (level 0) are sourced directly from Inventory with no
    processing delay, so they are returned immediately at `ready_t`.

    Returns: the time (hours) at which the job is complete
    """
    if comp_level[comp] == 0:
        return ready_t  # raw materials require no production time

    cfgs: list[dict] = comp_configs[comp]

    def finish_time(cfg: dict) -> float:
        avail = max(ws_avail[cfg["ws"]], ready_t)
        setup = 0.0 if ws_comp[cfg["ws"]] == comp else cfg["setup_time"]
        return avail + setup + cfg["proc_time"] * qty

    best: dict      = min(cfgs, key=finish_time)
    ws: str         = best["ws"]
    avail: float    = max(ws_avail[ws], ready_t)
    new_setup: bool = ws_comp[ws] != comp
    setup_t: float  = best["setup_time"] if new_setup else 0.0

    setup_start: float = avail
    proc_start: float  = avail + setup_t
    proc_end: float    = proc_start + best["proc_time"] * qty

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

    # WaitTime: how long the job waited at the workstation before processing
    # started (i.e. proc_start minus the time inputs were ready).
    wait_rows.append({
        "Workstation": ws, "Component": comp,
        "Order": order, "WaitTime": proc_start - ready_t,
    })

    ws_avail[ws] = proc_end
    ws_comp[ws]  = comp
    return proc_end


# ── Run simulation ────────────────────────────────────────────────────────────
print(f"Running {N_ORDERS} orders...")
for order in range(1, N_ORDERS + 1):
    # Assign product in round-robin order across all available products
    prod: str = products[(order - 1) % len(products)]

    # Determine how many units of every component are needed for this order
    needs: dict[str, int] = explode_bom(prod)

    # Schedule level by level (bottom-up): raw materials first, then
    # intermediates, then the final product. A component can only start once
    # all its direct inputs are ready (comp_ready tracks their finish times).
    comp_ready: dict[str, float] = {}
    max_level: int = comp_level[prod]

    for lvl in range(0, max_level + 1):
        for comp, qty in needs.items():
            if comp_level[comp] != lvl:
                continue
            # This component can start as soon as its latest input is ready.
            inputs_ready: float = max(
                (comp_ready.get(inp, 0.0) for inp, _ in bom_inputs.get(comp, [])),
                default=0.0,
            )
            comp_ready[comp] = schedule(comp, qty, inputs_ready, order)

    prod_done: float = comp_ready[prod]
    throughput_rows.append({"Time": prod_done, "Products": order, "Product": prod})
    print(f"  Order {order} ({prod}) done at t={prod_done:.3f} h")

# ── Utilization ───────────────────────────────────────────────────────────────
# Compute how each workstation spent its total time across all orders.
total_time: float  = max(ws_avail.values())
gantt_df: pd.DataFrame = pd.DataFrame(gantt_rows)

util_rows: list[dict] = []
for ws in sorted(production_ws):
    ws_gantt = gantt_df[gantt_df["Workstation"] == ws]
    busy: float  = (ws_gantt[ws_gantt["Type"] == "processing"]["Finish"] -
                    ws_gantt[ws_gantt["Type"] == "processing"]["Start"]).sum()
    setup: float = (ws_gantt[ws_gantt["Type"] == "setup"]["Finish"] -
                    ws_gantt[ws_gantt["Type"] == "setup"]["Start"]).sum()
    idle: float  = max(total_time - busy - setup, 0.0)
    util_rows.append({"Workstation": ws, "Busy": busy, "Setup": setup, "Idle": idle})

# ── Write outputs ─────────────────────────────────────────────────────────────
os.makedirs(SIM_DIR, exist_ok=True)
gantt_df.to_csv(os.path.join(SIM_DIR, "gantt.csv"), index=False)
pd.DataFrame(util_rows).to_csv(os.path.join(SIM_DIR, "utilization.csv"), index=False)
pd.DataFrame(throughput_rows).to_csv(os.path.join(SIM_DIR, "throughput.csv"), index=False)
pd.DataFrame([
    {"Workstation": ws, "SetupCost": cost_acc[ws]["setup"],
     "OperatingCost": cost_acc[ws]["operating"], "TransportCost": cost_acc[ws]["transport"]}
    for ws in production_ws
]).to_csv(os.path.join(SIM_DIR, "costs.csv"), index=False)
pd.DataFrame(wait_rows).to_csv(os.path.join(SIM_DIR, "wait_times.csv"), index=False)

print(f"\nSimulation complete → sim_output/")
print(f"Total time span : {total_time:.3f} h")
print(f"Orders completed: {len(throughput_rows)}")
