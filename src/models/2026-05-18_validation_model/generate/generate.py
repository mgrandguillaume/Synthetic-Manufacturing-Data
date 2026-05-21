#!/usr/bin/env python3
# Simple Assembly Factory — synthetic data generator.
# Builds an assembly-line factory from a YAML config and writes CSVs.
#
# Run:  python generate.py   (or via the top-level run.py)

import math
import os
import random
import sys
import csv
from collections import defaultdict
from dataclasses import dataclass

# Add the model root to sys.path so utils (and other packages) are importable
# whether this module is run directly or imported as part of a package.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import utils


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


# ── Stage-size helper ──────────────────────────────────────────────────────────

def _sample_stage_sizes(n_ws: int, depth: int,
                        stage_balance: float | None) -> list[int]:
    """
    Partition n_ws workstations into `depth` stages.

    stage_balance controls how evenly the workstations are distributed:

      None         : original floor-based uniform split (backward compatible).
      high (≥ 10)  : near-uniform; stages differ by at most 1 workstation.
      1.0          : flat Dirichlet — uniformly random over all valid partitions.
      low  (≤ 0.5) : skewed — a few stages absorb most workstations.

    The Dirichlet path samples k independent Gamma(stage_balance, 1) variates,
    normalises them to sum to n_ws, then applies largest-remainder rounding so
    the result always consists of positive integers summing to exactly n_ws.

    Requires n_ws >= depth >= 1 (each stage must receive at least one WS).
    """
    assert n_ws >= depth >= 1, (
        f"workstations_count ({n_ws}) must be >= depth ({depth})"
    )

    if depth == 1:
        return [n_ws]

    if stage_balance is None:
        # Original behaviour: floor-based uniform split.
        sizes = []
        for lvl in range(1, depth + 1):
            start = math.floor((lvl - 1) * n_ws / depth)
            end   = math.floor(lvl       * n_ws / depth)
            sizes.append(end - start)
        return sizes

    # Dirichlet-based random partition via the Gamma-distribution trick:
    #   (X_1, ..., X_k) ~ Dirichlet(c,...,c)  iff  X_i = G_i / sum(G_j)
    # where G_i ~ Gamma(c, 1) independently.
    gammas = [random.gammavariate(stage_balance, 1.0) for _ in range(depth)]
    total  = sum(gammas)
    floats = [g / total * n_ws for g in gammas]

    # Largest-remainder rounding: guaranteed to sum to exactly n_ws.
    floors    = [int(f) for f in floats]
    order     = sorted(range(depth), key=lambda i: floats[i] - floors[i], reverse=True)
    shortfall = n_ws - sum(floors)
    for i in range(shortfall):
        floors[order[i]] += 1

    # Enforce minimum of 1 per stage by borrowing from the largest stage(s).
    for i in range(depth):
        while floors[i] < 1:
            src = max(range(depth), key=lambda j: floors[j])
            floors[src] -= 1
            floors[i]   += 1

    return floors


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
    cap_r: list,  cost_r: list,
    stage_balance: float | None = None,
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

    # --- Rename components with product-ownership suffix -------------------------
    # After the full BOM is built we know which products each component feeds
    # into (directly or transitively).  We encode this in the component ID:
    #
    #   COMP_L3_2_(P1)      — exclusive to product 1
    #   COMP_L3_2_(P1,P2)   — shared between products 1 and 2
    #   RAW_L0_1_(P2)       — raw material only used in product 2's subtree
    #
    # Products themselves keep their original IDs (PROD_1, PROD_2, …).

    # 1. Walk the BOM downward from each product to find transitive ownership.
    _children_of: dict[str, list[str]] = defaultdict(list)
    for e in bom_edges:
        _children_of[e.output].append(e.input)

    _comp_products: dict[str, set[str]] = defaultdict(set)
    for comp in components:
        if comp.is_product:
            stack, visited = [comp.id], set()
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                _comp_products[node].add(comp.id)
                stack.extend(_children_of[node])

    # 2. Build old-id → new-id map.
    def _prod_suffix(comp_id: str) -> str:
        prods = sorted(
            _comp_products.get(comp_id, set()),
            key=lambda pid: int(pid.split("_")[1]),
        )
        if not prods:
            return ""
        return "_(" + ",".join(f"P{pid.split('_')[1]}" for pid in prods) + ")"

    _rename: dict[str, str] = {}
    for comp in components:
        if comp.is_product:
            _rename[comp.id] = comp.id          # products keep their IDs
        else:
            _rename[comp.id] = comp.id + _prod_suffix(comp.id)

    # 3. Apply rename to all structures that carry component IDs.
    for comp in components:
        if not comp.is_product:
            name_suffix = _prod_suffix(comp.id).lstrip("_")  # "(P1,P2)" not "_(P1,P2)"
            comp.name = comp.name + (f" {name_suffix}" if name_suffix else "")
            comp.id   = _rename[comp.id]

    for edge in bom_edges:
        edge.input  = _rename[edge.input]
        edge.output = _rename[edge.output]

    producible = [_rename[c] for c in producible]

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

    # --- Stage assignment --------------------------------------------------------
    # Build a level lookup from the components list constructed above.
    comp_level: dict[str, int] = {c.id: c.level for c in components}
    # Divide workstations into `depth` stages, one stage per BOM level.
    # A workstation in stage l can only produce components at BOM level l.
    # _sample_stage_sizes handles both uniform (stage_balance=None) and
    # Dirichlet-random (stage_balance=float) distributions.
    sizes = _sample_stage_sizes(len(assembly_ws), depth, stage_balance)
    stage_ws: dict[int, list[str]] = {}
    cursor = 0
    for lvl in range(1, depth + 1):
        stage_ws[lvl] = assembly_ws[cursor : cursor + sizes[lvl - 1]]
        cursor += sizes[lvl - 1]
    sizes_str = ", ".join(
        f"stage {l}:{len(stage_ws[l])}" for l in range(1, depth + 1)
    )
    print(f"  [generate] stage assignment ({sizes_str})")

    # --- Configurations ----------------------------------------------------------
    def usample(r: list) -> float:
        return random.uniform(r[0], r[1])

    configurations: list[Configuration] = []
    cfg_idx = 0
    for comp in producible:
        lvl      = comp_level[comp]
        eligible = stage_ws.get(lvl, assembly_ws)
        # Clamp producers_per_component to the number of eligible workstations.
        lo = min(prod_min, len(eligible))
        hi = max(lo, min(prod_max, len(eligible)))
        chosen = random.sample(eligible, random.randint(lo, hi))
        for ws in chosen:
            cfg_idx += 1
            configurations.append(Configuration(
                id=f"CFG_{cfg_idx}", workstation=ws, component=comp,
                processing_time=usample(pt_r), setup_time=usample(st_r),
                setup_cost=usample(sc_r),       operating_cost=usample(oc_r),
            ))

    # --- Force-assign idle workstations ------------------------------------------
    # The random sampling above does not guarantee every workstation receives at
    # least one configuration.  A workstation with zero configurations is
    # permanently idle: it occupies a layout slot and draws transport edges but
    # never produces anything, which distorts both α and simulation results.
    #
    # Fix: for each stage, find any workstation that was skipped and assign it
    # the component in that stage that currently has the fewest producers.
    # "Fewest producers" matches what a real planner would do — add redundancy
    # at the most constrained point.  A warning is printed so the caller knows
    # forced assignment occurred.
    ws_assigned: set[str] = {c.workstation for c in configurations}
    # Count how many producers each component currently has
    comp_producer_count: dict[str, int] = defaultdict(int)
    for c in configurations:
        comp_producer_count[c.component] += 1

    for lvl in range(1, depth + 1):
        stage_comps = [comp for comp in producible if comp_level[comp] == lvl]
        if not stage_comps:
            continue
        for ws in stage_ws.get(lvl, assembly_ws):
            if ws not in ws_assigned:
                # Pick the component at this level with the fewest existing producers
                target = min(stage_comps, key=lambda c: comp_producer_count[c])
                cfg_idx += 1
                configurations.append(Configuration(
                    id=f"CFG_{cfg_idx}", workstation=ws, component=target,
                    processing_time=usample(pt_r), setup_time=usample(st_r),
                    setup_cost=usample(sc_r),       operating_cost=usample(oc_r),
                ))
                comp_producer_count[target] += 1
                ws_assigned.add(ws)
                print(f"  [generate] forced assignment: {ws} -> {target} "
                      f"(was idle at stage {lvl})")

    # --- Layout ------------------------------------------------------------------
    # Edges are derived from the BOM: for every BOM dependency (comp_in is an
    # input to comp_out) we connect every workstation that produces comp_in to
    # every workstation that produces comp_out.  Raw materials (level 0) are
    # treated as produced by Inv; finished products connect their producers to QI.
    #
    # Multiple BOM paths may share the same physical (origin, destination) pair —
    # e.g. WS_3 sends two different components to WS_7.  These are deduplicated
    # into a single layout edge (one physical transport link, one cost/capacity).
    #
    # This gives a layout that is a faithful projection of the BOM onto the
    # factory floor: every edge carries material that actually needs to move,
    # and no phantom connections exist.

    # comp_id → list of workstation IDs that can produce it; Inv for raws.
    _comp_to_ws: dict[str, list[str]] = defaultdict(list)
    for cfg in configurations:
        _comp_to_ws[cfg.component].append(cfg.workstation)
    for comp in components:
        if comp.level == 0:
            _comp_to_ws[comp.id].append("Inv")

    # Collect unique (origin, destination) pairs.
    _edge_set: set[tuple[str, str]] = set()
    for bom_e in bom_edges:
        for ws_in in _comp_to_ws.get(bom_e.input, []):
            for ws_out in _comp_to_ws.get(bom_e.output, []):
                if ws_in != ws_out:          # guard against self-loops
                    _edge_set.add((ws_in, ws_out))

    # Products ship to QI once assembled.
    for comp in components:
        if comp.is_product:
            for ws in _comp_to_ws.get(comp.id, []):
                _edge_set.add((ws, "QI"))

    # Create one LayoutEdge per unique pair with fresh random capacity and cost.
    layout_edges: list[LayoutEdge] = [
        LayoutEdge(
            origin=o, destination=d,
            capacity=float(random.randint(int(cap_r[0]), int(cap_r[1]))),
            cost=usample(cost_r),
        )
        for o, d in sorted(_edge_set)
    ]

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

    Builds a params dict from the config and delegates to generate_from_params
    so all factory construction goes through a single code path.
    """
    cfg = utils.load_config(config_path)

    bom = cfg["bom"]
    ws  = cfg["workstations"]
    cc  = cfg["configurations"]
    lay = cfg["layout"]

    params = {
        "seed":                    cfg["metadata"].get("seed"),
        "n_products":              bom["n_products"],
        "depth":                   bom["depth"],
        "branching":               bom["branching"],
        "quantity":                bom["quantity"],
        "sharing_ratio":           bom.get("sharing_ratio", 0.0),
        "workstations_count":      ws["count"],
        "stage_balance":           ws.get("stage_balance", None),
        "producers_per_component": cc["producers_per_component"],
        "processing_time":         cc["processing_time"],
        "setup_time":              cc["setup_time"],
        "setup_cost":              cc["setup_cost"],
        "operating_cost":          cc["operating_cost"],
        "flow_capacity":           lay["flow_capacity"],
        "transport_cost":          lay["transport_cost"],
    }

    out_dir = None
    if export_csv:
        rel        = cfg["output"]["directory"]
        script_dir = os.path.dirname(os.path.abspath(__file__))
        out_dir    = rel if os.path.isabs(rel) else os.path.normpath(
            os.path.join(script_dir, rel))

    return generate_from_params(params, export_csv=export_csv, out_dir=out_dir)


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
    flow_capacity, transport_cost

    Optional keys
    -------------
    seed          (int | None)
    stage_balance (float | None) — Dirichlet concentration for stage sizing;
                                   None = uniform floor-based split (default)
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
        cap_r         = params["flow_capacity"],
        cost_r        = params["transport_cost"],
        stage_balance = params.get("stage_balance", None),
    )

    if export_csv and out_dir:
        _write_csvs(result, out_dir)
        result["out_dir"] = out_dir
    else:
        result["out_dir"] = None

    return result


# ── Script entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    script_dir  = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.normpath(os.path.join(script_dir, "..", "config.yaml"))
    result = generate_simple_assembly(config_path)
    print(f"Config:         {config_path}")
    print(f"Components:     {len(result['components'])}")
    print(f"BOM edges:      {len(result['bom_edges'])}")
    print(f"Workstations:   {len(result['workstations'])}")
    print(f"Configurations: {len(result['configurations'])}")
    print(f"Layout edges:   {len(result['layout_edges'])}")
    print(f"Exported ->     {result['out_dir']}")
