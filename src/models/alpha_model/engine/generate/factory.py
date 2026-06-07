"""
Factory generation machinery for the Assembly Factory generator.

Contains all logic for constructing the five factory tables from raw
parameters.  The public entry point is build_factory(); everything else
is an internal helper.

Internal helpers (prefix _)
----------------------------
_pt_range(assembly_type, depth, variation)
    Compute a [min, max] processing-time range from the assembly formula.
_sample_stage_sizes(n_ws, depth, stage_balance)
    Partition n_ws workstations into depth stages (uniform or Dirichlet).

Public function
---------------
build_factory(n_products, depth, ...) -> dict
    Build and return all five factory tables as lists of dataclass instances.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict

from .models import (
    BomEdge,
    Component,
    Configuration,
    LayoutEdge,
    Workstation,
)


# ── Assembly-type processing-time formula ──────────────────────────────────────
#
#   processing_time = a · C^b   (exponential approximation)
#
#   C (product complexity) grows monotonically with BOM depth for a fixed
#   branching factor; depth is used as a proxy for C in the implementation.
#
#   assembly_type   a       b
#   low             0.33    1.39
#   medium          0.28    1.45
#   high            0.12    1.79
#
#   A ±variation fraction is applied around this mean so each configuration
#   still gets its own sampled value.

_ASSEMBLY_PARAMS: dict[str, tuple[float, float]] = {
    "low":    (0.33, 1.39),
    "medium": (0.28, 1.45),
    "high":   (0.12, 1.79),
}


def _pt_range(assembly_type: str, depth: int, variation: float) -> list[float]:
    """
    Return a [min, max] processing-time range from the assembly formula.

    processing_time = a · C^b  ±  variation fraction

    C (product complexity) grows monotonically with BOM depth for a fixed
    branching factor; depth is used here as a proxy for C.

    Parameters
    ----------
    assembly_type : "low" | "medium" | "high"
    depth         : BOM depth (proxy for product complexity C)
    variation     : fractional spread, e.g. 0.10 for ±10 %
    """
    a, b = _ASSEMBLY_PARAMS[assembly_type]
    pt_mean = a * (depth ** b)
    return [pt_mean * (1.0 - variation), pt_mean * (1.0 + variation)]


# ── Stage-size helper ──────────────────────────────────────────────────────────

def _sample_stage_sizes(n_ws: int, depth: int,
                        stage_balance: float | None) -> list[int]:
    """
    Partition n_ws workstations into `depth` stages.

    stage_balance controls how evenly workstations are distributed:

      None         : original floor-based uniform split (backward compatible).
      high (≥ 10)  : near-uniform; stages differ by at most 1 workstation.
      1.0          : flat Dirichlet — uniformly random over all valid partitions.
      low  (≤ 0.5) : skewed — a few stages absorb most workstations.

    Uses Gamma-distribution trick: sample k Gamma(stage_balance, 1) variates,
    normalise to sum to n_ws, then apply largest-remainder rounding so the
    result always consists of positive integers summing to exactly n_ws.

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

    # Dirichlet-based random partition.
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


# ── Core factory builder ───────────────────────────────────────────────────────

