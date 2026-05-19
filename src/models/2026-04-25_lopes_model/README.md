# Lopes / CLEMATIS Model

This model implements the factory simulation described by Lopes et al. in the CLEMATIS framework. It generates a production network from two parameters and simulates continuous material flow through it using a Discrete-Time Simulation. Unlike the BOM-based models, there are no production orders — the factory runs continuously with infinite raw material supply and infinite downstream demand.

---

## Generate

**Script:** `generate.py`  
**Dependency:** `pip install numpy`  
**Run:** called automatically by `run.py`

The generator builds a directed acyclic graph (DAG) of workstations from two scalar parameters — the number of nodes `n` and the seriality `s` — and returns the graph structure as Python data structures. No CSV files are written; the output is passed directly to the simulator.

### What it builds

**Workstations**  
Each node in the graph represents a single workstation. Workstations are grouped into sequential *production steps* based on the seriality parameter. Every workstation in step *i* receives material from all workstations in step *i−1* and feeds all workstations in step *i+1*. The first step has infinite raw material supply; the last step feeds finished product out of the factory.

**Seriality and production steps**  
The number of production steps is derived directly from the two parameters:

```
p_steps = floor(n × s)
```

- `s = 1.0` (fully serial) — every workstation is its own step, forming a single chain.
- `s = 0.0` (fully parallel) — all workstations are in one step, all doing the same job independently.
- `0 < s < 1` — intermediate structures with multiple workstations per step.

```
n = 6, s = 1.0  (3 steps, 2 nodes each → serial):

Inv ── WS_0 ── WS_1 ── WS_2 ── WS_3 ── WS_4 ── WS_5 ── Out
       step 0   step 1   step 2   step 3   step 4   step 5


n = 6, s = 0.5  (3 steps, 2 nodes each → mixed):

           ┌── WS_0 ──┐         ┌── WS_2 ──┐         ┌── WS_4 ──┐
Inv ───────┤           ├─────────┤           ├─────────┤           ├─── Out
           └── WS_1 ──┘         └── WS_3 ──┘         └── WS_5 ──┘
           ── step 0 ──          ── step 1 ──          ── step 2 ──


n = 6, s ≈ 0  (1 step → fully parallel):

           ┌── WS_0 ──┐
           ├── WS_1 ──┤
Inv ───────┼── WS_2 ──┼─── Out
           ├── WS_3 ──┤
           ├── WS_4 ──┤
           └── WS_5 ──┘
           ── step 0 ──
```

Nodes are placed one per step first (guaranteeing every step is non-empty), then any remaining nodes are distributed across steps by uniform random sampling.

**Production rate**  
Every workstation is assigned the same production rate, derived as:

```
production_rate = p_steps / n
```

This ensures the theoretical throughput of the whole factory is normalised to 1 unit per tick regardless of topology. A more serial factory has fewer, faster stations; a more parallel factory has more, slower ones.

### Parameters

| Parameter | Description |
|---|---|
| `n` | Total number of workstations in the factory |
| `s` | Seriality — controls the fraction of workstations that form their own production step. `s = 1` is fully serial; `s = 0` is fully parallel |
| `failure_rate` | Probability per tick that a working machine fails and produces nothing that tick |
| `buffer_size` | Maximum units that can be held in the buffer between any two consecutive production steps |

---

## Simulate

**Script:** `simulate.py`  
**Dependency:** `pip install numpy python-igraph`  
**Run:** called automatically by `run.py`

The simulator takes the graph produced by the generator and advances production tick by tick. Unlike the BOM-based models, there are no orders, no setup phases, and no cost tracking — the simulation purely models continuous material flow and machine state.

### What it does

**Continuous flow**  
At each tick every workstation tries to produce one batch of units. Its output is deposited directly into the buffer of one downstream workstation (the one with the least-occupied buffer), and its input is drawn from its own buffer. Workstations in the first production step draw from an infinite supply of raw material and are never starved. Workstations in the last step deposit finished product out of the factory (no buffer limit at the exit).

