#!/usr/bin/env python3
# Simple Assembly Factory — synthetic data generator.
# Builds an assembly-line factory from a YAML config and writes CSVs.
# Install dependencies: pip install pyyaml
#
# Run:  python generate.py

import os
import random
import csv
from dataclasses import dataclass
import yaml


@dataclass
class Component:
    id: str
    name: str
    level: int
    is_product: bool


@dataclass
class BomEdge:
    input: str
    output: str
    quantity: int


@dataclass
class Workstation:
    id: str
    name: str
    type: str


@dataclass
class Configuration:
    id: str
    workstation: str
    component: str
    processing_time: float
    setup_time: float
    setup_cost: float
    operating_cost: float


@dataclass
class LayoutEdge:
    origin: str
    destination: str
    capacity: float
    cost: float


# ── Core generation logic ──────────────────────────────────────────────────────

def _build_factory(
    n_products:    int,
    depth:         int,
    branch_min:    int,   branch_max: int,
    qty_min:       int,   qty_max:    int,
    sharing_ratio: float,
    n_ws:          int,
    prod_min:      int,   prod_max:   int,
    pt_r:  list,  st_r: list,
    sc_r:  list,  oc_r: list,
    topology: str,
    cap_r: list,  cost_r: list,
) -> dict:
    """
    Core factory generation logic. All parameters are passed explicitly so
    both generate_simple_assembly (YAML-driven) and generate_from_params
    (dict-driven) can share a single implementation.
    """

    assert n_products >= 1,           "n_products must be >= 1"
    assert depth >= 1,                "depth must be >= 1"
    assert branch_min >= 1,           "branching[0] must be >= 1"
    assert branch_max >= branch_min,  "branching range invalid"
    assert n_ws >= 1,                 "workstations_count must be >= 1"
    assert topology in ("parallel", "linear"), \
        "topology must be 'parallel' or 'linear'"

    components:   list[Component]   = []
    bom_edges:    list[BomEdge]     = []
    producible:   list[str]         = []
    shared_pool:  dict[int, list[str]] = {}
    counter:      dict[int, int]    = {}

    # --- BOM tree ----------------------------------------------------------------
    def build_subtree(parent_id: str, parent_level: int):
        if parent_level <= 0:
            return
        child_level = parent_level - 1
        for _ in range(random.randint(branch_min, branch_max)):
            pool = shared_pool.get(child_level, [])
            if pool and random.random() < sharing_ratio:
                child = random.choice(pool)
            else:
                counter[child_level] = counter.get(child_level, 0) + 1
                n = counter[child_level]
                prefix = "RAW" if child_level == 0 else "COMP"
                child  = f"{prefix}_L{child_level}_{n}"
                components.append(Component(
                    id=child, name=f"{prefix} L{child_level} #{n}",
                    level=child_level, is_product=False,
                ))
                shared_pool.setdefault(child_level, []).append(child)
                if child_level > 0:
                    producible.append(child)
                build_subtree(child, child_level)
            bom_edges.append(BomEdge(
                input=child, output=parent_id,
                quantity=random.randint(qty_min, qty_max),
            ))

    for p in range(1, n_products + 1):
        pid = f"PROD_{p}"
        components.append(Component(id=pid, name=f"Product {p}",
                                    level=depth, is_product=True))
        producible.append(pid)
        build_subtree(pid, depth)

    # --- Workstations ------------------------------------------------------------
    workstations: list[Workstation] = [
        Workstation(id="Inv", name="Inventory",          type="source"),
        Workstation(id="QI",  name="Quality Inspection", type="sink"),
    ]
    assembly_ws: list[str] = []
    for i in range(1, n_ws + 1):
        ws_id = f"WS_{i}"
        workstations.append(Workstation(id=ws_id, name=f"Assembly {i}", type="production"))
        assembly_ws.append(ws_id)

    # --- Configurations ----------------------------------------------------------
    prod_min = min(prod_min, n_ws)
    prod_max = max(prod_min, min(prod_max, n_ws))

    def usample(r: list) -> float:
        return random.uniform(r[0], r[1])

    configurations: list[Configuration] = []
    cfg_idx = 0
    for comp in producible:
        n = random.randint(prod_min, prod_max)
        chosen = random.sample(assembly_ws, n)
        for ws in chosen:
            cfg_idx += 1
            configurations.append(Configuration(
                id=f"CFG_{cfg_idx}", workstation=ws, component=comp,
                processing_time=usample(pt_r), setup_time=usample(st_r),
                setup_cost=usample(sc_r),       operating_cost=usample(oc_r),
            ))

    # --- Layout ------------------------------------------------------------------
    layout_edges: list[LayoutEdge] = []

    def edge(o: str, d: str):
        layout_edges.append(LayoutEdge(
            origin=o, destination=d,
            capacity=float(random.randint(int(cap_r[0]), int(cap_r[1]))),
            cost=usample(cost_r),
        ))

    if topology == "parallel":
        for ws in assembly_ws:
            edge("Inv", ws)
            edge(ws, "QI")
    else:
        edge("Inv", assembly_ws[0])
        for i in range(len(assembly_ws) - 1):
            edge(assembly_ws[i], assembly_ws[i + 1])
        edge(assembly_ws[-1], "QI")

    # --- Validate ----------------------------------------------------------------
    produced = {c.component for c in configurations}
    for comp in producible:
        assert comp in produced, f"Producible component {comp} has no configuration"

    return dict(
        components=components, bom_edges=bom_edges,
        workstations=workstations, configurations=configurations,
        layout_edges=layout_edges, producible=producible,
    )


