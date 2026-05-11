# Simple Assembly Factory — Synthetic Data Model

This model generates and simulates a small synthetic assembly factory driven by a single config file (`config.yaml`). Running **Generate** first produces the factory structure; running **Simulate** replays production orders through it using a Discrete-Time Simulation. Running **Sweep** repeats this across a grid of structural parameters for analysis.

---

## Generate

**Script:** `generate/generate.py`  
**Dependency:** `pip install pyyaml`  
**Run:** `python generate/generate.py`

The generator builds a complete factory description from `config.yaml` and writes it to `generate/gen_output/` as five CSV files.

### What it builds

**Workstations**  
A workstation represents a single machine or assembly station on the factory floor. Each workstation can perform one type of operation at a time. They are represented as nodes.

**Connections**  
Connections are directed edges between workstations that define the path materials travel through the factory. A connection from workstation A to workstation B means that output from A flows as input into B.

Two fixed nodes are always present: Inv (Inventory) as the source, where all raw materials originate, and QI (Quality Inspection) as the sink, where finished products exit the factory. A configurable number of assembly workstations (WS_1, WS_2, …) are placed in between.

**Structure**  
The workstations are represented in a Directed Acyclic Graph (DAG) structure. Workstations are represented as nodes which are connected by edges representing the flow of materials.

The graph is structured with specific conventions. As a basis, the graph contains 'levels' which represent a new stage in the processing flow. The level numbers run from the bottom up: raw materials sit at `level 0`, intermediate components (`COMP_*`) occupy the levels in between, and finished products (`PROD_*`) sit at the highest level (`level = depth`). So a higher level number means closer to the finished product, following conventions used in ERP systems.

Components are automatically assigned an ID using the format `<TYPE>_L<level>_<counter>`:
- **`RAW_L0_3`** — the 3rd raw material at level 0
- **`COMP_L1_1`** — the 1st intermediate component created at BOM level 1
- **`PROD_2`** — the 2nd finished product (products drop the level suffix as they always sit at the top)

The following diagram depicts these conventions.

```
Level = 2 (depth)       PROD_1
                        /    \
Level = 1           COMP_L1_1  COMP_L1_2
                    /    \
Level = 0       RAW_L0_1  RAW_L0_2
```

### Configurations

Now that the standard conventions have been specified, the configurations of the structure will be addressed. There are three main sections of configurations. Namely, `workstation configurations`, `bill of materials configurations` and the `layout`.

**Workstation configurations**

The `workstation configurations` regard the settings that can be applied to these workstations. These are described in the following table.