def build_factory(
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
    Build all five factory tables from raw parameters.

    Parameters
    ----------
    n_products    : number of finished products
    depth         : BOM depth (levels below product level)
    branch_min/max: branching factor range at each BOM level
    qty_min/max   : quantity-per-edge range in the BOM
    sharing_ratio : probability of reusing an existing component at each level
    n_ws          : number of assembly workstations
    prod_min/max  : producers-per-component range
    pt_r          : [min, max] processing-time range (hours)
    st_r          : [min, max] setup-time range (hours)
    sc_r          : [min, max] setup-cost range
    oc_r          : [min, max] operating-cost range
    cap_r         : [min, max] flow-capacity range
    cost_r        : [min, max] transport-cost range
    stage_balance : Dirichlet concentration for stage sizing; None = uniform

    Returns
    -------
    dict with keys: components, bom_edges, workstations, configurations,
                    layout_edges, producible
    """

    assert n_products >= 1,           "n_products must be >= 1"
    assert depth >= 1,                "depth must be >= 1"
    assert branch_min >= 1,           "branching[0] must be >= 1"
    assert branch_max >= branch_min,  "branching range invalid"
    assert n_ws >= 1,                 "workstations_count must be >= 1"

    def _usample(r: list) -> float:
        return random.uniform(r[0], r[1])

    # ── BOM tree ───────────────────────────────────────────────────────────────

    components:  list[Component] = []
    bom_edges:   list[BomEdge]   = []
    producible:  list[str]       = []
    shared_pool: dict[int, list[str]] = {}
    counter:     dict[int, int]  = {}

    def _build_subtree(parent_id: str, parent_level: int) -> None:
        if parent_level <= 0:
            return
        child_level = parent_level - 1
        already_chosen: set[str] = set()   # prevent same child twice per parent
        for _ in range(random.randint(branch_min, branch_max)):
            # Exclude components already chosen for this parent so that each
            # input type is distinct.  Picking the same component twice would
            # silently reduce the effective branching factor and create
            # duplicate BOM edges (same parent→child pair), which causes
            # stock to go negative in the simulator.
            pool = [c for c in shared_pool.get(child_level, [])
                    if c not in already_chosen]
            if pool and random.random() < sharing_ratio:
                child = random.choice(pool)
            else:
                counter[child_level] = counter.get(child_level, 0) + 1
                n      = counter[child_level]
                prefix = "RAW" if child_level == 0 else "COMP"
                child  = f"{prefix}_L{child_level}_{n}"
                components.append(Component(
                    id=child, name=f"{prefix} L{child_level} #{n}",
                    level=child_level, is_product=False,
                ))
                shared_pool.setdefault(child_level, []).append(child)
                if child_level > 0:
                    producible.append(child)
                _build_subtree(child, child_level)
            already_chosen.add(child)
            bom_edges.append(BomEdge(
                input=child, output=parent_id,
                quantity=random.randint(qty_min, qty_max),
            ))

    for p in range(1, n_products + 1):
        pid = f"PROD_{p}"
        components.append(Component(id=pid, name=f"Product {p}",
                                    level=depth, is_product=True))
        producible.append(pid)
        _build_subtree(pid, depth)

    # ── Rename components with product-ownership suffix ────────────────────────
    #
    # After the full BOM is built we know which products each component feeds
    # into (directly or transitively).  We encode this in the component ID:
    #
    #   COMP_L3_2_(P1)      — exclusive to product 1
    #   COMP_L3_2_(P1,P2)   — shared between products 1 and 2
    #   RAW_L0_1_(P2)       — raw material only used in product 2's subtree
    #
    # Products themselves keep their original IDs (PROD_1, PROD_2, …).

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
            _rename[comp.id] = comp.id
        else:
            _rename[comp.id] = comp.id + _prod_suffix(comp.id)

    for comp in components:
        if not comp.is_product:
            name_suffix = _prod_suffix(comp.id).lstrip("_")
            comp.name = comp.name + (f" {name_suffix}" if name_suffix else "")
            comp.id   = _rename[comp.id]

    for edge in bom_edges:
        edge.input  = _rename[edge.input]
        edge.output = _rename[edge.output]

    producible = [_rename[c] for c in producible]

    # ── Workstations ───────────────────────────────────────────────────────────

    workstations: list[Workstation] = [
        Workstation(id="Inv", name="Inventory",          type="source"),
        Workstation(id="QI",  name="Quality Inspection", type="sink"),
    ]
    assembly_ws: list[str] = []
    for i in range(1, n_ws + 1):
        ws_id = f"WS_{i}"
        workstations.append(Workstation(id=ws_id, name=f"Assembly {i}", type="production"))
        assembly_ws.append(ws_id)

    # ── Stage assignment ───────────────────────────────────────────────────────

    comp_level: dict[str, int] = {c.id: c.level for c in components}
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

    # ── Configurations ─────────────────────────────────────────────────────────

    configurations: list[Configuration] = []
    cfg_idx = 0
    for comp in producible:
        lvl      = comp_level[comp]
        eligible = stage_ws.get(lvl, assembly_ws)
        lo = min(prod_min, len(eligible))
        hi = max(lo, min(prod_max, len(eligible)))
        chosen = random.sample(eligible, random.randint(lo, hi))
        for ws in chosen:
            cfg_idx += 1
            configurations.append(Configuration(
                id=f"CFG_{cfg_idx}", workstation=ws, component=comp,
                processing_time=_usample(pt_r), setup_time=_usample(st_r),
                setup_cost=_usample(sc_r),       operating_cost=_usample(oc_r),
            ))

    # ── Force-assign idle workstations ─────────────────────────────────────────
    #
    # Random sampling may leave some workstations without any configuration.
    # A permanently idle workstation distorts layout and simulation results.
    # Fix: assign each idle workstation to the component in its stage that
    # currently has the fewest producers ("add redundancy at the bottleneck").

    ws_assigned: set[str] = {c.workstation for c in configurations}
    comp_producer_count: dict[str, int] = defaultdict(int)
    for c in configurations:
        comp_producer_count[c.component] += 1

    for lvl in range(1, depth + 1):
        stage_comps = [comp for comp in producible if comp_level[comp] == lvl]
        if not stage_comps:
            continue
        for ws in stage_ws.get(lvl, assembly_ws):
            if ws not in ws_assigned:
                target = min(stage_comps, key=lambda c: comp_producer_count[c])
                cfg_idx += 1
                configurations.append(Configuration(
                    id=f"CFG_{cfg_idx}", workstation=ws, component=target,
                    processing_time=_usample(pt_r), setup_time=_usample(st_r),
                    setup_cost=_usample(sc_r),       operating_cost=_usample(oc_r),
                ))
                comp_producer_count[target] += 1
                ws_assigned.add(ws)
                print(f"  [generate] forced assignment: {ws} -> {target} "
                      f"(was idle at stage {lvl})")

    # ── Layout ─────────────────────────────────────────────────────────────────
    #
    # Edges are derived from the BOM: for every BOM dependency (comp_in is an
    # input to comp_out) we connect every workstation that produces comp_in to
    # every workstation that produces comp_out.  Raw materials (level 0) are
    # treated as produced by Inv; finished products connect their producers to QI.
    # Multiple BOM paths may share the same (origin, destination) pair — these
    # are deduplicated into a single layout edge.

    _comp_to_ws: dict[str, list[str]] = defaultdict(list)
    for cfg in configurations:
        _comp_to_ws[cfg.component].append(cfg.workstation)
    for comp in components:
        if comp.level == 0:
            _comp_to_ws[comp.id].append("Inv")

    _edge_set: set[tuple[str, str]] = set()
    for bom_e in bom_edges:
        for ws_in in _comp_to_ws.get(bom_e.input, []):
            for ws_out in _comp_to_ws.get(bom_e.output, []):
                if ws_in != ws_out:
                    _edge_set.add((ws_in, ws_out))

    for comp in components:
        if comp.is_product:
            for ws in _comp_to_ws.get(comp.id, []):
                _edge_set.add((ws, "QI"))

    layout_edges: list[LayoutEdge] = [
        LayoutEdge(
            origin=o, destination=d,
            capacity=float(random.randint(int(cap_r[0]), int(cap_r[1]))),
            cost=_usample(cost_r),
        )
        for o, d in sorted(_edge_set)
    ]

    # ── Validate ───────────────────────────────────────────────────────────────

    produced = {c.component for c in configurations}
    for comp in producible:
        assert comp in produced, f"Producible component {comp} has no configuration"

    # ── Complexity ─────────────────────────────────────────────────────────────
    #
    # C(product) = number of distinct non-raw component types that the product
    # transitively depends on, excluding the product itself.
    #
    # Computed by BFS downward from each product through the BOM DAG.
    # Raw materials (level == 0) are excluded — they have infinite supply and
    # no production logic, so they do not contribute to scheduling complexity.
    #
    # The children_of map is rebuilt here from the final, renamed bom_edges
    # so that component IDs are consistent with the rest of the result dict.

    _final_children: dict[str, list[str]] = defaultdict(list)
    for e in bom_edges:
        _final_children[e.output].append(e.input)

    _comp_by_id_final: dict[str, Component] = {c.id: c for c in components}

    complexity: dict[str, int] = {}
    for comp in components:
        if not comp.is_product:
            continue
        visited: set[str] = set()
        stack = list(_final_children.get(comp.id, []))
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            stack.extend(_final_children.get(node, []))
        complexity[comp.id] = sum(
            1 for node in visited
            if node in _comp_by_id_final and _comp_by_id_final[node].level > 0
        )

    _c_vals = list(complexity.values())
    _c_mean = sum(_c_vals) / len(_c_vals) if _c_vals else 0.0
    _c_max  = max(_c_vals) if _c_vals else 0
    print(f"  [generate] complexity  "
          f"mean={_c_mean:.1f}  max={_c_max}  "
          f"({', '.join(f'{pid}:{c}' for pid, c in complexity.items())})")

    return dict(
        components=components, bom_edges=bom_edges,
        workstations=workstations, configurations=configurations,
        layout_edges=layout_edges, producible=producible,
        complexity=complexity,
    )


# ── Re-export pt_range for callers that need the formula directly ──────────────

pt_range = _pt_range
