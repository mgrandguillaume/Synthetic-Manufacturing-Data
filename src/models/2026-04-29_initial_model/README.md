# Simple Assembly Factory — Synthetic Data Model

This model generates and simulates a small synthetic assembly factory driven by a single config file (`config.yaml`). Running **Generate** first produces the factory structure; running **Simulate** replays orders through it.

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

The graph is structured with the specific conventions. As a basis, the graph contains 'levels' which represent a new stage in the processing flow. The level numbers run from the bottom up: raw materials sit at `level 0`, intermediate components (`COMP_*`) occupy the levels in between, and finished products (`PROD_*`) sit at the highest level (`level = depth`). So a higher level number means closer to the finished product, following conventions used in ERP systems.

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

| Parameter                 | Description                                                                                                                    |
|---------------------------|--------------------------------------------------------------------------------------------------------------------------------|
| `workstation_count`       | The number of workstations                                                                                                     |
| `producers_per_component` | How many workstations are capable of producing each component (randomly sampled per component, clamped to ≤ workstation count) |
| `processing_time`         | Time to produce one unit of a component                                                                                        |
| `setup_time`              | Time required for a changeover when a workstation switches to a different component                                            |
| `setup_cost`              | Cost charged once per changeover                                                                                               |
| `operating_cost`          | Cost per unit produced                                                                                                         |

**Bill of materials**

A Bill of Materials (BOM) is a structured list of all components, sub-components, and raw materials required to produce a finished product, along with the quantities needed at each stage. In a manufacturing context it defines what needs to be made and from what.
The model allows us to configurate the BOM through the `bill of materials configurations`. The following table states these configurations.

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

Note that the `branching` value is randomly drawn from a uniform distribution independently for every component
```
branching = 2:          branching = 3:

Level = 1    COMP_1      Level = 1      COMP_1
             /    \                    /   |   \
Level = 0  R1      R2   Level = 0   R1   R2   R3
```

**Layout**

Finally, the `layout` of the structure can be configured with the following variables stated in the table.

| Parameter | Description                                                                                                                                          |
|---|------------------------------------------------------------------------------------------------------------------------------------------------------|
| `topology` | How workstations are connected: `parallel` (Inventory → each WS → QI independently) or `linear` (Inventory → WS_1 → WS_2 → … → QI as a single chain) |
| `flow_capacity` | Maximum number of units that can flow along an edge (randomly sampled within range, sampled per workstaion connection)                               |
| `transport_cost` | Cost per unit transported along an edge (randomly sampled within range)                                                                              |

The following diagram illustrates the two topology types.

```
topology = "parallel":            topology = "linear":

         ┌── WS_1 ──┐                  Inv ── WS_1 ── WS_2 ── WS_3 ── QI
Inv ─────┼── WS_2 ──┼───── QI
         └── WS_3 ──┘
```

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
**Dependency:** `pip install pandas`  
**Run:** `python simulate/simulate.py`

The simulator reads the five CSVs produced by Generate and replays a series of production orders through the factory. It uses a simple discrete-event-style scheduler (no external simulation library) and writes its results to `simulate/sim_output/`.

### What it does

**Order assignment**

The simulation runs a fixed number of production orders (`N_ORDERS`), processing them one at a time in sequence. Each order is always for exactly one unit of a product.

The simulator known the number of total orders, and the number of all the possible output products (decided in the generation stage). The orders do not specify what product is needed, so it evenly divides the orders over all possible products.  With 2 products and 6 orders, each product gets exactly 3 orders. With 2 products and 5 orders, the first product gets 3 and the second gets 2.

**BOM explosion**

Before any production can be scheduled, the simulator needs to know the total number of units of *every* component required to fulfil the order; not just the direct inputs of the product, but the inputs of those inputs, all the way down to raw materials. This process is called a BOM explosion.

It works top-down, level by level. Starting with one unit of the finished product, the simulator looks up what that product directly requires and in what quantities. It then moves down one level and repeats for each of those components, multiplying quantities as it goes. This continues until raw materials are reached.

The reason it must go level by level rather than expanding each branch independently is **shared components**. If the same intermediate component appears under two different parents, its required quantity must be accumulated from both parents before its own inputs are expanded; otherwise the raw material quantities would be undercounted.

The result is a flat list of every component involved in the order and exactly how many units of each are needed.

**Scheduling**

With the full list of required components and quantities known, the simulator schedules their production from the bottom up: raw materials first, then intermediate components, then the finished product. This mirrors physical reality; a component cannot be assembled until all of its inputs are ready.

Raw materials are assumed to be available from Inventory instantly at no production cost, so they require no scheduling. This is the **infinite supply assumption**.

For every other component, the simulator looks at all workstations capable of producing it and asks: *which one would finish this job the earliest?* For each candidate workstation it considers three things:

- **Availability** - when does the workstation finish its current job? The new job cannot start before then.
- **Setup changeover** - is the workstation currently configured for a different component? If so, a setup period must happen before production can begin. If the workstation is already configured for this component (from a previous job), no setup is needed and production starts immediately.
- **Processing time** - how long does it take to produce the required number of units at this workstation? Processing time scales linearly with quantity.

The workstation with the earliest projected finish time is selected. The job is then locked in: a setup event is recorded if a changeover was needed, followed by a processing event. The workstation is marked as occupied until the job is complete, and its current configuration is updated to reflect the new component so future jobs know whether a changeover will be needed.

A component can only begin once *all* of its inputs are finished. If two inputs finish at different times, the component waits for the slowest one. The time spent waiting, from when the last input was ready to when processing actually started, is recorded as the wait time for that job.

**Cost tracking**

Three types of cost are accumulated throughout the simulation:

- **Setup cost** - charged once each time a workstation switches from producing one component to another.
- **Operating cost** - charged per unit produced at a workstation.
- **Transport cost** - charged per unit moved from Inventory to the workstation, based on the cost of that connection in the layout.

These are tracked per workstation and summed over all orders.

**Utilisation**

Once all orders are complete, the simulator calculates how each workstation spent its time over the full simulation. The time from the start until the last job finishes across all workstations defines the total time span. Each workstation's time is then broken down into three categories: time spent actively producing (`busy`), time spent on setup changeovers (`setup`), and time spent waiting with nothing to do (`idle`).

### Output files

| File | Contents |
|---|---|
| `gantt.csv` | Start and finish time of every setup and processing event, per workstation and order |
| `utilization.csv` | Total busy, setup, and idle time per workstation over the full simulation |
| `throughput.csv` | Completion time and cumulative order count for each finished order |
| `costs.csv` | Setup, operating, and transport costs aggregated per workstation |
| `wait_times.csv` | How long each component waited at its workstation before processing began |