**Machine states**  
Each tick, every workstation is classified into one of three states before production is attempted:

- **Working** — the workstation has material available and at least one downstream buffer has space. It produces normally.
- **Starved** — the workstation's own buffer is empty; it cannot produce.
- **Blocked** — all downstream buffers are full; there is nowhere to put the output. The workstation skips production this tick.

Nodes are evaluated in topological order so that upstream production decisions are visible to downstream nodes within the same tick.

**Failures**  
Each working machine has a `failure_rate` probability of failing per tick. When a failure occurs the workstation skips production for that tick (but is not reclassified — it retains its *working* state label and simply produces zero units).

**Tick loop**  
Each call to `iterate()` performs one tick:

1. Classify every workstation as working, starved, or blocked.
2. For each working workstation, attempt production:
   - Cap output by available input buffer stock.
   - Cap output by available space in downstream buffers.
   - Apply a random failure check — if the machine fails, produce nothing.
   - Deduct consumed input from the workstation's own buffer.
   - Deposit output into the downstream buffer with the most available space.
3. Record state counts (starved / blocked / working) and total production for this tick.

---

## Run

**Script:** `run.py`  
**Dependencies:** `pip install numpy python-igraph`  
**Run:** `python run.py`

`run.py` wires the generator and simulator together and writes results to `sim_output/`. Edit the parameter block at the top of the file to change the factory configuration.

### Parameters

| Parameter | Description |
|---|---|
| `N` | Total number of workstations |
| `S` | Seriality (`0.0` = fully parallel, `1.0` = fully serial) |
| `FAILURE_RATE` | Probability per tick that a working machine fails |
| `BUFFER_SIZE` | Buffer capacity between production steps |
| `N_TICKS` | Number of simulation ticks to run |
| `SEED` | Random seed for reproducibility (`None` for non-reproducible) |

### Output files

| File | Contents |
|---|---|
| `sim_output/states.csv` | Per-tick counts of workstations in each state and total units produced |

`states.csv` columns:

| Column | Description |
|---|---|
| `Tick` | Simulation tick number |
| `Starved` | Number of workstations starved this tick |
| `Blocked` | Number of workstations blocked this tick |
| `Working` | Number of workstations working this tick |
| `TotalProduction` | Units of finished product produced this tick |

---

## Visualize

**Script:** `visualize_sim.py`  
**Run:** `python visualize_sim.py`

Reads `sim_output/states.csv` and displays the core CLEMATIS output chart:

**Machine State % over Ticks** — for every tick, the percentage of all workstations in the Working, Starved, and Blocked states. Faint raw lines show the per-tick values; bold lines show a 20-tick rolling average. This chart is the primary diagnostic tool in the CLEMATIS framework and directly shows how the balance between starvation and blocking evolves over time.

---

## Model Limitations

### No production orders or BOM
The model has no concept of orders, due dates, lead times, or a bill of materials. It simulates pure flow — one homogeneous material type moves through all steps. It therefore cannot represent multi-product factories, component assembly, or any scheduling decisions.

### No setup times or costs
Workstations switch between tasks instantaneously and at no cost. There are no changeovers and no cost tracking of any kind.

### Simplified failure model
The failure model is a Bernoulli trial each tick: a working machine either produces normally or produces nothing. There is no repair time, no MTTR, and no Weibull age-based failure distribution. A failed machine recovers automatically on the next tick.

### Homogeneous workstations
All workstations in the factory share the same failure rate, buffer size, and production rate (up to the normalisation by step count). There is no way to model bottleneck stations, specialised machines, or heterogeneous capacity.

### No stochastic processing times
Production per tick is deterministic — each working machine always produces exactly `production_rate` units. Real machines have variability in cycle time; that is absent here.

### Infinite supply and demand
Raw materials are always available and finished products are always accepted. The model cannot represent supply disruptions, demand constraints, or inventory holding costs.
