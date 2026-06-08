# Alpha Model - Synthetic Manufacturing Data Generator 

This model generates and simulates synthetic assembly factories driven by a single config file (`config.yaml`). Running **Generate** first produces the factory structure; running **Simulate** replays production orders through it using a Discrete-Time Simulation. In addition, the model contains functionality allowing the created synthetic manufacturing data to be analyzed.
## Running the UI

The primary interface is a Dash web app. **Python** must be installed first. Then install `uv`:

```bash
pip install uv
```

Then launch from the model root:

```bash
uv run python __main__.py
```

Or equivalently:

```bash
uv run python ui/app.py
```

Then open **http://127.0.0.1:8501** in your browser. The sidebar groups pages into **Engine** (Generate, Simulate) and **Analyse** (Sweep, Validate, Availability). The **Configure** page lets you edit `config.yaml` directly without leaving the browser. All sections below describe the underlying logic; see the UI for the interactive interface.

---

## Contents

- [Configuration Reference](#configuration-reference)
  - [metadata](#metadata)
  - [bom](#bom)
  - [workstations](#workstations)
  - [configurations](#configurations)
  - [layout](#layout)
  - [simulation](#simulation)
  - [failures](#failures)
  - [sweep](#sweep)
  - [output](#output)
- [Generate](#generate)
  - [Step 1 — BOM tree construction](#step-1--bom-tree-construction)
  - [Step 2 — Ownership renaming](#step-2--ownership-renaming)
  - [Step 3 — Stage assignment](#step-3--stage-assignment)
  - [Step 4 — Configuration sampling](#step-4--configuration-sampling)
  - [Step 5 — Forced assignment](#step-5--forced-assignment)
  - [Step 6 — Layout derivation](#step-6--layout-derivation)
  - [Output files](#output-files)
- [Simulate](#simulate)
  - [Implementation](#implementation)
  - [Machine failures](#machine-failures)
  - [What it does](#what-it-does)
  - [Output files](#output-files-1)
  - [Factory Physics metrics in utilization.csv](#factory-physics-metrics-in-utilizationcsv)
- [Sweep](#sweep)
  - [Performance notes](#performance-notes)
  - [Parameter groups](#parameter-groups)
  - [Alpha (α)](#alpha-α)
  - [Complexity (C)](#complexity-c)
  - [Output files](#output-files-2)
  - [Visualize](#visualize)
    - [Single simulation run](#single-simulation-run)
    - [Parameter sweep](#parameter-sweep)
- [Verify](#verify)
  - [How to run](#how-to-run)
  - [Check groups](#check-groups)
  - [Output files](#output-files-3)
  - [Visualize](#visualize-1)
- [Use Cases](#use-cases)
  - [Availability analysis](#availability-analysis)
- [Exporting Figures for Reports](#exporting-figures-for-reports)
- [Model Limitations](#model-limitations)
  - [Greedy, non-anticipating scheduler](#greedy-non-anticipating-scheduler)
  - [No stochasticity during simulation execution](#no-stochasticity-during-simulation-execution)
  - [Infinite raw material supply](#infinite-raw-material-supply)
  - [Machine failures — partially addressed](#machine-failures--partially-addressed)
  - [No labour or operator constraints](#no-labour-or-operator-constraints)
  - [Instantaneous material transport](#instantaneous-material-transport)
  - [Uniform buffer capacity](#uniform-buffer-capacity)
  - [Fixed, deterministic order interarrival](#fixed-deterministic-order-interarrival)
  - [No preemption](#no-preemption)
  - [Flow capacity not enforced](#flow-capacity-not-enforced)
  - [Availability analysis assumes no cascading starvation](#availability-analysis-assumes-no-cascading-starvation)
  - [No quality control or scrap](#no-quality-control-or-scrap)
  - [Parameter combinations can cause irrecoverable deadlock](#parameter-combinations-can-cause-irrecoverable-deadlock)

---

## Configuration Reference

All model behaviour is controlled by a single file: **`config.yaml`** in the model root directory. The file is divided into seven sections. Parameters marked *[min, max]* are sampled uniformly from the given range once per generation run.

---

### `metadata`

| Parameter | Type | Description |
|---|---|---|
| `name` | string | Human-readable label for this factory configuration. Used only in log output. |
| `seed` | int or `null` | Random seed passed to every stochastic step (BOM construction, workstation assignment, simulation, failure sampling). Set to `null` for a non-reproducible run. The same seed in `config.yaml` is forwarded to all sub-modules; it can also be overridden per API call. |

---

### `bom`

Controls the shape of the Bill of Materials tree. All intermediate components and raw materials are generated automatically from these five parameters.

| Parameter | Type | Description |
|---|---|---|
| `n_products` | int | Number of distinct finished products to generate. Each product is the root of its own BOM subtree; subtrees can share intermediate components when `sharing_ratio > 0`. |
| `depth` | int ≥ 2 | Number of BOM levels. `depth = 2` means raw material → product (one intermediate level); `depth = 5` means four intermediate levels between raw material and product. Also determines the number of stages workstations are divided into — must not exceed `workstations.count`. Level numbering follows ERP convention: level 0 = raw materials, level `depth` = finished products. |
| `branching` | [min, max] int | Number of distinct component types that each parent node directly requires. Sampled independently per parent node. A wider range produces more irregular, realistic trees. Example: `[2, 3]` means each assembly requires 2 or 3 direct input types. |
| `quantity` | [min, max] int | Number of units of each input required to produce one unit of the parent (BOM edge quantity). Sampled independently per BOM edge. Higher values increase the total production volume required to fulfil an order and therefore directly affect simulation duration and recommended `n_ticks`. |
| `sharing_ratio` | float 0–1 | Probability that, when a new child component is needed, an already-existing component at the same BOM level is reused instead of creating a new one. `0.0` = every component is unique (pure tree); `1.0` = reuse as aggressively as possible given traversal order. Reusing a component adds a second parent to it, turning the BOM tree into a DAG and creating components that are inputs to multiple assemblies. Has no effect if a level contains only one component. Each parent's direct inputs are always **distinct** — the same component cannot be selected twice for the same parent (which would reduce the effective branching factor and create invalid duplicate BOM edges). |

---

### `workstations`

| Parameter | Type | Description |
|---|---|---|
| `count` | int | Total number of assembly workstations. Inventory (`:Inv`) and Quality Inspection (`:QI`) nodes are always added automatically and are not counted here. Must be ≥ `bom.depth` (each stage must have at least one workstation). |
| `stage_balance` | float > 0 or `null` | Controls how evenly workstations are distributed across the `depth` stages (one stage per BOM level). `null` (default) gives a perfectly uniform, floor-based split. A positive value is the concentration parameter *c* of a symmetric Dirichlet distribution over stage sizes: higher values → more uniform; lower values → more skewed, with one or a few stages absorbing most of the capacity. Rule of thumb: `> 5` looks roughly uniform, `≈ 1` is a uniformly random partition, `< 0.5` creates pronounced bottleneck stages. |

The **alpha (α)** metric is derived from these two parameters and is used throughout the analysis:

```
α = bom.depth / workstations.count
```

`α = 1` means one workstation per stage on average (serial, specialised factory). `α → 0` means many workstations per stage (wide, parallel factory with redundant capacity at each level).

---

### `configurations`

A configuration links one workstation to one component it is capable of producing and specifies the time and cost parameters for that pairing. Each workstation can hold multiple configurations (capability for multiple components, switching between them via changeovers).

| Parameter | Type | Description |
|---|---|---|
| `producers_per_component` | [min, max] int | How many workstations in a stage are assigned the capability to produce each component. Sampled per component; automatically clamped to the number of workstations in that stage. A range of `[1, 1]` creates a single-machine bottleneck for every component; `[2, 3]` adds redundant capacity. |
| `processing_time` | [min, max] float (hours) | Processing time per unit for each workstation–component pair. Used only when `assembly_type` is **not** set. Each pair is sampled independently from this range. |
| `assembly_type` | `"low"`, `"medium"`, or `"high"` | When set, overrides `processing_time` with a formula that scales with product complexity C: `pt = a · C^b ± variation`. This ensures deeper, more complex assemblies take proportionally longer to produce. The (a, b) coefficients are: `low` = (0.33, 1.39), `medium` = (0.28, 1.45), `high` = (0.12, 1.79). Cannot be used together with an explicit `processing_time` range. |
| `variation` | float 0–1 | Fractional spread applied around the `assembly_type` formula value to preserve workstation heterogeneity. A value of `0.10` means each pair is sampled uniformly from `[pt_mean × 0.90, pt_mean × 1.10]`. Default: `0.10`. Has no effect when using the explicit `processing_time` range. |
| `setup_time` | [min, max] float (hours) | Changeover time charged once each time a workstation switches from producing one component to a different one. Sampled per workstation–component pair. A workstation reassigned to the same component it last produced does not incur setup time. |
| `setup_cost` | [min, max] float | Cost charged per changeover event. Sampled per pair. Contributes to the `SetupCost` column of `costs.csv`. |
| `operating_cost` | [min, max] float | Cost charged per unit produced. Sampled per workstation–component pair. Contributes to the `OperatingCost` column of `costs.csv`. |

---

### `layout`

The layout graph (which workstations are physically connected) is derived automatically from the BOM and stage assignments — no manual edge definitions are needed. These two parameters control the properties assigned to each derived edge.

| Parameter | Type | Description |
|---|---|---|
| `flow_capacity` | [min, max] int | Maximum throughput of each material flow edge (units per unit time). Sampled per edge. Not enforced as a hard constraint in the current simulator; stored in `layout.csv` for reference and potential use in future analyses. |
| `transport_cost` | [min, max] float | Cost per unit transported along each material flow edge. Sampled per edge. The simulator attributes transport cost to the receiving workstation by averaging all incoming edge costs. Contributes to the `TransportCost` column of `costs.csv`. |

---

### `simulation`

Discrete-Time Simulation (DTS) parameters. Time advances in fixed steps called *ticks*; all workstations are evaluated simultaneously every tick.

| Parameter | Type | Description |
|---|---|---|
| `tick_duration` | float (hours) | Duration of one simulated tick in hours. Smaller values give finer time resolution and more accurate timing of job completions, but increase the number of ticks needed to cover the same simulation horizon. Default: `0.05` h (≈ 3 minutes). All processing and setup times are converted to tick counts by ceiling-dividing by this value. |
| `buffer_capacity` | int | Maximum number of units any single non-raw intermediate component buffer may hold. When a workstation finishes a unit but the buffer is at capacity, it enters the **blocked** state and retries every tick until space opens. Raw material buffers are infinite. A larger value reduces blocking at the cost of higher in-process inventory; a value that is too small relative to BOM explosion quantities can cause deadlock (all producers blocked, all consumers starved). |
| `order_interarrival` | int (ticks) | Number of ticks between successive order releases. One order is released every `order_interarrival` ticks until `n_orders` have been released. Larger values space orders out and allow the factory to drain partially before new demand arrives, reducing congestion. `order_interarrival × tick_duration` gives the inter-arrival time in simulated hours. |
| `n_ticks` | int | Hard upper limit on simulation length in ticks. The simulation ends early if all orders are fulfilled before `n_ticks` is reached. Total simulated horizon = `n_ticks × tick_duration` hours. For factories with a deep BOM (high `depth`) and large explosion quantities, this value may need to be set very high (100 000 +) for all orders to complete. A rough lower bound is `n_orders × (branching_max^depth × processing_time_max) / tick_duration`. |
| `n_orders` | int | Total number of production orders to release. Orders cycle evenly through all `n_products` products. Increasing this value extends the simulation and provides more throughput and utilisation data. |

---

### `failures`

Controls stochastic machine failures. When `enabled: false`, all parameters in this section are ignored and the simulation runs as if machines never break down.

| Parameter | Type | Description |
|---|---|---|
| `enabled` | bool | Master switch. `true` activates the Weibull failure model; `false` disables all failures entirely. |
| `weibull_beta` | [min, max] float | Weibull shape parameter β, sampled once per workstation from this range. Determines the failure-rate trend over machine lifetime: `β < 1` = infant mortality (failure rate decreases over time), `β = 1` = constant failure rate (exponential distribution, memoryless), `β > 1` = wear-out behaviour (failure rate increases with age — the most realistic for mechanical equipment). |
| `weibull_lambda` | [min, max] float (hours) | Weibull scale parameter λ (characteristic life in simulated hours), sampled once per workstation. Larger values mean the machine lives longer before its first failure on average. The mean time between failures (MTBF) in hours is `λ · Γ(1 + 1/β)`. |
| `mttr` | [min, max] float (hours) | Repair duration per failure event (Mean Time To Repair). A fresh value is sampled uniformly from this range each time a failure occurs. Repair counts down tick by tick; the machine returns to idle when the counter reaches zero, with age reset to 0 and a new TTF drawn. |
| `repair_cost` | [min, max] float | Cost charged per failure event. A fresh value is sampled uniformly from this range each time a failure occurs, independently of repair duration. Accumulated in the `RepairCost` column of `costs.csv`. |

**Note on age accumulation:** machine age advances only during `setup` and `processing` states. A workstation that is idle, starved, or blocked does not age. This means MTBF is measured in *active working hours*, not calendar time.

---

### `sweep`

Defines the parameter grid for the Sweep analysis. Every combination of all expanded parameter lists is run as a separate Generate + Simulate pair. Simulation settings (`n_orders`, `tick_duration`, etc.) are taken from `simulation:` and held constant across all runs; only the structural parameters listed here are varied.

**Value formats** — three formats are supported for each parameter:

| Format | Example | Expands to |
|---|---|---|
| Scalar (fixed) | `n_products: 4` | `[4]` |
| List (explicit) | `depth: [2, 3, 5]` | `[2, 3, 5]` |
| Range | `depth: {min: 1, max: 8, step: 1}` | `[1, 2, 3, 4, 5, 6, 7, 8]` |

**Sweepable parameters:**

| Key | Maps to |
|---|---|
| `n_products` | `bom.n_products` |
| `depth` | `bom.depth` |
| `workstations_count` | `workstations.count` |
| `sharing_ratio` | `bom.sharing_ratio` |

The total number of runs equals the product of all expanded list lengths, minus any combinations where `depth > workstations_count` (which are always skipped). Runs are executed sequentially; results are collected into aggregated CSVs (see the **Sweep** section below).

---

### `output`

| Parameter | Type | Description |
|---|---|---|
| `directory` | string | Directory for Generate output files (`components.csv`, `bom.csv`, etc.). Relative paths are resolved relative to the model root; absolute paths are used as-is. Default: `"gen_output"`. |

---

## Generate

The generator builds a complete factory description from `config.yaml` and writes five CSV files to `engine/generate/gen_output/`. Run it from the **Generate** page in the UI, or call it directly:

```python
from engine.generate.generate import generate_simple_assembly
result = generate_simple_assembly("config.yaml", export_csv=True)
```

Generation proceeds in six sequential steps:

1. **BOM tree construction** — build the component hierarchy top-down from each product down to raw materials
2. **Ownership renaming** — append a product-ownership suffix to every non-product component ID
3. **Stage assignment** — divide workstations into `depth` groups, one group per BOM level
4. **Configuration sampling** — randomly assign workstations to components within each stage
5. **Forced assignment** — ensure no workstation is left permanently idle
6. **Layout derivation** — place directed edges between workstations based on actual BOM dependencies

---

### Step 1 — BOM tree construction

A **Bill of Materials (BOM)** defines what each product is made of, all the way down to raw materials. The generator builds the BOM **top-down and recursively**, starting from each finished product.

For every node, it samples a random number of children within the `branching` range and creates each child at `level − 1`. This recurses until `level 0` (raw materials) is reached. Level numbers run bottom-up: `level 0` = raw materials, `level depth` = finished products. Higher numbers mean closer to the finished product, following ERP conventions.

```
depth = 2, branching = 2, n_products = 2

Level 2:   PROD_1                        PROD_2
            ├── COMP_L1_1_(P1)            ├── COMP_L1_3_(P2)
            │     ├── RAW_L0_1_(P1)       │     ├── RAW_L0_4_(P2)
            │     └── RAW_L0_2_(P1)       │     └── RAW_L0_5_(P2)
            └── COMP_L1_2_(P1)            └── COMP_L1_4_(P2)
                  └── RAW_L0_3_(P1)             └── RAW_L0_6_(P2)
```

*(The `_(P…)` suffixes are added in Step 2 — shown here for consistency with actual output.)*

The `bom.csv` file records each `(child → parent, quantity)` edge, meaning "you need `quantity` units of this child to produce one unit of this parent."

**Component sharing**

By default (`sharing_ratio = 0`) every node gets its own private subtree. When `sharing_ratio > 0`, each time the generator needs a new child it has a `sharing_ratio` chance of reusing an already-existing component at that level instead of creating a new one. Reusing a component adds a second incoming BOM edge to it, turning the pure tree into a DAG.

```
sharing_ratio = 0 (no sharing):          sharing_ratio > 0 (with sharing):

Level 2   PROD_1        PROD_2           Level 2   PROD_1          PROD_2
           /   \          /   \                      /   \            /   \
Level 1   C1   C2        C3   C4         Level 1   C1    C2         C1    C3
                                                          ^_________^
                                                    C1 = COMP_L1_1_(P1,P2)
```

The very first child created at any level is always new (the pool is empty at that point), so `sharing_ratio = 1.0` does not collapse a level to a single component — it reuses as aggressively as possible given the traversal order.

Note that sharing always connects components across **different parents** — the same component can never appear twice as a direct input to the *same* parent. This keeps the effective branching factor equal to the configured range and avoids degenerate BOM edges.

---

### Step 2 — Ownership renaming

After the full BOM is built, every non-product component and every raw material is renamed with a **product-ownership suffix** listing which finished products it transitively feeds.

The generator walks downward from each product through the BOM to find all reachable nodes. A component that only feeds `PROD_1` gets `_(P1)`; one that feeds both `PROD_1` and `PROD_2` gets `_(P1,P2)`. Finished products (`PROD_*`) keep their original IDs — no suffix.

**Component ID format:** `<TYPE>_L<level>_<counter>_(P…)`

| Example ID | Meaning |
|---|---|
| `RAW_L0_3_(P2)` | 3rd raw material; feeds only product 2 |
| `COMP_L1_1_(P1,P2)` | 1st level-1 intermediate; shared between products 1 and 2 |
| `COMP_L3_2_(P1)` | 2nd level-3 intermediate; exclusive to product 1 |
| `PROD_2` | 2nd finished product; no suffix |

The rename is applied to the component list, all BOM edges, and the producible component list before any workstation assignment takes place.

---

### Step 3 — Stage assignment

Workstations are divided into `depth` groups called **stages**, one stage per BOM level. A workstation in stage *l* can only be assigned components at BOM level *l*.

How many workstations end up in each stage is controlled by the `stage_balance` parameter (see below). The result is logged to stdout on every run so the split is always visible:

```
[generate] stage assignment (stage 1:2, stage 2:5, stage 3:3, stage 4:2, stage 5:2)
```

The **alpha (α) parameter** summarises the average serial/parallel topology:

```
α = depth / workstations_count
```

- **α = 1** — one workstation per stage on average; serial, specialised factory
- **α → 0** — many workstations per stage on average; wide, parallel factory with redundant capacity at each level

Note that α captures the *average* stage size. With `stage_balance` set to a low value, individual stages can deviate significantly from this average; two factories with the same α can have very different bottleneck patterns.

> **Constraint:** `depth` must not exceed `workstations_count`. Each stage must receive at least one workstation, so `depth > workstations_count` is invalid.

**Stage balance**

By default (`stage_balance: null`) workstations are distributed using simple floor-based arithmetic, giving a near-perfectly-uniform split. Setting `stage_balance` to a positive number switches to a **Dirichlet-based random partition**, which is more realistic: real factories rarely have exactly equal capacity at every stage.

The `stage_balance` value is the concentration parameter *c* of a symmetric Dirichlet distribution over the `depth` stage sizes. The generator samples *k* = `depth` independent Gamma(*c*, 1) variates, normalises them to sum to `workstations_count`, and rounds using the largest-remainder method. Each stage is guaranteed at least one workstation.

| `stage_balance` | Effect |
|---|---|
| `null` | Perfectly uniform floor-based split (original behaviour) |
| `10.0` | Near-uniform; stages differ by at most 1–2 workstations |
| `1.0` | Flat Dirichlet — uniformly random over all valid partitions |
| `0.5` | Skewed — a few stages absorb most workstations |

```
Same factory, n_ws = 10, depth = 5, three different draws at stage_balance = 1.0:

  Draw 1:  stage 1:1  stage 2:4  stage 3:2  stage 4:2  stage 5:1   (bottleneck at 1 and 5)
  Draw 2:  stage 1:3  stage 2:1  stage 3:3  stage 4:2  stage 5:1   (bottleneck at 2 and 5)
  Draw 3:  stage 1:2  stage 2:2  stage 3:2  stage 4:2  stage 5:2   (happens to be uniform)
```

A high value like `10.0` is appropriate when you want α to remain the dominant variable (e.g. during a parameter sweep). A value around `1.0` is appropriate for single-run realism. Values below `0.5` produce extreme skew that is only realistic for very specialised factories.

**Stage assignment parameters**

| Parameter | Description |
|---|---|
| `workstations.count` | Total number of assembly workstations |
| `workstations.stage_balance` | Dirichlet concentration for stage sizing (`null` = uniform; higher = more uniform; lower = more skewed). Must be `> 0` if set. |

---

### Step 4 — Configuration sampling

A **configuration** links one workstation to one component and specifies the time and cost of producing that component on that machine. A single workstation can hold multiple configurations, meaning it is capable of producing several different components (with a changeover in between).

For each producible component, the generator randomly selects between the minimum and maximum of `producers_per_component` workstations from that component's stage. Each selected `(workstation, component)` pair gets independently sampled timing and cost values.

**Configuration parameters**

| Parameter | Description |
|---|---|
| `producers_per_component` | `[min, max]` — how many workstations can produce each component; clamped to the stage size |
| `assembly_type` | `"low"`, `"medium"`, or `"high"` — sets the (a, b) coefficients for the processing-time formula (see below). Cannot be used together with `processing_time`. |
| `variation` | Fractional spread around the formula value, e.g. `0.10` for ±10 %. Each (workstation, component) pair is sampled independently within this band. Default: `0.10`. |
| `processing_time` | `[min, max]` hours — explicit range, used when `assembly_type` is not set. |
| `setup_time` | `[min, max]` hours — changeover time when switching to this component; sampled per pair |
| `setup_cost` | `[min, max]` — cost charged once per changeover; sampled per pair |
| `operating_cost` | `[min, max]` — cost per unit produced; sampled per pair |

**Processing-time formula**

When `assembly_type` is set, processing time scales with the product complexity C using an exponential approximation. C grows monotonically with BOM depth for a fixed branching factor, and BOM depth is used as a proxy for C in the implementation:

```
processing_time = a · C^b   ±  variation
```

Products with higher C — more distinct intermediate component types to coordinate — automatically produce components that take longer to assemble. The (a, b) coefficients by assembly type are:

| `assembly_type` | a | b |
|---|---|---|
| `low` | 0.33 | 1.39 |
| `medium` | 0.28 | 1.45 |
| `high` | 0.12 | 1.79 |

For example, with `assembly_type: medium`, `depth: 5` (C ≈ depth for unit branching), and `variation: 0.10`:

```
pt_mean = 0.28 × 5^1.45 ≈ 2.89 h
pt_range = [2.89 × 0.90,  2.89 × 1.10] = [2.60 h,  3.18 h]
```

Each configuration is then sampled uniformly from this range, preserving workstation heterogeneity.

---

### Step 5 — Forced assignment

Random sampling in Step 4 does not guarantee every workstation receives at least one configuration. A workstation with zero configurations is permanently idle: it occupies a stage slot, draws layout edges, but never produces anything — distorting both α and simulation utilisation figures.

After the main sampling pass, the generator scans each stage for unassigned workstations. Each idle workstation is assigned the component in its stage that currently has the **fewest producers** (fewest-producers heuristic). This adds redundancy at the most constrained point, which is what a real production planner would do. A warning is printed to stdout each time this occurs:

```
[generate] forced assignment: WS_6 -> COMP_L3_2_(P1,P2) (was idle at stage 3)
```

---

### Step 6 — Layout derivation

Layout edges define which workstations are physically connected — i.e. which machines ship material to which other machines. They are derived entirely from the BOM and the configurations from Steps 4–5, so every edge represents material that actually needs to move. No edges are placed between workstations that do not exchange a real component.

**How edges are placed:**

For each BOM edge `(comp_in → comp_out)`, the generator connects every workstation that produces `comp_in` to every workstation that produces `comp_out`. Two endpoint rules complete the graph:

- **Inv → WS:** raw materials originate from Inv, so any workstation that consumes a raw material receives an incoming edge from Inv.
- **WS → QI:** any workstation that produces a finished product gets an outgoing edge to QI.

If multiple BOM paths result in the same physical `(origin, destination)` pair — e.g. WS_3 supplies two different components to WS_7 — these are deduplicated into a single edge with one capacity and one cost.

```
Example: WS_1 produces COMP_L1_1_(P1), WS_3 assembles PROD_1

  BOM path:  RAW_L0_1_(P1)  ->  COMP_L1_1_(P1)  ->  PROD_1

  Edges created:
    Inv  -> WS_1    raw material flows from inventory to WS_1
    WS_1 -> WS_3    COMP_L1_1 flows from WS_1 to the assembly station
    WS_3 -> QI      PROD_1 leaves the factory to Quality Inspection

  WS_1 -> WS_4 is NOT created unless WS_4 also consumes
  a component that WS_1 produces.
```

**Layout parameters**

| Parameter | Description |
|---|---|
| `flow_capacity` | `[min, max]` — maximum units that can flow along an edge; sampled per edge |
| `transport_cost` | `[min, max]` — cost per unit transported along an edge; sampled per edge |

---

### Output files

| File | Contents |
|---|---|
| `components.csv` | All components: ID, name, BOM level, and whether it is a finished product |
| `bom.csv` | BOM edges: `Input` component, `Output` component, and `Quantity` required |
| `workstations.csv` | All workstations (Inv, WS_*, QI) with their type: source / production / sink |
| `configurations.csv` | Each (workstation, component) capability pair with processing time, setup time, setup cost, and operating cost |
| `layout.csv` | Material flow edges: origin workstation, destination workstation, capacity, and transport cost |

In addition to the CSV files, `generate_from_params()` returns a `"complexity"` key in its result dict containing a per-product complexity mapping `{product_id: C}`. This is available for programmatic use without re-reading any CSV. During a parameter sweep it is automatically aggregated into `gen_stats.csv` (see [Complexity (C)](#complexity-c) below).

---

## Simulate

> This model supports optional **machine failures**. Enable them in the `failures:` section of `config.yaml`.

Run the simulation from the **Simulate** page in the UI (requires a prior Generate run), or call it directly:


The simulator reads the five CSVs produced by Generate and replays a series of production orders through the factory. It uses a **Discrete-Time Simulation (DTS)** approach: time advances in fixed steps called *ticks*, and every workstation is evaluated simultaneously at each tick. This allows multiple workstations to produce different components at the same time (concurrency), and captures two failure modes that a purely sequential scheduler cannot see:

- **Blocking** — a workstation has finished a job but the output buffer is full; it holds the units and waits until space opens up downstream.
- **Starvation** — a workstation is ready to start a job but the input components it needs have not yet arrived in the buffer; it waits until upstream production catches up.

All simulation parameters (`tick_duration`, `buffer_capacity`, `order_interarrival`, `n_ticks`, `n_orders`) are set in the `simulation:` section of `config.yaml`. Results are written to `simulate/sim_output/`.

### Implementation

This model replaces the initial model's pure-Python simulation with a **NumPy + Numba** implementation that compiles the tick loop to machine code. The public `simulate()` function has an identical signature and return value — `run.py`, `sweep.py`, and all visualisations are unchanged.

The simulation runs in three phases:

**Phase 1 — Pre-processing (Python)**

All factory objects (workstations, configurations, BOM edges, layout) are converted from Python dataclasses and string-keyed dictionaries into flat NumPy arrays before the tick loop starts. Every string ID (component, workstation) is replaced by an integer index so the compiled loop can use fast array indexing instead of dictionary lookups.

The key data structures are:

| Structure | Type | Description |
|---|---|---|
| `ws_state[n_ws]` | `int8` | Current state of each workstation (0=idle … 4=starved) |
| `ws_ticks_left[n_ws]` | `int32` | Remaining ticks on the active job |
| `ws_current_comp[n_ws]` | `int32` | Index of the last component produced (−1 = none) |
| `capable[n_ws, n_comps]` | `bool` | Whether workstation *i* can produce component *j* |
| `proc_time_m[n_ws, n_comps]` | `float64` | Processing time (hours per unit) per workstation–component pair |
| `setup_time_m[n_ws, n_comps]` | `float64` | Changeover time (hours) per workstation–component pair |
| `stock[n_comps]` | `int32` | Current buffer stock for each component |

The BOM is stored in **CSR (Compressed Sparse Row)** format — the same format used in sparse matrix libraries — so that looking up the inputs of any component is a simple integer range lookup rather than a dictionary access:

```
bom_ptr[ci] : bom_ptr[ci+1]  →  range of indices into bom_inputs / bom_qtys
```

BOM explosions for each product are also pre-computed in Python before the loop starts, so that releasing an order inside the Numba loop only requires copying a fixed slice of pre-computed arrays rather than performing recursive BOM traversal.

**Phase 2 — Tick loop (Numba `@njit`)**

The core tick loop is extracted into a standalone function decorated with `@numba.njit(cache=True)`. Numba compiles this function to native machine code via LLVM on the first call (approximately 1–2 seconds), then caches the compiled binary to disk. Every subsequent call — including all runs in a parameter sweep — uses the cached binary with no recompilation cost.

Inside the compiled function there are no Python objects, no dictionaries, no strings, and no Pandas. Every operation is integer or floating-point arithmetic on NumPy arrays. The sequential parts of the loop (demand assignment, starvation detection) remain loops, but each iteration is executed at near-C speed rather than interpreted Python speed.

All output is written into pre-allocated arrays (`state_log`, `tp_log`, `buf_log`) rather than appended to Python lists. This avoids memory allocation overhead inside the hot loop.

**Phase 3 — Post-processing (Python + Pandas)**

After the tick loop returns, the raw output arrays are converted back to the same five Pandas DataFrames that the initial model produces. This step runs in Python and is not compiled, but it executes only once per simulation run and scales with `actual_ticks × n_workstations`.

### Machine failures

Machine failures are controlled by the `failures:` section of `config.yaml`:

| Parameter | Description |
|---|---|
| `enabled` | `true` to activate failures; `false` to run identically to the optimized model |
| `weibull_beta` | `[min, max]` Weibull shape parameter β. Each workstation is assigned a value sampled uniformly from this range. β > 1 gives wear-out behaviour (the older the machine, the more likely it is to fail). β = 1 reduces to an exponential distribution (constant failure rate). |
| `weibull_lambda` | `[min, max]` Weibull scale parameter λ in simulated hours. Controls the characteristic life of each machine — a larger λ means the machine lives longer before its first failure. |
| `mttr` | `[min, max]` repair duration in hours (Mean Time To Repair). A new value is sampled uniformly from this range every time a failure occurs. |
| `repair_cost` | `[min, max]` cost charged per failure event (sampled per event). Accumulated in the `RepairCost` column of `costs.csv`. |

**How failures work — the Weibull model:**

At the start of the simulation, every workstation is assigned its own β and λ from the configured ranges. A first **time-to-failure (TTF)** is then drawn by sampling from the Weibull distribution:

```
TTF ~ Weibull(β, λ)     [in simulated hours, then converted to ticks]
```

Each tick, every non-failed, non-blocked workstation **ages by one tick**. When its accumulated age reaches the sampled TTF the machine fails. Blocked workstations are excluded: their job is already complete and they only need buffer space, so mechanical age should not advance during that wait.

After repair the age resets to zero and a **new TTF** is drawn from the same Weibull(β, λ), giving each machine an independent, randomly varying lifetime for every cycle.

**Job interruption:** if the workstation was in the middle of a setup or processing job when it failed, the BOM inputs that had been consumed from stock are returned, and the demand item is re-queued as unassigned. Once the machine is repaired it will pick up new work via the normal assignment step.

**Repair:** the repair counter counts down by one each tick. When it reaches zero the workstation returns to the **idle** state. The machine remembers the last component it was producing (`ws_current_comp`), so if the first new job after repair is for the same component, no setup is required.

**Output:** the `utilization.csv` file gains two new columns (`Failed` for hours spent failed, `FailedPct` for the percentage of simulation time). The `costs.csv` file gains a `RepairCost` column. The `states.csv` file records the new state value `"failed"`.

### What it does

**Order release**

Orders are not all released at the start. Instead, one order is released every `order_interarrival` ticks. This spreads demand out over time and allows the factory to process earlier orders while new ones are still arriving.

Each order is for exactly one unit of a product. The simulator cycles evenly through all available products: with 2 products and 6 orders, each gets 3 orders; with 2 products and 5 orders, the first gets 3 and the second gets 2.

**BOM explosion**

When an order is released, the simulator performs a BOM explosion to determine the total number of units of every component required — not just the direct inputs of the product, but the inputs of those inputs, all the way down to raw materials.

It works top-down, level by level. Starting with one unit of the finished product, the simulator looks up what that product directly requires and in what quantities. It then moves down one level and repeats for each of those components, multiplying quantities as it goes. This continues until raw materials are reached.

The reason it must go level by level rather than expanding each branch independently is **shared components**. If the same intermediate component appears under two different parents, its required quantity must be accumulated from both parents before its own inputs are expanded; otherwise the raw material quantities would be undercounted.

The result is a flat list of every non-raw component required for this order and exactly how many units of each are needed. Each entry becomes a *demand item* in the simulation queue.

**Tick loop**

Each tick, the simulator steps through the following actions in order:

1. **Release** — if enough ticks have passed since the last order, release a new one and add its demand items to the queue.
2. **Advance jobs** — every workstation that is in setup or processing has its remaining tick counter decremented by one. If a job finishes, its output is ready to be deposited.
3. **Deposit output** — the finished units are moved into the component's buffer. If the buffer is full (stock has reached `buffer_capacity`), the workstation enters the **blocked** state and retries on the next tick.
4. **Assign work** — idle workstations are matched to pending demand items, processed from the lowest BOM level upward so that sub-components are always produced before the assemblies that need them. A demand item can only be assigned once all of its non-raw input components are already in the buffer (raw materials use the **infinite supply assumption** — they are always available at no production cost). The workstation that would finish earliest is selected; if it is not yet configured for this component, a **setup** phase is added first.
5. **Classify idle workstations** — any workstation that has pending demand it could handle but cannot start because upstream components are not yet ready is marked as **starved**.
6. **Log** — each workstation's current state is recorded for this tick, along with the current stock level of every non-raw component buffer.

The simulation runs until all orders are complete or the tick limit (`n_ticks`) is reached.

**Changeovers**

Every workstation remembers the last component it produced (`current_comp`). When a workstation is assigned a new demand item, the simulator checks whether that component matches what the machine was last set up for:

- **Same component as before** — no changeover needed; the workstation moves straight into the `processing` state.
- **Different component (or first job ever)** — the workstation must first go through a `setup` phase. It stays in `setup` for as many ticks as the `setup_time` configuration for that workstation–component pair requires, then transitions into `processing` automatically.

The setup time and setup cost are both defined per workstation–component pair in `configurations.csv`, so different machines can have different changeover costs for the same part.

This also influences which workstation gets picked for a demand item. When multiple workstations are capable of producing a component, the one with the **shortest estimated completion time** wins. That estimate already accounts for whether a setup would be needed, so a machine that is already configured for the right component has a built-in advantage over one that would need a changeover first.

A typical sequence on one workstation might look like this:

```
Tick  0  → assigned COMP_L1_1  (was idle, current_comp = "")   → setup starts
Tick  5  → setup done                                           → processing starts
Tick 12  → processing done, output deposited                    → idle
Tick 13  → assigned COMP_L1_1  (same component!)               → no setup, processing starts immediately
Tick 19  → processing done, output deposited                    → idle
Tick 20  → assigned COMP_L1_3  (different component)           → setup starts again
...
```

**Cost tracking**

Three types of cost are accumulated throughout the simulation:

- **Setup cost** — charged once each time a workstation switches from producing one component to another.
- **Operating cost** — charged per unit produced at a workstation.
- **Transport cost** — charged per unit moved into a workstation, calculated as the average cost of all incoming layout edges for that workstation. Stage-1 workstations are fed directly from Inv; higher-stage workstations are fed from the previous stage's workstations.

These are tracked per workstation and summed over all orders.

**Utilisation**

Each workstation spends every tick in exactly one of six states. At the end of the simulation the total time and percentage spent in each state is computed per workstation:

- **Processing** — actively producing units.
- **Setup** — performing a changeover before switching to a new component type.
- **Blocked** — processing is done but the output buffer is full; waiting for space to open.
- **Starved** — has pending demand but the required input components are not yet in the buffer.
- **Idle** — no pending demand; nothing to do.
- **Failed** — the machine has broken down and is under repair.

### Output files

| File | Contents |
|---|---|
| `states.csv` | Per-tick record of every workstation's state (`idle`, `setup`, `processing`, `blocked`, `starved`, or `failed`) |
| `utilization.csv` | Time (hours) and percentage spent in each of the six states per workstation, plus Factory Physics availability metrics (see below) |
| `throughput.csv` | Completion time, cumulative order count, and lead time for each finished order |
| `costs.csv` | Setup, operating, transport, and repair costs aggregated per workstation (includes `RepairCost`) |
| `buffers.csv` | Stock level of every non-raw component buffer at every tick |

---

### Factory Physics metrics in `utilization.csv`

> **Primary source:** Hopp, W. J., & Spearman, M. L. (2008). *Factory Physics* (3rd ed.).
> Waveland Press. Chapters 7–8.
>
> The MTBF formula is from standard Weibull distribution theory, not from Hopp & Spearman
> directly (see note below).

The `utilization.csv` file (and the in-memory `utilization` DataFrame) includes four additional columns derived analytically from each workstation's sampled Weibull failure parameters. These give theoretical predictions that can be compared against the empirical simulation results.

**`MTBF_h`** — Mean time between failures (hours)

For a Weibull failure distribution with shape **β** and scale **λ** (hours), the theoretical mean time between failures is:

```
MTBF = λ · Γ(1 + 1/β)
```

where Γ is the gamma function. `None` when failures are disabled.

> ⚠ **Citation note:** This formula is the expectation of the Weibull distribution —
> standard probability theory. Hopp & Spearman (Ch. 8) use a generic symbol *m₀* for mean
> time between failures without specifying the failure distribution or this formula. The choice
> of Weibull parameterisation is a design decision of this model, not a prescription from the book.

**`Availability`** — Long-run uptime fraction

Following Hopp & Spearman (Ch. 8), where *m₀* = mean time between failures and *mᵣ* = mean repair time:

```
A = m₀ / (m₀ + mᵣ)   →   A = MTBF / (MTBF + MTTR_mean)
```

A value of 0.80 means the machine is operational 80 % of the time. Always 1.0 when failures are disabled.

> **Model adaptation:** The config specifies a repair-time range `[mttr_min, mttr_max]`; this
> model uses `MTTR_mean = (mttr_min + mttr_max) / 2` as *mᵣ*. The book uses a generic
> *mᵣ* without specifying a repair-time distribution.

**`t_e_h`** — Effective process time (hours per unit) — *Hopp & Spearman, Equation 8.2*

Failures inflate the natural (failure-free) processing time **t₀** to an effective process time:

```
t_e = t₀ / A                   [Hopp & Spearman, Eq. 8.2]
```

A machine with A = 0.80 takes 25 % longer per unit than a failure-free machine. `t₀` is the mean processing time averaged over all components the workstation can produce. When failures are disabled, `t_e_h = t₀`.

**`IsPredictedBottleneck`** — Theoretical bottleneck flag

Hopp & Spearman (Ch. 7) define the bottleneck as the workstation with the highest utilization `u = r / r_e`, where `r` is the demand rate (orders per hour), `m` is the number of machines at that workstation, and `r_e = m / t_e` is the effective capacity (units per hour). For a fixed demand rate *r*, the station with the highest `t_e` has the lowest `r_e` and therefore the highest utilization, making it the bottleneck.

In a multi-product BOM factory the demand rate differs per workstation, so this is an approximation; it correctly identifies the machine most penalised by failures and long processing times.

---

## Sweep

The sweep runs Generate and Simulate for every combination of parameters defined in `config.yaml → sweep:` and collects all outputs into aggregated CSVs. Run it from the **Sweep** page in the UI, or call it directly:

```python
from analysis.sweep.sweep import main as run_sweep
run_sweep()                  # run every valid combination
run_sweep(max_runs=50)       # randomly sample 50 combinations
```

**Limiting the number of runs**

Large sweep grids can produce hundreds or thousands of combinations. The **Limit to N runs** field in the UI (and the `max_runs` parameter in `main()`) lets you pick exactly *N* combinations at random from the full valid grid instead of running all of them. When `N ≥ total_valid_combinations`, all combinations are run and the setting has no effect.

The random sample is reproducible: if `metadata.seed` is set in `config.yaml`, the same seed is used for sampling, so the same *N* runs are selected every time the sweep is triggered with that configuration. When `metadata.seed` is `null`, a fresh random sample is drawn each time.

The UI field accepts any integer between 1 and the total combination count. Leave it blank to run all combinations.

### Performance notes

Large sweeps can produce very large output files and long runtimes. The UI shows a warning banner for each condition that applies. The table below lists every condition that is checked, the threshold that triggers it, and why it matters.

| Condition | Threshold | Why it matters |
|---|---|---|
| **BOM depth** | any swept `depth` value > 4 | Component count grows as `branching_max ^ depth`. Each additional level multiplies components, workstation assignments, BOM-explosion work per order, and the number of ticks needed for the factory to drain — per-run time can increase by an order of magnitude between depth 4 and depth 6. |
| **Tick count** | `n_ticks` > 10 000 | `state_summary.csv` stores one row per **(run, tick)**, so its total row count equals `n_valid_runs × n_ticks`. At 80 runs × 56 000 ticks this is 4.5 million rows (≈ 270 MB). The visualiser reads this file with a chunked loader to avoid running out of memory, but loading time still scales with the total row count. |
| **Order count** | `n_orders` > 100 | Per-run simulation time scales linearly with `n_orders` because each order triggers a full BOM explosion and is tracked through the factory until completion. Total orders processed across the sweep equals `n_valid_runs × n_orders`. |
| **Branching × depth** | `bom.branching` max > 3 **and** max swept depth > 3 | Component count ≈ `branching_max ^ depth`. A branching factor of 4 at depth 5 already creates ~1 000 components; at depth 7 that is ~16 000. Each component needs workstation assignments, buffer slots, and BOM edge tracking — all of which scale the per-run cost super-linearly. |
| **Large state_summary** | `n_valid_runs × n_ticks` ≥ 1 000 000 | Fires when a wide grid (many runs) drives the state_summary row count past one million even at a moderate tick count (e.g. 500 runs × 5 000 ticks = 2.5 M rows). Separate from the n_ticks warning above. |

**Estimated state_summary size formula:**

```
rows  ≈  n_valid_runs  ×  n_ticks
size  ≈  rows  ×  ~60 bytes/row
```

For example: 200 runs × 20 000 ticks = 4 000 000 rows ≈ 240 MB.

**Recommendations for large sweeps:**

- Use the **Limit to N runs** field to randomly sample a smaller subset of the grid before committing to the full sweep.
- Set `n_ticks` to the minimum needed: many factory configurations complete all orders well before the tick limit. Check the single-run Simulate page to find a reasonable upper bound before sweeping.
- Keep `bom.depth` ≤ 4 in the sweep grid unless you are specifically studying the effect of deep BOMs; the exponential growth in component count means each depth increment is much more expensive than the last.
- A `metadata.seed` in `config.yaml` makes sub-sampled sweeps reproducible — the same random combination selection is used every time the same seed and limit are applied.

---

### Parameter groups

The sweep grid is defined entirely in `config.yaml → sweep:`. Each parameter can be a scalar, a list, or a `{min, max, step}` range — every combination is tested. Simulation settings (`n_orders`, `tick_duration`, etc.) are taken from `config.yaml → simulation:` and held constant across all runs.

### Alpha (α)

For each run, the alpha parameter is computed as:

```
α = depth / workstations_count
```

Alpha is a derived topology metric that summarises the serial/parallel structure of the factory (see the Layout section under Generate). It is prepended to every output row so that results can be grouped and plotted against it directly.

### Complexity (C)

For each product, complexity is computed at generation time as:

```
C(product) = number of distinct non-raw component types transitively required
             to produce one unit of the product
```

Concretely: starting from the product node, the generator performs a BFS downward through the BOM DAG and counts all reachable components with `level > 0`, excluding the product itself. Raw materials (`level = 0`) are excluded because they have infinite supply and contribute no scheduling complexity.

Two aggregate values are written to `gen_stats.csv` per sweep run:

| Column | Description |
|---|---|
| `mean_complexity` | Mean C across all products in the run |
| `max_complexity` | Maximum C across all products in the run |

With `sharing_ratio = 0`, all products have identical BOM subtrees and both values are equal. With `sharing_ratio > 0`, products that inherit more shared intermediate components have a smaller individual C — mean and max diverge, and the gap reflects how asymmetric the sharing turned out to be for that run.

Unlike α, which captures the ratio of BOM depth to workstation capacity, C captures the absolute number of component types a product depends on. A factory can have low α (many workstations relative to depth) and still have high C if the BOM is wide. The two metrics are therefore complementary: α describes scheduling pressure, C describes structural complexity.

For single-run programmatic access, `gen_result["complexity"]` holds the full `{product_id: C}` dict without needing a sweep.

### Output files

| File | Contents |
|---|---|
| `gen_stats.csv` | Per-run factory structure counts: raw materials, non-raw components, configurations, layout edges, and product complexity (`mean_complexity`, `max_complexity`) |
| `state_summary.csv` | Per-run, per-tick state percentages averaged across all workstations. "Working" combines Processing and Setup into a single column (`WorkingPct`); the file also includes `StarvedPct`, `BlockedPct`, and `FailedPct`. |
| `utilization.csv` | Per-run utilization breakdown across all workstations |
| `throughput.csv` | Per-run throughput and lead time for each completed order |
| `costs.csv` | Per-run cost breakdown per workstation |

All files include the run's sweep parameters and alpha as leading columns so rows from different runs can be distinguished and filtered.

### Visualize

### Single simulation run

Charts are shown automatically on the **Simulate** page in the UI after a run completes. The underlying script `engine/simulate/visualize_sim.py` can also be run standalone against existing CSVs. Five charts are produced:

1. **Machine state % over iterations** — for every tick, the percentage of all workstations in the Working, Starved, and Blocked states. Faint raw lines show per-tick values; bold lines show a rolling average. This chart follows the CLEMATIS convention from Lopes et al.
2. **Utilisation by workstation** — stacked bar showing how each workstation split its time across all five states.
3. **Throughput over time** — cumulative completed orders as a step chart, with mean lead time annotated.
4. **Cost breakdown** — stacked bar of setup, operating, and transport costs per workstation.
5. **Component buffer levels** — stock of each non-raw component buffer over time, with a capacity reference line.

### Parameter sweep

Charts are shown automatically on the **Sweep** page in the UI after a run completes. The underlying script `analysis/sweep/visualize_sweep.py` can also be run standalone against existing CSVs. Nine charts are organised into two sections:

**Generation Graphs** — properties of the generated factory structure as a function of the generation parameters:
1. Non-raw component count vs BOM depth (split by number of products)
2. Configuration count vs number of workstations (split by depth)

**Simulation Graphs** — DTS performance metrics across the parameter space:
3. Makespan vs α (split by depth)
4. Mean busy utilisation vs sharing ratio (split by number of products)
5. Total cost vs BOM depth — bar chart (split by number of products)
6. Mean lead time vs α (split by depth)
7. Starved % vs α (split by depth)
8. Mean state % over iterations — sweep-wide average of the CLEMATIS chart
9. **% Working machines vs α** (full-width) — shows how machine utilisation changes with the serial/parallel topology ratio, split by depth so each line covers its own α range

---

## Verify

The verification suite checks that the simulation behaves correctly by running a set of targeted tests and comparing results against known theoretical expectations. It is split into four groups of checks, ordered from purely mechanical to statistical.

### How to run

Run from the **Validate** page in the UI, or call it directly:

```python
from analysis.model_verification.verification import run_all

passed = run_all(show_charts=False, report_dir="analysis/model_verification/verification_output")
```

Results are written to `analysis/model_verification/verification_output/verification_report.txt` and displayed in the UI. Chart data is saved as CSVs in the same folder.

### Check groups

**1. Conservation laws** — must never fail

These checks verify properties that must hold by mathematical construction. A failure here always indicates a bug in the simulation logic, not a statistical fluctuation.

| Check | Description |
|---|---|
| Time balance | For every workstation, the sum of hours spent in all six states (`Busy + Setup + Blocked + Starved + Idle + Failed`) must equal exactly `actual_ticks × tick_duration`. |
| Cost non-negativity | Every cost column (`SetupCost`, `OperatingCost`, `TransportCost`, `RepairCost`) must be ≥ 0 for all workstations. |

**2. Boundary / degenerate cases** — unit tests with known outputs

Each test runs the simulation with an extreme input where the correct answer is known in advance, independent of randomness.

| Check | Input | Expected output |
|---|---|---|
| Zero orders | `n_orders = 0` | `throughput` DataFrame is empty. |
| Single order | `n_orders = 1` | Exactly one row in `throughput`. |
| Large buffer | `buffer_capacity = 1 000 000` | `BlockedPct = 0` for every workstation. |
| Large Weibull λ | `failures_enabled = True`, `λ = 1 000 000 h` | `FailedPct ≈ 0` (machine effectively never fails). |
| Full sharing | `sharing_ratio = 1.0`, `n_products = 1` | Number of non-raw components equals `depth` (one shared component per BOM level). |

**3. Monotonicity** — directional-effect tests

These checks verify that changing one parameter in a known direction produces the expected effect on the output metric. Each test sweeps one parameter across 10 levels and checks the direction of the trend. Because a fixed seed is used, results are deterministic.

| Check | Swept parameter | Expected direction |
|---|---|---|
| More workstations | `workstations_count`: 2 → 3 → … → 11 | Makespan weakly decreasing. |
| Larger buffer | `buffer_capacity`: 1 → 2 → … → 10 | Makespan weakly decreasing. |
| More orders | `n_orders`: 2 → 4 → … → 20 | Makespan strictly increasing. |
| Higher branching | `branching`: 1 → 2 → … → 10 | Non-raw component count strictly increasing. (Generator-only test; no simulation.) |
| Higher BOM quantity | `quantity`: [1,1] → [2,2] → … → [10,10] | Mean lead time strictly increasing. |

**4. Statistical / theoretical** — comparison against analytical benchmarks

These checks compare simulation output against predictions from queueing theory and reliability theory.

| Check | Theory | Tolerance |
|---|---|---|
| Little's Law | `L = λ × W`, where L is the average number of orders in the system, λ is the order arrival rate, and W is the mean lead time per order. | 50 % relative error (finite-sample and discretisation bias). |
| Steady-state availability | For exponential inter-failure times (β = 1): `A = λ / (λ + MTTR)`. Configured with λ = 20 h, MTTR = 4 h → A_theory ≈ 0.833. | ±10 percentage points. |

### Output files

All verification output is written to `analysis/model_verification/verification_output/`.

| File | Contents |
|---|---|
| `verification_report.txt` | Full PASS/FAIL report with per-check messages and timing |
| `val_orders.csv` | Cumulative orders completed over time (used by chart 1) |
| `val_buffers.csv` | Buffer stock per component over time (used by chart 2) |
| `val_availability.csv` | Observed and theoretical availability per workstation (used by chart 3) |
| `val_monotonicity.csv` | Monotonicity test results: swept parameter values, output metric values, pass/fail direction per test (used by the monotonicity chart) |

### Visualize

Diagnostic charts are shown automatically on the **Validate** page in the UI after a run completes. The underlying script `analysis/model_verification/visualize_verification.py` can also be run standalone against existing CSVs. Three diagnostic charts are shown in a single figure:

1. **Cumulative orders completed over time** — a step chart. A smooth staircase confirms the scheduler is making continuous progress. A prolonged flat section indicates deadlock or persistent starvation.
2. **Buffer levels over time** — stock of each non-raw component over the simulation, with a reference line at `buffer_capacity`. A line that reaches the cap and stays there signals a persistent blocking cascade upstream.
3. **Observed vs. theoretical availability** — a bar chart per workstation overlaid with the classical reliability prediction `A = λ / (λ + MTTR)`. Bars close to the reference line confirm that the Weibull failure model is sampling correctly.

---

## Use Cases

The `use_cases/` directory contains standalone analyses that run on top of the generated factory and simulation data. Each use case has its own script and README.

### Availability analysis

**Location:** `analysis/use_cases/availability_analysis/`  
**Entry point:** **Availability** page in the UI, or `python -m analysis.use_cases.availability_analysis.availability` standalone  
**README:** [`analysis/use_cases/availability_analysis/README.md`](analysis/use_cases/availability_analysis/README.md)

Compares two approaches to computing steady-state system availability for the generated factory:

| Approach | Description |
|---|---|
| **Theoretical (integrated)** | E[A_ws] is computed by 2-D numerical quadrature over the full (β, λ) distributions using the mean MTTR. System availability is then computed by exact 2^N workstation-state enumeration (or Monte Carlo for >22 workstations). Exact enumeration is required because workstations can be shared across components: a naive product of per-component availabilities would treat each shared workstation failure as independent per component, underestimating system availability. |
| **Experimental** | Monte Carlo: replications of the full Weibull failure–repair cycle on an adaptive time grid, aggregated into an empirical availability distribution and outage duration histogram. |

The simulation horizon and warm-up are scaled automatically to the workstation MTBF, so the analysis is well-conditioned across any configured parameter range. The script produces a three-panel figure (per-replication availability histogram; outage duration distribution; Monte Carlo convergence) and prints a comparison table to stdout. See the use case README for a full explanation of the methodology and how to interpret the results.

---

## Exporting Figures for Reports

`export_figures.py` re-renders all model figures in a report-friendly style (white background, print-friendly colours) and saves them as self-contained interactive HTML files. Open any exported file in a browser to inspect, zoom, and screenshot for a paper or report.

```bash
# From the model root:
python export_figures.py               # generate + sweep + verify → HTML (default)
python export_figures.py --generate    # factory layout graph only
python export_figures.py --sweep       # sweep figure only
python export_figures.py --verify      # verification diagnostics + monotonicity
python export_figures.py --availability  # availability (re-runs Monte Carlo, ~1–3 min)
python export_figures.py --all         # all figures including availability
```

Output files are written to `export/` in the model root:

| File | Figure |
|---|---|
| `generation.html` | Factory layout graph (Pyvis/vis.js) |
| `sweep.html` | Parameter sweep (9 charts) |
| `verification_diagnostics.html` | Verification diagnostics (3 charts) |
| `verification_monotonicity.html` | Monotonicity test trends (5 charts) |
| `availability.html` | Availability analysis — only with `--availability` or `--all` |

**Prerequisites:** the relevant CSV data must already exist on disk before running. Run Generate, Sweep, and Verify first (via the UI or `run.py`) to produce the required CSVs. The availability figure is the exception — it re-runs the Monte Carlo analysis on the fly and requires only `config.yaml` with `failures.enabled: true`.

---

## Model Limitations

This section documents the known simplifications and assumptions built into the model. Understanding these is important when interpreting simulation results or deciding whether the generated data is suitable for a given research question.

### Greedy, non-anticipating scheduler

The scheduler assigns workstations to demand items one at a time, in BOM-level order, picking whichever available machine would finish that single job the fastest. It has no look-ahead and no global view of the queue. This means it can make locally optimal decisions that are globally harmful — for example, committing the only machine capable of an urgent component to a low-priority changeover, or failing to batch consecutive same-component jobs together to avoid redundant setups. A real production planner would use dispatching rules based on order priority, critical path, or bottleneck awareness. The current approach generates realistic-looking inefficiencies (blocking cascades, unnecessary starvation), but may over- or under-represent them compared to a real factory running a smarter schedule.

### No stochasticity during simulation execution

Processing times and setup times are sampled randomly at factory generation time, but once fixed they are used as exact constants throughout the simulation. Every job of a given workstation–component pair always takes exactly the same number of ticks. Real production has variability in execution: a machine may run slower on a particular shift, a setup may take longer than expected, an operator may be faster one day than another. Because this variability is absent, the simulation produces smoother and more predictable utilisation patterns than a real factory would.

### Infinite raw material supply

Raw materials (BOM level 0) are given an effectively infinite stock and are never depleted. The model therefore cannot represent supply chain disruptions, procurement lead times, minimum order quantities, or supplier variability. All starvation in the simulation is caused entirely by upstream production delays, never by an actual shortage of input materials.

### Machine failures — partially addressed

This model adds stochastic machine failures (see the **Machine failures** subsection above). Each workstation can break down mid-job and requires a randomly sampled repair duration before returning to service. The failure model uses a **Weibull distribution**: with β > 1, older machines fail more often (wear-out behaviour), so this is not a purely random, memoryless process. However, age only accumulates during active work (setup or processing) — a workstation does not age while it is idle, starved, or blocked, which underestimates wear relative to calendar-time degradation. Every repair still performs a **perfect restoration**: the machine resets to age zero and draws a fresh time-to-failure, with no residual damage or gradual performance loss. The model also does not include **scheduled preventive maintenance** windows.

### No labour or operator constraints

Each workstation is assumed to always have a qualified operator available. There are no shift schedules, no lunch breaks, no skill-based restrictions on who can operate which machine, and no sharing of operators across multiple stations. In practice, labour is often the binding constraint rather than machine capacity.

### Instantaneous material transport

Transport costs are tracked and attributed per workstation, but transport takes zero time. Parts move from one stage to the next in the same tick they are deposited. Real factories have non-trivial internal logistics: parts travel between stations on conveyors, forklifts, or AGVs, introducing delays that can be a significant source of lead time and a further cause of starvation.

### Uniform buffer capacity

Every non-raw component buffer has the same `buffer_capacity` limit. In reality, buffer sizes vary by location, component size, and deliberate design choices (e.g. larger buffers in front of bottleneck stations). A single global capacity value cannot capture the asymmetric blocking behaviour that arises from heterogeneous buffer sizing.

### Fixed, deterministic order interarrival

Orders arrive at perfectly regular intervals (`order_interarrival` ticks apart). Real demand is stochastic: customer orders arrive with variable timing, batch sizes fluctuate, and rush orders interrupt the normal sequence. The regular arrival pattern means the simulation settles into a steady rhythm that real factories rarely achieve, which may cause utilisation and lead time figures to be artificially stable.

### No preemption

Once a job has started on a workstation it runs to completion. A higher-priority demand item that arrives mid-job cannot interrupt it. In some real scheduling environments (particularly when due-date pressure is high) preemption or job splitting is used to re-prioritise work mid-run; that behaviour is not modelled here.

### Flow capacity not enforced

Each material flow edge in the layout has a `flow_capacity` value (sampled from the configured range and stored in `layout.csv`). The current simulator does not enforce this limit; all edges are treated as having unlimited throughput at runtime. Flow capacity is recorded for reference and potential future use, but cannot currently cause congestion or blocking between stages.

### Availability analysis assumes no cascading starvation

The theoretical availability calculation (see [Availability analysis](#availability-analysis)) predicts steady-state system uptime based on individual workstation MTBF and MTTR values. It correctly accounts for shared workstations by enumerating all possible failure-state combinations. However, it does not model the downstream effect of a prolonged repair: a workstation that is down for an extended period can drain the intermediate buffers that feed subsequent stages, causing starvation cascades that the theoretical formula does not predict. The theoretical availability therefore provides an optimistic upper bound; the experimental Monte Carlo result is a closer reflection of actual throughput loss under failure conditions.

### No quality control or scrap

All units produced are assumed to be defect-free. There is no rework, no scrap rate, and no re-inspection. The Quality Inspection node (QI) is purely a sink — it does not reject or hold back any output. In reality, quality failures drive additional production demand, consume machine time on rework, and introduce feedback loops that are absent from this model.

### Parameter combinations can cause irrecoverable deadlock

Certain combinations of `bom.depth`, `workstations.count`, `bom.branching`, and `simulation.buffer_capacity` lead to a **permanent blocking/starvation cascade** from which the simulation cannot recover — resulting in zero completed orders even if `n_ticks` is very large.

**Mechanism.** With a deep BOM (depth ≥ 5) and few workstations, each BOM level may have only one or two workstations. A typical cascade looks like this:

1. Each level-1 workstation produces many component types. It fills the buffer for one component to `buffer_capacity` and enters the **blocked** state.
2. A blocked workstation cannot be reassigned to a different component — it must wait until the downstream consumer takes a unit. But the downstream consumer is **starved**: the specific component *it* needs is at stock = 0 (a different component from the one that is blocking).
3. Because every level-1 workstation is blocked on a different full-buffer component, no level-1 production can proceed. All higher-level assembly is therefore permanently starved.
4. This deadlock persists for the remainder of the simulation. No orders complete.

This is mechanically analogous to a **circular-wait deadlock** in a concurrent system, except that the wait cycle involves mismatched component types rather than resource locks. Unlike real factories — where a supervisor would physically move parts, use overflow storage, or cancel and restart jobs — the DTS scheduler has no intervention mechanism and no global view of the deadlock state.

**The α threshold.** The sweep analysis shows a clear phase transition around **α = depth / workstations_count ≈ 0.3–0.4**. Below this threshold most configurations complete all orders; above it starvation escalates sharply. As a practical guideline:

| α range | Typical behaviour |
|---|---|
| < 0.3 | Orders usually complete; starvation is transient |
| 0.3 – 0.5 | Increasing risk of partial or total deadlock |
| > 0.5 (with deep BOM) | High probability of permanent deadlock; zero orders completed |

**Buffer capacity interaction.** The deadlock risk compounds when `buffer_capacity` is small relative to the BOM explosion quantity. BOM explosion quantities grow as `branching_max ^ depth × quantity_max`, so at depth 5 with branching [2, 3] and quantity [1, 3] one order can require hundreds of units of a level-1 component. If `buffer_capacity` is only 10, workstations fill their output buffers quickly and spend most of the simulation blocked.

**Config consistency guidelines.** To avoid this condition:

- Keep `α = depth / workstations.count` below **0.3** when using `assembly_type` with a deep BOM. This means `workstations.count` should scale with `depth`, not remain fixed as depth increases.
- Set `buffer_capacity` to at least **`branching_max ^ depth × quantity_max`** if you want to be certain that blocking is not the binding constraint. For sweeps up to depth 4 and branching [2, 3], a value of 50–100 is usually sufficient.
- For sweep grids that include `depth > 4`, verify on a single run at the highest depth and lowest workstation count that at least one order completes before committing to the full grid.
- The **Sweep** page in the UI warns when swept `depth > 4` is detected; treat those runs as exploratory rather than production-quality simulation results.
