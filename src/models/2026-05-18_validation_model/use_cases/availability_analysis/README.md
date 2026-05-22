# Availability Analysis

This use case answers a single question:

> **Given that every production workstation runs under continuous mechanical load, what fraction of time is the factory able to produce every component in its bill of materials?**

This metric is called **steady-state system availability** (A_sys). It is computed in three independent ways and the results are compared to validate the approach.

---

## Table of Contents

1. [How to Run](#1-how-to-run)
2. [Output](#2-output)
3. [Files](#3-files)
4. [How Theoretical Availability is Calculated](#4-how-theoretical-availability-is-calculated)
5. [Methodology — Three Approaches](#5-methodology--three-approaches)
6. [Tunable Parameters](#6-tunable-parameters)
7. [Config.yaml Keys](#7-configyaml-keys)
8. [Understanding the Results](#8-understanding-the-results)

---

## 1. How to Run

From the repository root:

```bash
uv run src/models/2026-05-18_validation_model/use_cases/availability_analysis/availability.py
```

**Expected runtime:** ~5 minutes for 1000 Monte Carlo replications on a typical laptop. The two theoretical calculations complete in under a second.

---

## 2. Output

### Console

A formatted table is printed with three columns:

```
                                  Midpoint   Integrated  Experimental
System availability  A_sys         74.890%     73.214%       71.803%
95% CI (experimental)                  --          --   [71.567%, 72.039%]
Std dev (across runs)                  --          --         3.819%
Verdict (midpoint):   NEAR PASS - 2.84pp outside CI ...
Verdict (integrated): PASS - theoretical within 95% CI
```

Followed by the five weakest components (lowest A_comp), useful for identifying bottlenecks.

### Plotly Figure

Three panels open in the browser:

| Panel | What it shows |
|---|---|
| **(1) Histogram** | Distribution of per-replication system availability across all Monte Carlo runs. Vertical lines mark the experimental mean, 95% CI bounds, and both theoretical values. |
| **(2) Bottleneck chart** | Per-component marginal availability (A_comp), sorted weakest-first. Bars are coloured red (1 producer = single point of failure), amber (2 producers), blue (3+). Horizontal lines mark both theoretical A_sys values. |
| **(3) Timeline** | System up/down state (0 or 1) over time for the last Monte Carlo replication, with a rolling average overlay and both theoretical reference lines. |

---

## 3. Files

| File | Role |
|---|---|
| `availability.py` | Entry point. Orchestrates generation, both theoretical calculations, Monte Carlo, console report, and Plotly figure. Tune runtime constants here. |
| `theoretical.py` | Closed-form availability using **midpoint** Weibull parameters. Uses exact 2^N workstation-state enumeration for the system-level calculation. |
| `theoretical_integrated.py` | Same topology logic, but computes **E[A_ws] via 2-D numerical quadrature** over the full parameter distributions instead of the midpoint. More accurate when parameter ranges are wide. |
| `experimental.py` | Monte Carlo simulation. Samples Weibull failure-repair cycles for every workstation, builds a boolean availability matrix, and measures the fraction of time the system is up. |

---

## 4. How Theoretical Availability is Calculated

The factory is modelled as a **reliability block diagram (RBD)** with two levels: parallel groups in series.

### Step 1 — Per-workstation availability (A_ws)

Each workstation is modelled as a **Weibull** wear-out process. Using the midpoint of the configured ranges (β = 2.25, λ = 35 h, MTTR = 2.25 h):

```
MTTF = λ · Γ(1 + 1/β)
     = 35 · Γ(1.444)
     = 35 · 0.886
     ≈ 31.0 h

A_ws = MTTF / (MTTF + MTTR)
     = 31.0 / (31.0 + 2.25)
     ≈ 93.2%
```

Interpretation: each workstation is operational **93.2%** of the time.

### Step 2 — Per-component availability (parallel OR gate)

A component can be produced as long as **at least one** of its capable workstations is up. The failure of k independent workstations must occur simultaneously for the component to be unavailable:

```
A_comp = 1 - (1 - A_ws)^k
```

| Producers (k) | Calculation | A_comp |
|---|---|---|
| 1 (SPOF) | 1 - (0.068)^1 | **93.2%** |
| 2 | 1 - (0.068)^2 | **99.5%** |
| 6 | 1 - (0.068)^6 | **~100.0%** |

A component with a single producer is a **Single Point of Failure (SPOF)** — the entire system goes down whenever that one workstation fails.

### Step 3 — System availability (series AND gate, exact)

The system is available only when **every** component is simultaneously producible. A naive approach multiplies all A_comp values together:

```
A_sys ≈ A_comp_1 × A_comp_2 × ... × A_comp_N   ← WRONG when workstations are shared
```

This is **incorrect** when the same workstation produces multiple components. For example, if WS_1 is the sole producer for six level-1 components, its failure takes all six down at once — but the product formula counts it as six independent events, heavily underestimating A_sys.

The correct approach enumerates all **2^N workstation states** (up/down combinations) and sums the probability of every state where all components are covered:

```
A_sys = Σ  P(state) · 1[system available in state]
       states

P(state) = A_ws^(# up) · (1 - A_ws)^(# down)
```

For the current factory (14 workstations), this means 2^14 = 16,384 states — computed in milliseconds.

**Concrete example** with the current config (A_ws = 93.2%):

The factory reduces to four independent SPOF constraints (WS_1, WS_2, WS_3, WS_5), one 6-fold parallel group (COMP_L4), and two correlated parallel groups sharing WS_12 (PROD_1 and PROD_2):

```
A_sys = A_ws^4
      × (1 - (1-A_ws)^6)
      × (1 - 2·(1-A_ws)^2 + (1-A_ws)^3)

      = 0.932^4
      × (1 - 0.068^6)
      × (1 - 2·0.068^2 + 0.068^3)

      = 0.755 × ~1.000 × 0.991
      ≈ 74.9%
```

---

## 5. Methodology — Three Approaches

### Midpoint theoretical (`theoretical.py`)

Uses the midpoint of each parameter range as a single representative value (e.g. λ_mid = 35 h). Fast and simple, but introduces a systematic bias when parameter ranges are wide: because A_ws is a **concave function of λ**, the average A_ws over the full range is lower than A_ws at the midpoint (*Jensen's inequality*). The midpoint method therefore tends to **overestimate** A_sys.

### Integrated theoretical (`theoretical_integrated.py`)

Computes the true **E[A_ws]** by numerical quadrature over the full joint distribution of (β, λ, MTTR):

```
E[A_ws] = ∫∫ E_MTTR[ MTTF(β,λ) / (MTTF(β,λ) + MTTR) ] · f(β) · f(λ) dβ dλ
```

The MTTR dimension is solved analytically (log integral), leaving a 500×500 grid evaluation over (β, λ). This corrects the Jensen's inequality bias and produces a result much closer to the Monte Carlo ground truth.

### Experimental Monte Carlo (`experimental.py`)

For each of N replications:
1. Each workstation is assigned its own randomly sampled (β_i, λ_i) from the configured ranges.
2. A failure-repair sequence is simulated: the machine runs until a Weibull-drawn TTF elapses, fails, is repaired after a uniform MTTR, then repeats — for the full horizon.
3. A boolean matrix `ws_failed[workstation, timepoint]` is built on a 5,000-point time grid.
4. The system is up at a timepoint iff every component has at least one non-failed capable workstation.
5. The fraction of up-timepoints = replication availability.

The mean and 95% CI across replications are the experimental estimate. This is the ground truth — it makes no closed-form approximations.

**Key assumption:** machines run at 100% utilisation, i.e. age accumulates continuously. This is the standard assumption for Weibull wear-out analysis. In a real production schedule, idle machines would age more slowly, giving higher observed availability.

---

## 6. Tunable Parameters

All constants are at the top of `availability.py`:

| Constant | Default | Effect |
|---|---|---|
| `N_REPLICATIONS` | 1000 | More replications → narrower CI. 200 ≈ ±0.5pp, 1000 ≈ ±0.24pp. Scales runtime linearly. |
| `HORIZON_HOURS` | 2000 | Simulated hours per replication. Should be >> MTTF so many failure cycles are observed. |
| `WARMUP_HOURS` | 200 | Hours discarded from the start of each replication. Should be ~3–4× MTTF to reach steady state. |
| `N_TIMEPOINTS` | 5000 | Evaluation points per replication. Higher = smoother timeline in panel (3). |
| `SEED` | 42 | RNG seed. Change to get a different (but equally valid) sample. |

---

## 7. Config.yaml Keys

Only the `failures` section affects this analysis:

```yaml
failures:
  enabled:         true           # must be true or the script exits
  weibull_beta:   [1.5,  3.0]    # Weibull shape β — controls wear-out rate
  weibull_lambda: [20,   50]     # Weibull scale λ — characteristic life (hours)
  mttr:           [0.5,  4.0]    # repair duration per failure event (hours)
```

`repair_cost` and the simulation-level failure settings are not used here.

---

## 8. Understanding the Results

### Verdict labels

| Label | Meaning |
|---|---|
| `PASS` | Theoretical value falls inside the experimental 95% CI — excellent agreement. |
| `NEAR PASS` | Within ~3pp of the CI. Expected when parameter ranges are wide (Jensen's inequality). |
| `DIVERGE` | 3–10pp outside CI. Check whether parameter ranges are unusually wide. |
| `FAIL` | >10pp outside CI. Likely a topology mismatch or modelling error. |

### Residual gap between integrated theoretical and experimental

Even after correcting for Jensen's inequality, a small gap (<1pp for typical configs) may remain. This comes from **higher-order variance effects**: within a single replication, workstations have heterogeneous A_ws values (each gets its own sampled β, λ). The exact covariance structure of their joint failure affects A_sys in a way that no single-number E[A_ws] can fully capture. This is not a bug — it is the fundamental limit of a closed-form approach.

### Bottleneck interpretation

The bottleneck chart (panel 2) shows **marginal** per-component availability — how available each component would be in isolation. Components with one producer (red bars) are the weakest links. Adding a second capable workstation to a SPOF component raises its A_comp from ~93% to ~99.5% and can significantly lift A_sys.
