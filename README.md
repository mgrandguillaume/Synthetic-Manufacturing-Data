# Synthetic Factory Data Generator

## Table of Contents

1. [Overview](#overview)
2. [Repository Layout](#repository-layout)
3. [Model Progression](#model-progression)
4. [How to Run](#how-to-run)
5. [Dependencies](#dependencies)

---

## Overview

### Foundation

This project builds on the work of
[Lopes et al. (2024)](https://doi.org/10.1080/0951192X.2024.2322981),
who proposed a two-component framework for synthetic manufacturing
data generation:

- **MN-RM** (Manufacturing Network Random Model): a random graph
  generation algorithm that represents production lines as networks
  of machines and production steps.
- **CLEMATIS** (Complex Manufacturing Throughput Simulation): a
  simulation strategy that generates machine state data and event
  logs from those networks.

The original implementation can be found
[here](https://github.com/Victorf-lopes/clematis/blob/main/src/clematis/model_generator_ns.py#L25).

### This Project

This project extends the CLEMATIS framework in two key ways. First,
it moves from a topology-driven to a **product-driven** approach,
where the factory layout and machine configurations are derived from
the requirements of a defined product or product family. Second, it
introduces **heterogeneous machine parameters** drawn from realistic
probability distributions, replacing the assumption that all machines
in the network are identical.

The goal is to produce synthetic factory data that is more
representative of the diversity of real manufacturing systems,
and more useful for researchers benchmarking optimization and
simulation models.

---

## Repository Layout

```
src/
└── models/
    ├── 2026-04-25_lopes_model/        # Baseline CLEMATIS implementation
    │   ├── model_generator.py         # Original MN-RM graph generator (Lopes et al.)
    │   ├── dynamic_manufacturing.py   # Original CLEMATIS DTS simulator (Lopes et al.)
    │   ├── run.py                     # Wires generator → simulator → CSV output
    │   ├── visualize_sim.py           # Machine state % chart
    │   └── sim_output/
    │       └── states.csv
    │
    ├── 2026-04-27_rafael_model/       # Julia reimplementation of the generator
    │   ├── generate.jl
    │   ├── config.yaml
    │   └── output/
    │
    ├── 2026-04-28_python_model/       # Python BOM-based product-driven model
    │   ├── config.yaml
    │   ├── run.py
    │   ├── generate/
    │   ├── simulate/
    │   ├── sweep/
    │   └── theme.py
    │
    ├── 2026-04-29_alpha_model/        # Stage-based layout with α parameter
    │   ├── config.yaml
    │   ├── run.py
    │   ├── generate/
    │   ├── simulate/
    │   ├── sweep/
    │   └── theme.py
    │
    ├── 2026-05-13_optimized_model/    # NumPy + Numba JIT performance model
    │   ├── config.yaml
    │   ├── run.py
    │   ├── generate/
    │   ├── simulate/
    │   └── sweep/
    │
    ├── 2026-05-15_failure_rate/       # Weibull machine failure model
    │   ├── config.yaml
    │   ├── run.py
    │   ├── generate/
    │   ├── simulate/
    │   └── sweep/
    │
    └── 2026-05-18_validation_model/   # Validation suite
        ├── config.yaml
        ├── run.py
        ├── generate/
        ├── simulate/
        ├── sweep/
        └── validate/
```

---

## Model Progression

| Date | Model | What it introduced |
|---|---|---|
| 2026-04-25 | `lopes_model` | Baseline CLEMATIS implementation. Random DAG generator (MN-RM) and discrete-time simulator producing starved / blocked / working state logs. Pure continuous flow, no BOM or orders. |
| 2026-04-27 | `rafael_model` | Julia reimplementation of the MN-RM generator. Same graph structure, different language and runtime. |
| 2026-04-28 | `python_model` | Full Python rewrite with a **product-driven** approach. Introduces a Bill of Materials (BOM), workstation configurations (processing time, setup time, costs), and a parallel or linear layout topology. Adds parameter sweep and visualizations. |
| 2026-04-29 | `alpha_model` | Replaces the binary parallel/linear topology with a continuous **α parameter** (α = depth / workstation count) that produces a spectrum of stage-based layouts between fully parallel and fully serial. |
| 2026-05-13 | `optimized_model` | Performance rewrite using **NumPy vectorization** and **Numba JIT compilation** (@njit). Enables large-scale sweeps that would be too slow in pure Python. |
| 2026-05-15 | `failure_rate` | Adds a **Weibull failure model** with shape and scale parameters, replacing the simple Bernoulli trial. Machines now have age-dependent failure probabilities and explicit repair/downtime cycles. |
| 2026-05-18 | `validation_model` | Adds a dedicated **validation suite** with four test categories: conservation checks (units in = units out), boundary condition tests (zero machines, zero ticks), monotonicity tests (more machines → more throughput), and statistical distribution checks. |

---

## How to Run

Each model is self-contained. Navigate to the model directory and run `run.py` — it generates factory data, runs the simulation, writes output CSVs, and opens visualizations.

```bash
# Example: run the alpha model
uv run src/models/2026-04-29_alpha_model/run.py
```

To run a parameter sweep (where available):

```bash
uv run src/models/2026-04-29_alpha_model/sweep/sweep.py
```

See each model's `README.md` for the full list of parameters and output files.

---

## Dependencies

### Python models (all except `rafael_model`)

Managed via `pyproject.toml` and a `.venv` created by [uv](https://github.com/astral-sh/uv):

| Package | Use |
|---|---|
| `numpy` | Array operations and vectorized simulation |
| `numba` | JIT compilation for the optimized and later models |
| `pandas` | CSV I/O and data manipulation |
| `plotly` | Interactive visualizations |
| `pyyaml` | Config file parsing |
| `python-igraph` | Graph structure required by the CLEMATIS simulator |

Install everything with:

```bash
uv sync
```

### Julia model (`rafael_model`)

Requires a Julia installation. No additional packages beyond the standard library are needed — run directly with:

```bash
julia src/models/2026-04-27_rafael_model/generate.jl
```

