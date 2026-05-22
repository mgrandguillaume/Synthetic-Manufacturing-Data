# Simple Assembly Factory — Synthetic Data Model

This model generates and simulates a small synthetic assembly factory driven by a single config file (`config.yaml`). Running **Generate** first produces the factory structure; running **Simulate** replays production orders through it using a Discrete-Time Simulation. Running **Sweep** repeats this across a grid of structural parameters for analysis.

---

## Contents

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
- [Sweep](#sweep)
  - [Parameter groups](#parameter-groups)
  - [Alpha (α)](#alpha-α)
  - [Output files](#output-files-2)
  - [Visualize](#visualize)
    - [Single simulation run](#single-simulation-run)
    - [Parameter sweep](#parameter-sweep)
- [Validate](#validate)
  - [How to run](#how-to-run)
  - [Check groups](#check-groups)
  - [Output files](#output-files-3)
  - [Visualize](#visualize-1)
- [Use Cases](#use-cases)
  - [Availability analysis](#availability-analysis)
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
  - [No quality control or scrap](#no-quality-control-or-scrap)

---

## Generate

**Script:** `generate/generate.py`  
**Dependency:** `pip install pyyaml`  
**Run:** `python generate/generate.py`

The generator builds a complete factory description from `config.yaml` and writes five CSV files to `generate/gen_output/`. Generation proceeds in six sequential steps:

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

**BOM parameters**

| Parameter | Description |
|---|---|
| `n_products` | Number of finished products to generate |
| `depth` | Number of BOM levels (`depth = 2` means raw → intermediate → product) |
| `branching` | `[min, max]` — number of children each node requires; sampled independently per node |
| `quantity` | `[min, max]` — units of each input required per BOM edge; sampled per edge |
| `sharing_ratio` | Probability (0–1) that an existing component at a given level is reused instead of a new one being created |

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

Note that α captures the *average* stage size. With `stage_balance` set to a low value, individual stages can deviate significantly from this average — two factories with the same α can have very different bottleneck patterns.

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

For each producible component at BOM level *l*, the generator randomly selects between `producers_per_component[0]` and `producers_per_component[1]` workstations from stage *l*. Each selected `(workstation, component)` pair gets independently sampled timing and cost values.

**Configuration parameters**

| Parameter | Description |
|---|---|
| `producers_per_component` | `[min, max]` — how many workstations can produce each component; clamped to the stage size |
| `assembly_type` | `"low"`, `"medium"`, or `"high"` — sets the (α, β) coefficients for the processing-time formula (see below). Mutually exclusive with `processing_time`. |
| `variation` | Fractional spread around the formula value, e.g. `0.10` for ±10 %. Each (workstation, component) pair is sampled independently within this band. Default: `0.10`. |
| `processing_time` | `[min, max]` hours — legacy explicit range. Used only when `assembly_type` is absent. |
| `setup_time` | `[min, max]` hours — changeover time when switching to this component; sampled per pair |
| `setup_cost` | `[min, max]` — cost charged once per changeover; sampled per pair |
| `operating_cost` | `[min, max]` — cost per unit produced; sampled per pair |

**Processing-time formula**

When `assembly_type` is set, processing time is derived from the BOM depth using an exponential approximation:

```
processing_time = α · depth^β   ±  variation
```

`depth` is the same value used for BOM construction, so deeper factories automatically produce components that take longer to assemble. The (α, β) coefficients by assembly type are:

| `assembly_type` | α | β |
|---|---|---|
| `low` | 0.33 | 1.39 |
| `medium` | 0.28 | 1.45 |
| `high` | 0.12 | 1.79 |

For example, with `assembly_type: medium`, `depth: 5`, and `variation: 0.10`:

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

---

## Simulate

**Script:** `simulate/simulate.py`  
**Dependency:** `pip install pandas pyyaml numba`  
**Run:** `python simulate/simulate.py`

> This model extends the optimized model with **machine failures**. Enable them in the `failures:` section of `config.yaml`.

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
| `utilization.csv` | Time (hours) and percentage spent in each of the six states per workstation (includes `Failed` and `FailedPct`) |
| `throughput.csv` | Completion time, cumulative order count, and lead time for each finished order |
| `costs.csv` | Setup, operating, transport, and repair costs aggregated per workstation (includes `RepairCost`) |
| `buffers.csv` | Stock level of every non-raw component buffer at every tick |

---

## Sweep

**Script:** `sweep.py`  
**Dependencies:** `pip install pyyaml pandas`  
**Run:** `python sweep.py`

The sweep runs Generate and Simulate for every combination of a set of structural parameters, and collects all outputs into aggregated CSVs. This allows the effect of each parameter on factory performance to be studied across the full parameter space.

### Parameter groups

The sweep uses three parameter groups:

**`PARAM_GRID`** — the parameters that are swept. Every combination is tested (81 runs total):

| Parameter | Values |
|---|---|
| `n_products` | 1, 2, 4 |
| `depth` | 1, 2, 3 |
| `workstations_count` | 2, 4, 8 |
| `sharing_ratio` | 0.0, 0.5, 1.0 |

**`FIXED_PARAMS`** — factory structure parameters held constant across all runs. Values are given as ranges `[min, max]`; the generator samples uniformly within these ranges for each run, introducing natural variation. A fixed `seed` ensures reproducibility.

**`SIM_PARAMS`** — simulation settings (`n_orders`, `tick_duration`, `buffer_capacity`, `order_interarrival`, `n_ticks`) that are identical for every run.

### Alpha (α)

For each run, the alpha parameter is computed as:

```
α = depth / workstations_count
```

Alpha is a derived topology metric that summarises the serial/parallel structure of the factory (see the Layout section under Generate). It is prepended to every output row so that results can be grouped and plotted against it directly.

### Output files

| File | Contents |
|---|---|
| `gen_stats.csv` | Per-run factory structure counts: raw materials, non-raw components, configurations, layout edges |
| `state_summary.csv` | Per-run, per-tick state percentages (Working / Starved / Blocked) averaged across all workstations |
| `utilization.csv` | Per-run utilization breakdown across all workstations |
| `throughput.csv` | Per-run throughput and lead time for each completed order |
| `costs.csv` | Per-run cost breakdown per workstation |

All files include the run's sweep parameters and alpha as leading columns so rows from different runs can be distinguished and filtered.

### Visualize

### Single simulation run

**Script:** `simulate/visualize_sim.py`  
**Run:** `python simulate/visualize_sim.py`

Reads the CSVs from `simulate/sim_output/` and shows five charts:

1. **Machine state % over iterations** — for every tick, the percentage of all workstations in the Working, Starved, and Blocked states. Faint raw lines show per-tick values; bold lines show a rolling average. This chart follows the CLEMATIS convention from Lopes et al.
2. **Utilisation by workstation** — stacked bar showing how each workstation split its time across all five states.
3. **Throughput over time** — cumulative completed orders as a step chart, with mean lead time annotated.
4. **Cost breakdown** — stacked bar of setup, operating, and transport costs per workstation.
5. **Component buffer levels** — stock of each non-raw component buffer over time, with a capacity reference line.

### Parameter sweep

**Script:** `visualize_sweep.py`  
**Run:** `python visualize_sweep.py`

Reads the CSVs from `sweep_output/` and shows nine charts organised into two sections:

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

## Validate

**Scripts:** `validate/validate.py`, `validate/visualize_validation.py`  
**Dependencies:** `pip install pyyaml pandas plotly numba`  
**Run:** `python run.py --validate` or `python run.py --validate-only`

The validation suite checks that the simulation behaves correctly by running a set of targeted tests and comparing results against known theoretical expectations. It is split into four groups of checks, ordered from purely mechanical to statistical.

### How to run

```
python run.py --validate        # full pipeline (generate → sweep → visualize) then validate
python run.py --validate-only   # skip generate/sweep, run validation immediately
```

Results are printed to the console as `[PASS]` / `[FAIL]` and written to `validate/validation_output/validation_report.txt`. Chart data is saved as CSVs in the same folder.

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

These checks verify that changing one parameter in a known direction produces the expected effect on makespan. Each test runs the simulation at three levels of one swept parameter and checks the direction of the trend. Because a fixed seed is used, results are deterministic.

| Check | Swept parameter | Expected direction |
|---|---|---|
| More workstations | `workstations_count`: 2 → 4 → 8 | Makespan weakly decreasing. |
| Larger buffer | `buffer_capacity`: 2 → 10 → 100 | Makespan weakly decreasing. |
| More orders | `n_orders`: 3 → 6 → 12 | Makespan strictly increasing. |

**4. Statistical / theoretical** — comparison against analytical benchmarks

These checks compare simulation output against predictions from queueing theory and reliability theory.

| Check | Theory | Tolerance |
|---|---|---|
| Little's Law | `L = λ × W`, where L is the average number of orders in the system, λ is the order arrival rate, and W is the mean lead time per order. | 50 % relative error (finite-sample and discretisation bias). |
| Steady-state availability | For exponential inter-failure times (β = 1): `A = λ / (λ + MTTR)`. Configured with λ = 20 h, MTTR = 4 h → A_theory ≈ 0.833. | ±10 percentage points. |

### Output files

| File | Contents |
|---|---|
| `validation_output/validation_report.txt` | Full PASS/FAIL report with per-check messages and timing |
| `validation_output/val_orders.csv` | Cumulative orders completed over time (used by chart 1) |
| `validation_output/val_buffers.csv` | Buffer stock per component over time (used by chart 2) |
| `validation_output/val_availability.csv` | Observed and theoretical availability per workstation (used by chart 3) |

### Visualize

**Script:** `validate/visualize_validation.py`  
**Run:** `python validate/visualize_validation.py`

Reads the four CSVs from `validation_output/` and shows three diagnostic charts in a single figure:

1. **Cumulative orders completed over time** — a step chart. A smooth staircase confirms the scheduler is making continuous progress. A prolonged flat section indicates deadlock or persistent starvation.
2. **Buffer levels over time** — stock of each non-raw component over the simulation, with a reference line at `buffer_capacity`. A line that reaches the cap and stays there signals a persistent blocking cascade upstream.
3. **Observed vs. theoretical availability** — a bar chart per workstation overlaid with the classical reliability prediction `A = λ / (λ + MTTR)`. Bars close to the reference line confirm that the Weibull failure model is sampling correctly.

---

## Use Cases

The `use_cases/` directory contains standalone analyses that run on top of the generated factory and simulation data. Each use case has its own script and README.

### Availability analysis

**Location:** `use_cases/availability_analysis/`  
**Entry point:** `python use_cases/availability_analysis/availability.py`  
**README:** [`use_cases/availability_analysis/README.md`](use_cases/availability_analysis/README.md)

Compares three approaches to computing steady-state system availability for the generated factory:

| Approach | Description |
|---|---|
| **Theoretical (midpoint)** | Weibull MTTF computed from the midpoint of each parameter range; exact 2^N workstation-state enumeration propagated through the factory's RBD topology |
| **Theoretical (integrated)** | Same state enumeration, but E[A_ws] is evaluated by numerical integration over the full (β, λ, MTTR) parameter distributions — corrects for Jensen's inequality |
| **Experimental** | Monte Carlo: 1 000 replications of the full Weibull failure–repair cycle, aggregated into an empirical availability distribution |

The script produces a three-panel figure (histogram of experimental replications with both theoretical lines; per-component availability bar chart; system-level summary) and prints a comparison table to stdout. See the use case README for a full explanation of the methodology and how to interpret the results.

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

### No quality control or scrap

All units produced are assumed to be defect-free. There is no rework, no scrap rate, and no re-inspection. The Quality Inspection node (QI) is purely a sink — it does not reject or hold back any output. In reality, quality failures drive additional production demand, consume machine time on rework, and introduce feedback loops that are absent from this model.