def _write_csvs(result: dict, out_dir: str):
    """Write the five factory CSVs to out_dir."""
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "components.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Name", "Level", "IsProduct"])
        for c in result["components"]:
            w.writerow([c.id, c.name, c.level, c.is_product])

    with open(os.path.join(out_dir, "bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Input", "Output", "Quantity"])
        for e in result["bom_edges"]:
            w.writerow([e.input, e.output, e.quantity])

    with open(os.path.join(out_dir, "workstations.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Name", "Type"])
        for ws in result["workstations"]:
            w.writerow([ws.id, ws.name, ws.type])

    with open(os.path.join(out_dir, "configurations.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Workstation", "Component",
                    "ProcessingTime", "SetupTime", "SetupCost", "OperatingCost"])
        for c in result["configurations"]:
            w.writerow([c.id, c.workstation, c.component,
                        c.processing_time, c.setup_time, c.setup_cost, c.operating_cost])

    with open(os.path.join(out_dir, "layout.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Origin", "Destination", "Capacity", "Cost"])
        for e in result["layout_edges"]:
            w.writerow([e.origin, e.destination, e.capacity, e.cost])


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_simple_assembly(config_path: str, export_csv: bool = True) -> dict:
    """
    Generate a factory from a YAML config file.
    Returns the factory as a dict of dataclass lists.
    When export_csv=True, writes the five CSVs to cfg["output"]["directory"].
    """
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    seed = cfg["metadata"].get("seed")
    if seed is not None:
        random.seed(seed)

    bom  = cfg["bom"]
    ws   = cfg["workstations"]
    cc   = cfg["configurations"]
    lay  = cfg["layout"]

    result = _build_factory(
        n_products    = bom["n_products"],
        depth         = bom["depth"],
        branch_min    = bom["branching"][0],
        branch_max    = bom["branching"][1],
        qty_min       = bom["quantity"][0],
        qty_max       = bom["quantity"][1],
        sharing_ratio = bom.get("sharing_ratio", 0.0),
        n_ws          = ws["count"],
        prod_min      = cc["producers_per_component"][0],
        prod_max      = cc["producers_per_component"][1],
        pt_r          = cc["processing_time"],
        st_r          = cc["setup_time"],
        sc_r          = cc["setup_cost"],
        oc_r          = cc["operating_cost"],
        topology      = lay.get("topology", "parallel"),
        cap_r         = lay["flow_capacity"],
        cost_r        = lay["transport_cost"],
    )

    if export_csv:
        rel     = cfg["output"]["directory"]
        script_dir = os.path.dirname(os.path.abspath(__file__))
        out_dir = rel if os.path.isabs(rel) else os.path.normpath(
            os.path.join(script_dir, rel))
        _write_csvs(result, out_dir)
        result["out_dir"] = out_dir
    else:
        result["out_dir"] = None

    return result


def generate_from_params(params: dict, export_csv: bool = False,
                         out_dir: str | None = None) -> dict:
    """
    Generate a factory from a parameter dictionary.
    Intended for programmatic use (e.g. parameter sweeps).

    Expected keys
    -------------
    n_products, depth, branching, quantity, sharing_ratio,
    workstations_count, producers_per_component,
    processing_time, setup_time, setup_cost, operating_cost,
    topology, flow_capacity, transport_cost

    Optional keys
    -------------
    seed  (int | None)
    """
    seed = params.get("seed")
    if seed is not None:
        random.seed(seed)

    result = _build_factory(
        n_products    = params["n_products"],
        depth         = params["depth"],
        branch_min    = params["branching"][0],
        branch_max    = params["branching"][1],
        qty_min       = params["quantity"][0],
        qty_max       = params["quantity"][1],
        sharing_ratio = params.get("sharing_ratio", 0.0),
        n_ws          = params["workstations_count"],
        prod_min      = params["producers_per_component"][0],
        prod_max      = params["producers_per_component"][1],
        pt_r          = params["processing_time"],
        st_r          = params["setup_time"],
        sc_r          = params["setup_cost"],
        oc_r          = params["operating_cost"],
        topology      = params.get("topology", "parallel"),
        cap_r         = params["flow_capacity"],
        cost_r        = params["transport_cost"],
    )

    if export_csv and out_dir:
        _write_csvs(result, out_dir)
        result["out_dir"] = out_dir
    else:
        result["out_dir"] = None

    return result


# ── Script entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    result = generate_simple_assembly(os.path.join(script_dir, "..", "config.yaml"))
    print(f"Components:     {len(result['components'])}")
    print(f"BOM edges:      {len(result['bom_edges'])}")
    print(f"Workstations:   {len(result['workstations'])}")
    print(f"Configurations: {len(result['configurations'])}")
    print(f"Layout edges:   {len(result['layout_edges'])}")
    print(f"Exported →      {result['out_dir']}")
