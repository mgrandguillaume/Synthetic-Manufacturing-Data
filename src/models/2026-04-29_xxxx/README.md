# Synthetic Generation Model From Rafael - Explanation

## The 4 Main Building Blocks

### 1. Bill of Materials (BOM)
Builds a DAG (Directed Acyclic Graph) of components. With `depth: 2` and `n_products: 2`:
- Level 0 → raw materials (`RAW_L0_*`)
- Level 1 → intermediate components (`COMP_L1_*`)
- Level 2 → finished products (`PROD_1`, `PROD_2`)

Each parent node randomly gets 2–3 children (`branching: [2,3]`), with random quantities per edge. The `sharing_ratio` controls how often components are shared between products (realism: same subcomponent used in multiple products).

### 2. Workstations
Creates 4 assembly workstations (`WS_1`…`WS_4`), plus two fixed nodes: **Inv** (raw material inventory) and **QI** (quality inspection / exit).

### 3. Configurations
For every producible component (intermediates + products), randomly assigns 1–2 workstations that can produce it, with random processing time, setup time, setup cost, and operating cost. This is essentially the **capability matrix** of the factory.

### 4. Layout (material flow graph)
Defines how material flows between stations. Two options from config:
- `parallel`: Inv → each WS independently → QI
- `linear` *(current)*: Inv → WS1 → WS2 → WS3 → WS4 → QI (a single assembly line)

Each edge has a flow capacity and transport cost.

---

## Output

Five CSVs are written to the `output/` folder:

| File | Content |
|---|---|
| `components.csv` | All parts with their level |
| `bom.csv` | Parent–child relationships + quantities |
| `workstations.csv` | All stations |
| `configurations.csv` | Which WS can make which component + costs/times |
| `layout.csv` | Material flow edges + capacity/cost |

---

## Config

### BOM

| Variable | Meaning |
|---|---|
| `n_products` | Number of finished products to generate |
| `depth` | Number of levels in the component tree (e.g. 2 = raw → intermediate → product) |
| `branching` | Range for how many child components each parent requires |
| `quantity` | Range for how many units of a child are needed per parent unit |
| `sharing_ratio` | Probability that a component is reused across different products |

### Workstations

| Variable | Meaning |
|---|---|
| `count` | Number of assembly workstations (excludes Inv and QI which are added automatically) |

### Configurations

| Variable | Meaning |
|---|---|
| `producers_per_component` | Range for how many workstations can produce each component |
| `processing_time` | Hours needed to produce one unit of a component |
| `setup_time` | Hours needed to set up a workstation before producing a component |
| `setup_cost` | Cost per setup (paid each time a workstation switches to producing a component) |
| `operating_cost` | Cost per unit produced |

### Layout

| Variable | Meaning |
|---|---|
| `topology` | Flow structure: `parallel` (each WS independent) or `linear` (chain) |
| `flow_capacity` | Range for max units that can flow through a transport edge |
| `transport_cost` | Range for cost per unit transported along an edge |
