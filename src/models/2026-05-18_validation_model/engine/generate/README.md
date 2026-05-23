# engine/generate

Builds a synthetic assembly factory from a set of parameters and exports it as five CSV tables.

---

## Files

| File | Purpose |
|---|---|
| `models.py` | Dataclass definitions and CSV export |
| `factory.py` | All factory construction logic |
| `generate.py` | Public API and script entry point |
| `visualize_gen.py` | vis.js layout visualizer — `build_html(gen_result) -> str` for the UI; runnable standalone to write `gen_output/layout_graph.html` |

---

## models.py — Data structures

Defines the five dataclasses that represent a complete factory:

| Class | Represents |
|---|---|
| `Component` | A node in the BOM (raw material, sub-assembly, or finished product) |
| `BomEdge` | A directed dependency: *input component* is consumed to produce *output component* |
| `Workstation` | A physical station (`source`, `production`, or `sink`) |
| `Configuration` | One recipe: a specific workstation that can produce a specific component, with its own processing time, setup time, and costs |
| `LayoutEdge` | A transport link between two workstations, with capacity and cost |

Also contains `write_csvs(result, out_dir)`, which serialises all five tables to `components.csv`, `bom.csv`, `workstations.csv`, `configurations.csv`, and `layout.csv`.

---

## factory.py — Construction logic

Contains `build_factory(...)`, the core function that constructs the factory step by step.  All randomness lives here; the public API in `generate.py` only seeds the RNG and unpacks config parameters.

### Step 1 — BOM tree

A recursive tree is grown from each product downward.  At each level, nodes are either freshly created or reused from a shared pool (controlled by `sharing_ratio`).  Raw materials sit at level 0 (infinite supply); the finished product sits at the deepest level (`depth`).

```
PROD_1  (level 2)
 ├─ COMP_L1_1  (level 1)
 │   ├─ RAW_L0_1  (level 0)
 │   └─ RAW_L0_2  (level 0)
 └─ COMP_L1_2  (level 1)
     └─ RAW_L0_1  (level 0)   ← shared node
```

### Step 2 — Ownership renaming

After the full BOM is built, each component's ID is extended with a suffix that encodes which product(s) it feeds into — transitively, not just directly.  This makes the data self-describing when loaded as a CSV.

```
COMP_L1_1_(P1)       — exclusive to product 1
COMP_L1_3_(P1,P2)    — shared between products 1 and 2
RAW_L0_2_(P2)        — only used in product 2's subtree
```

### Step 3 — Workstations and stage assignment

`n_ws` assembly workstations are created (`WS_1` … `WS_n`), plus fixed `Inv` (source) and `QI` (sink) stations.  The assembly workstations are partitioned into `depth` stages — one stage per BOM level — so each workstation only ever produces components at a single level.  The partition is either uniform (floor-based) or randomised via a Dirichlet distribution, controlled by `stage_balance`.

### Step 4 — Configurations

For each producible component, a random subset of the eligible stage workstations is selected and assigned a `Configuration` with independently sampled processing time, setup time, setup cost, and operating cost.  If any workstation ends up with no configurations (permanently idle), it is force-assigned to the most constrained component in its stage.

### Step 5 — Layout

A transport edge is created for every unique `(origin, destination)` pair implied by the BOM: if workstation A produces a component that workstation B consumes, an edge `A → B` is added.  Raw-material sources connect from `Inv`; finished products connect to `QI`.  Each edge gets an independently sampled capacity and cost.

### Step 6 — Validation

A final assertion checks that every producible component has at least one configuration.

---

## generate.py — Public API

Two public functions, both return the same dict:

```
{
  "components":     list[Component],
  "bom_edges":      list[BomEdge],
  "workstations":   list[Workstation],
  "configurations": list[Configuration],
  "layout_edges":   list[LayoutEdge],
  "producible":     list[str],   # component IDs that require production
  "out_dir":        str | None,  # CSV output directory, or None
}
```

| Function | Use case |
|---|---|
| `generate_simple_assembly(config_path)` | Reads parameters from `config.yaml`; resolves the processing-time range via the assembly-type formula or a legacy explicit range |
| `generate_from_params(params)` | Accepts a plain dict; intended for sweeps and validation tests |

Both delegate to `factory.build_factory()` after setting the RNG seed.  When `export_csv=True`, `write_csvs()` is called and the output path is stored in `result["out_dir"]`.

### Processing-time formula

When `assembly_type` is set in the config, processing time is derived from:

```
processing_time = α · depth^β  ±  variation
```

| assembly_type | α | β |
|---|---|---|
| low | 0.33 | 1.39 |
| medium | 0.28 | 1.45 |
| high | 0.12 | 1.79 |

This ensures that processing times scale realistically with BOM depth without requiring manual tuning per run.
