import pandas as pd
import os

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen_output")
SIM_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim_output")
N_ORDERS   = 10

# ── Load data ─────────────────────────────────────────────────────────────────
components_df   = pd.read_csv(os.path.join(OUTPUT_DIR, "components.csv"))
bom_df          = pd.read_csv(os.path.join(OUTPUT_DIR, "bom.csv"))
workstations_df = pd.read_csv(os.path.join(OUTPUT_DIR, "workstations.csv"))
configs_df      = pd.read_csv(os.path.join(OUTPUT_DIR, "configurations.csv"))
layout_df       = pd.read_csv(os.path.join(OUTPUT_DIR, "layout.csv"))

# ── Lookup structures ─────────────────────────────────────────────────────────
# bom_inputs[parent] = [(child, quantity), ...]
bom_inputs = {}
for _, row in bom_df.iterrows():
    bom_inputs.setdefault(row["Output"], []).append((row["Input"], row["Quantity"]))

comp_level = dict(zip(components_df["ID"], components_df["Level"]))
products   = components_df[components_df["IsProduct"] == True]["ID"].tolist()

# comp_configs[component] = [{"ws", "proc_time", "setup_time", "setup_cost", "op_cost"}, ...]
comp_configs = {}
for _, row in configs_df.iterrows():
    comp_configs.setdefault(row["Component"], []).append({
        "ws":         row["Workstation"],
        "proc_time":  row["ProcessingTime"],
        "setup_time": row["SetupTime"],
        "setup_cost": row["SetupCost"],
        "op_cost":    row["OperatingCost"],
    })

transport_cost_map = {
    (row["Origin"], row["Destination"]): row["Cost"]
    for _, row in layout_df.iterrows()
}

# ── Simulation state ──────────────────────────────────────────────────────────
production_ws = workstations_df[workstations_df["Type"] == "production"]["ID"].tolist()

ws_avail = {ws: 0.0 for ws in production_ws}  # when each WS next becomes free
ws_comp  = {ws: ""  for ws in production_ws}  # component each WS is set up for

# ── Event logs ────────────────────────────────────────────────────────────────
gantt_rows      = []
throughput_rows = []
wait_rows       = []
cost_acc        = {ws: {"setup": 0.0, "operating": 0.0, "transport": 0.0}
                   for ws in production_ws}

# ── BOM explosion ─────────────────────────────────────────────────────────────
def explode_bom(prod):
    """
    Returns a dict {component: total_units_needed} for one unit of prod.
    Processes level-by-level (top-down) so shared components accumulate correctly.
    """
    needs = {prod: 1}
    max_level = comp_level[prod]
    for lvl in range(max_level, 0, -1):
        for comp, qty in list(needs.items()):
            if comp_level[comp] != lvl:
                continue
            for child, child_qty in bom_inputs.get(comp, []):
                needs[child] = needs.get(child, 0) + qty * child_qty
    return needs

# ── Schedule one job ──────────────────────────────────────────────────────────
def schedule(comp, qty, ready_t, order):
    """
    Assigns `qty` units of `comp` to the workstation that finishes earliest.
    Returns the time at which the job is complete.
    """
    if comp_level[comp] == 0:
        return ready_t  # raw material: available from Inventory instantly

    cfgs = comp_configs[comp]

    # Pick the workstation that finishes this job earliest
    def finish_time(cfg):
        avail = max(ws_avail[cfg["ws"]], ready_t)
        setup = 0.0 if ws_comp[cfg["ws"]] == comp else cfg["setup_time"]
        return avail + setup + cfg["proc_time"] * qty

    best = min(cfgs, key=finish_time)
    ws        = best["ws"]
    avail     = max(ws_avail[ws], ready_t)
    new_setup = ws_comp[ws] != comp
    setup_t   = best["setup_time"] if new_setup else 0.0

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

# ── Run simulation ────────────────────────────────────────────────────────────
print(f"Running {N_ORDERS} orders...")
for order in range(1, N_ORDERS + 1):
    prod  = products[(order - 1) % len(products)]
    needs = explode_bom(prod)

    # Process level by level: raw (0) → intermediates → product
    comp_ready = {}
    max_level  = comp_level[prod]
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
    print(f"  Order {order} ({prod}) done at t={prod_done:.3f} h")

# ── Utilization ───────────────────────────────────────────────────────────────
total_time = max(ws_avail.values())
gantt_df   = pd.DataFrame(gantt_rows)

util_rows = []
for ws in sorted(production_ws):
    ws_gantt = gantt_df[gantt_df["Workstation"] == ws]
    busy  = (ws_gantt[ws_gantt["Type"] == "processing"]["Finish"] -
             ws_gantt[ws_gantt["Type"] == "processing"]["Start"]).sum()
    setup = (ws_gantt[ws_gantt["Type"] == "setup"]["Finish"] -
             ws_gantt[ws_gantt["Type"] == "setup"]["Start"]).sum()
    idle  = max(total_time - busy - setup, 0.0)
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