| Parameter                 | Description                                                                                                                                                    |
|---------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `workstation_count`       | The number of workstations                                                                                                                                     |
| `producers_per_component` | How many workstations are capable of producing each component (randomly sampled per component, clamped to ≤ the number of workstations in that component's stage) |
| `processing_time`         | Time to produce one unit of a component                                                                                                                        |
| `setup_time`              | Time required for a changeover when a workstation switches to a different component                                                                            |
| `setup_cost`              | Cost charged once per changeover                                                                                                                               |
| `operating_cost`          | Cost per unit produced                                                                                                                                         |

**Bill of materials**

A Bill of Materials (BOM) is a structured list of all components, sub-components, and raw materials required to produce a finished product, along with the quantities needed at each stage. In a manufacturing context it defines what needs to be made and from what.
The model allows us to configure the BOM through the `bill of materials configurations`. The following table states these configurations.

| Parameter | Description |
|---|---|
| `n_products` | Number of finished products to generate |
| `depth` | Number of levels in the BOM tree (e.g. `depth = 2` means raw → intermediate → product) |
| `branching` | Number of input components each component requires (randomly sampled within range) |
| `quantity` | Number of units of each input component required per BOM edge (randomly sampled within range) |
| `sharing_ratio` | Probability that an existing component at a given level is reused instead of a new one being created |

Both the `branching` and `sharing_ratio` require some more detailed explanation:

A `sharing_ratio` parameter introduces realistic component sharing: when a new input component is needed, there is a `sharing_ratio` chance that an already-existing component at that level is reused instead of a brand-new one being created. This means a single lower-level component can end up serving as an input to multiple higher-level components.

```
sharing_ratio = 0 (no sharing):         sharing_ratio > 0 (with sharing):

Level = 2   PROD_1      PROD_2          Level = 2   PROD_1        PROD_2
             /   \       /   \                        /   \         /   \
Level = 1  C1    C2    C3    C4         Level = 1  C1     C2      C1    C3
                                                           ^______^
                                                            shared
```

Where `C1` = `COMP_L1_1`, `C2` = `COMP_L1_2`, etc. In the sharing example, `COMP_L1_1` is required by both `PROD_1` and `PROD_2`, so instead of 4 unique level-1 components there are only 3.

Note that the `branching` value is randomly drawn from a uniform distribution independently for every component.
```
branching = 2:          branching = 3:

Level = 1    COMP_1      Level = 1      COMP_1
             /    \                    /   |   \
Level = 0  R1      R2   Level = 0   R1   R2   R3
```

**Layout**

The layout of the factory is derived automatically from a **stage assignment** based on the BOM depth and workstation count. The key concept is the **alpha (α) parameter**:

```
α = depth / workstations_count
```

Alpha controls how many workstations are assigned to each BOM stage:
- **α ≈ 1** — roughly one workstation per stage; the factory is serial and each workstation is specialised for one BOM level.
- **α ≈ 0** — many workstations per stage; the factory is wide and parallel with high redundant capacity at each level.

The workstations are divided into `depth` groups (stages) using floor-based arithmetic. A workstation in stage *l* can only produce components at BOM level *l*. The layout edges follow directly from this assignment:

- **Inv → every workstation in stage 1** (raw materials enter at the first processing stage)
- **Every workstation in stage *l* → every workstation in stage *l*+1** (for l = 1 … depth−1)
- **Every workstation in stage depth → QI** (finished products leave the factory)

Within each stage the workstations operate in parallel; between stages the flow is serial.

```
depth = 3, workstations = 3  (α = 1.0 — one WS per stage, serial):

Inv ── WS_1 ──────────── WS_2 ──────────── WS_3 ── QI
       stage 1            stage 2            stage 3
      (level 1)          (level 2)          (level 3)


depth = 2, workstations = 4  (α = 0.5 — two WSs per stage, parallel):

           ┌── WS_1 ──┐               ┌── WS_3 ──┐
Inv ───────┤           ├───────────────┤           ├─── QI
           └── WS_2 ──┘               └── WS_4 ──┘
           ──── stage 1 ────           ──── stage 2 ────
             (BOM level 1)               (BOM level 2)
```

The two configurable layout parameters control edge properties:

| Parameter | Description |
|---|---|
| `flow_capacity` | Maximum number of units that can flow along an edge (randomly sampled within range per edge) |
| `transport_cost` | Cost per unit transported along an edge (randomly sampled within range per edge) |

### Output files

| File | Contents |
|---|---|
| `components.csv` | All components with their ID, name, BOM level, and whether they are a final product |
| `bom.csv` | BOM edges: which component is required (`Input`), for which parent (`Output`), and in what quantity |
| `workstations.csv` | All workstations (source, production, sink) |
| `configurations.csv` | Which workstation can produce which component, and at what cost/time |
| `layout.csv` | Material flow edges between workstations with capacity and transport cost |

---

## Simulate

**Script:** `simulate/simulate.py`  
**Dependency:** `pip install pandas pyyaml`  
**Run:** `python simulate/simulate.py`

The simulator reads the five CSVs produced by Generate and replays a series of production orders through the factory. It uses a **Discrete-Time Simulation (DTS)** approach: time advances in fixed steps called *ticks*, and every workstation is evaluated simultaneously at each tick. This allows multiple workstations to produce different components at the same time (concurrency), and captures two failure modes that a purely sequential scheduler cannot see:

- **Blocking** — a workstation has finished a job but the output buffer is full; it holds the units and waits until space opens up downstream.
- **Starvation** — a workstation is ready to start a job but the input components it needs have not yet arrived in the buffer; it waits until upstream production catches up.

All simulation parameters (`tick_duration`, `buffer_capacity`, `order_interarrival`, `n_ticks`, `n_orders`) are set in the `simulation:` section of `config.yaml`. Results are written to `simulate/sim_output/`.

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

**Cost tracking**

Three types of cost are accumulated throughout the simulation:

- **Setup cost** — charged once each time a workstation switches from producing one component to another.
- **Operating cost** — charged per unit produced at a workstation.
- **Transport cost** — charged per unit moved into a workstation, calculated as the average cost of all incoming layout edges for that workstation. Stage-1 workstations are fed directly from Inv; higher-stage workstations are fed from the previous stage's workstations.

These are tracked per workstation and summed over all orders.

**Utilisation**

Each workstation spends every tick in exactly one of five states. At the end of the simulation the total time and percentage spent in each state is computed per workstation:

- **Processing** — actively producing units.
- **Setup** — performing a changeover before switching to a new component type.
- **Blocked** — processing is done but the output buffer is full; waiting for space to open.
- **Starved** — has pending demand but the required input components are not yet in the buffer.
- **Idle** — no pending demand; nothing to do.

### Output files

| File | Contents |
|---|---|
| `states.csv` | Per-tick record of every workstation's state (`idle`, `setup`, `processing`, `blocked`, or `starved`) |
| `utilization.csv` | Time (hours) and percentage spent in each of the five states per workstation |
| `throughput.csv` | Completion time, cumulative order count, and lead time for each finished order |
| `costs.csv` | Setup, operating, and transport costs aggregated per workstation |
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

---

## Visualize

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
