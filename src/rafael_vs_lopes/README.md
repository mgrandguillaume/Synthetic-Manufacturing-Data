# Lopes vs Rafael vs Alpha — Model Comparison

This folder contains a single visualisation script that reads existing output
files from three models and produces a side-by-side comparison figure. Its
purpose is to justify why the **Alpha model** is a more realistic representation
of a manufacturing system than either the Lopes or Rafael model alone.

---

## Research context

This comparison is part of a Bachelor End Project (BEP) on synthetic
manufacturing data generation. The goal of the BEP is to produce a data
generator that outputs factory data representative of real manufacturing systems,
which can be used to benchmark optimisation and simulation algorithms.

Two existing approaches were identified in the literature:

| Model | Origin | Approach |
|---|---|---|
| **Lopes** | Lopes et al. (2024) | Topology-driven. Generates a random graph of workstations from two parameters (n nodes, s seriality) and runs a Discrete-Time Simulation that produces machine state logs. |
| **Rafael** | Supervisor-provided | Product-driven. Generates a factory from a Bill of Materials (BOM) — a hierarchical product structure with components, configurations, and a layout. No simulation. |

Both models have strong parts and significant limitations. The **Alpha model**
was developed to combine their strengths into a single, more realistic model.

---

## What each model does well

### Lopes model — strong simulation, weak structure

The Lopes model is built around the CLEMATIS framework, which tracks three
machine states per tick:

- **Working** — the workstation has material and downstream space; it produces.
- **Starved** — the workstation's input buffer is empty; it waits.
- **Blocked** — the workstation finished but all downstream buffers are full; it waits.

The balance between starvation and blocking over time is the central diagnostic
output of the model. This is realistic and useful.

**What it lacks:**
- No Bill of Materials. Every workstation processes one homogeneous material
  type. There are no products, no components, and no assembly structure.
- All workstations are identical. They share the same production rate, failure
  rate, and buffer size.
- No setup times, no changeover costs, no cost tracking of any kind.
- Only two structural parameters: `n` (number of nodes) and `s` (seriality).

### Rafael model — rich structure, no simulation, binary topology

The Rafael model generates a complete factory description from a product
hierarchy:

- A **Bill of Materials** (BOM) tree with configurable depth and branching.
  Components are shared between products via the `sharing_ratio` parameter.
- **Workstation configurations** with per-component processing times, setup
  times, setup costs, and operating costs — making machines heterogeneous.
- A **layout** graph that routes material between workstations.

This structure is much more representative of a real factory than the Lopes
graph. However:

**What it lacks:**
- No simulation. The model generates CSVs but produces no machine state data,
  no throughput, no lead times, and no costs at runtime.
- Binary topology. The layout is either `parallel` (every workstation is
  independent) or `linear` (a single serial chain). Real factories sit
  somewhere in between — a binary switch cannot represent this.

---

## The Alpha model synthesis

The Alpha model inherits the BOM-driven structure from Rafael and replaces the
binary topology choice with a **continuous α parameter**:

```
α = depth / workstations_count
```

- `α → 1` — one workstation per BOM stage; the factory is serial and
  specialised.
- `α → 0` — many workstations per stage; the factory is wide and parallel.
- `0 < α < 1` — any intermediate structure.

This single parameter spans the full spectrum that Rafael's binary switch can
only approximate at its two extremes. The full simulation pipeline (DTS,
machine states, throughput, costs, lead times) runs on top of this richer
structure.

---

## Comparison figure

**Script:** `visualize_comparison.py`  
**Run:** `uv run src/rafael_vs_lopes/visualize_comparison.py`  
**Dependencies:** `pip install pandas plotly`

The figure contains six charts organised into four rows:

| Chart | What it shows |
|---|---|
| ① Lopes — machine state % over ticks | What the Lopes model does well: continuous simulation dynamics with clear starvation/blocking trade-off. The annotation notes what is absent: no BOM, identical machines. |
| ② BOM structural complexity vs depth | How component count grows with BOM depth in the Alpha (and Rafael) model. Lopes is shown as a flat reference line at 1 — it always has exactly one material type regardless of any parameter. |
| ③ Topology coverage by model | Conceptual chart on a 0–1 seriality axis. Lopes can sweep `s` continuously but has no BOM. Rafael has exactly two discrete choices (parallel, linear). Alpha covers the full range with a BOM-driven structure. |
| ④ Alpha — machine state % vs α (depth = 3) | The central argument chart. The full starvation/blocking trade-off curve across the continuous α range. The two dashed lines mark where Rafael's `parallel` and `linear` options sit — the only two points Rafael can represent. |
| ⑤ Alpha — makespan vs α | How total production time changes with topology and BOM depth. Shows that the α parameter produces a rich, smooth response — not just two extreme values. |
| ⑥ Alpha — cost breakdown vs α (depth = 3) | Setup, operating, and transport costs stacked across the α range. This output exists only in the Alpha model — neither Lopes nor Rafael can produce it. |

---

## Data sources

All charts read from pre-existing output files — no simulation is re-run.

| Model | File(s) read |
|---|---|
| Lopes | `2026-04-25_lopes_model/sim_output/states.csv` |
| Rafael | `2026-04-27_rafael_model/output/components.csv`, `bom.csv` |
| Alpha | `2026-04-29_alpha_model/sweep/sweep_output/state_summary.csv`, `gen_stats.csv`, `throughput.csv`, `costs.csv` |

If any file is missing, re-run the corresponding model first:

```bash
# Lopes
uv run src/models/2026-04-25_lopes_model/run.py

# Alpha sweep (Rafael has no simulation to re-run)
uv run src/models/2026-04-29_alpha_model/sweep/sweep.py
```
