# Availability Analysis

This use case answers a single question:

> **Given that every production workstation runs under continuous mechanical load, what fraction of time is the factory able to produce every component in its bill of materials?**

This metric is called **steady-state system availability** (A_sys). It is computed in two independent ways — theoretical and experimental — and the results are compared to validate the approach.

---

## Table of Contents

1. [How to Run](#1-how-to-run)
2. [Output](#2-output)
3. [Files](#3-files)
4. [How Theoretical Availability is Calculated](#4-how-theoretical-availability-is-calculated)
5. [Methodology — Two Approaches](#5-methodology--two-approaches)
6. [Tunable Parameters](#6-tunable-parameters)
7. [Config.yaml Keys](#7-configyaml-keys)
8. [Understanding the Results](#8-understanding-the-results)

---

## 1. How to Run

**Via the UI (recommended):** open the **Availability** page in the Dash app. Set the number of replications, then click **Run availability analysis**. The simulation horizon and warm-up period are scaled automatically to the configured MTBF — no manual tuning required.

**Standalone:** from the model root:

```bash
python -m analysis.use_cases.availability_analysis.availability
```

**Expected runtime:** ~5 minutes for 1000 Monte Carlo replications on a typical laptop. The theoretical calculation completes in under a second.

---

## 2. Output

### Console

A formatted table is printed with two columns:

```
                                  Integrated  Experimental
System availability  A_sys           73.214%       71.803%
95% CI (experimental)                    --   [71.567%, 72.039%]
Std dev (across runs)                    --         3.819%
Verdict: PASS - theoretical within 95% CI
```

Followed by the five weakest components (lowest A_comp), useful for identifying bottlenecks.

### Plotly Figure

Three panels open in the browser:

| Panel | What it shows |
|---|---|
| **(1) Histogram** | Distribution of per-replication system availability across all Monte Carlo runs. Vertical lines mark the experimental mean, 95% CI bounds, and the theoretical value. |
| **(2) Outage duration distribution** | Histogram of system-down episode lengths (in hours) accumulated across all replications. A dashed line marks the mean outage duration. Shows how long typical failures last and whether the distribution is skewed toward short or long outages. |
| **(3) Monte Carlo convergence** | Cumulative mean A_sys as a function of replication count, with a narrowing 95% CI band and a theoretical reference line. Confirms how many replications are needed for the estimate to stabilise. |

---

## 3. Files

| File | Role |
|---|---|
| `availability.py` | Entry point. Orchestrates generation, theoretical calculation, Monte Carlo, console report, and Plotly figure. Runtime constants are defined here. |
| `theoretical_integrated.py` | Computes **E[A_ws] via 2-D numerical quadrature** over the full (β, λ) distributions with mean MTTR. Used as the single theoretical reference. |
| `experimental.py` | Monte Carlo simulation. Samples Weibull failure-repair cycles, builds a boolean availability matrix, measures system uptime, and records outage durations. |
| `_rbd.py` | Shared RBD solver. Implements exact 2^N workstation-state enumeration (≤22 workstations) and Monte Carlo fallback (>22). |

---

## 4. How Theoretical Availability is Calculated

The factory is modelled as a **reliability block diagram (RBD)** with two levels: parallel groups in series.

### Step 1 — Per-workstation availability (A_ws)

Each workstation is modelled as a **Weibull** wear-out process. The expected availability is computed by integrating over the full (β, λ) distribution with the mean MTTR:

```
MTBF(β, λ) = λ · Γ(1 + 1/β)

A_ws(β, λ) = MTBF(β, λ) / (MTBF(β, λ) + E[MTTR])

E[A_ws] = average of A_ws(β, λ) over a 500×500 grid spanning
          [β_min, β_max] × [λ_min, λ_max]
```

Using E[MTTR] (the mean repair time) in the denominator matches the Monte Carlo, where each machine draws a fresh MTTR per repair event and therefore experiences the mean MTTR over a long horizon.

### Step 2 — Per-component availability (parallel OR gate)

A component can be produced as long as **at least one** of its capable workstations is up:

```
A_comp = 1 - (1 - E[A_ws])^k
```

| Producers (k) | A_comp (example with E[A_ws] = 93.2%) |
|---|---|
| 1 (SPOF) | **93.2%** |
| 2 | **99.5%** |
| 6 | **~100.0%** |

A component with a single producer is a **Single Point of Failure (SPOF)** — the entire system goes down whenever that workstation fails.

### Step 3 — System availability (series AND gate, exact)

The system is available only when **every** component is simultaneously producible. A naive approach would multiply the per-component availabilities:

```
A_sys_naive = A_comp_1 × A_comp_2 × … × A_comp_C
```

This is only correct when every component's availability is statistically independent of every other's — i.e. no workstation is shared across components. In practice this assumption is violated: a single workstation can be assigned to produce multiple components, so when it fails all of those components simultaneously lose a capable producer. The naive product treats each consequence as an independent event, effectively counting the same workstation failure once per component it affects, and therefore **underestimates** system availability.

The correct approach enumerates all **2^N workstation states** and sums the probability of every state where all components are covered:

```
A_sys = Σ  P(state)
       states where system is up

P(state) = E[A_ws]^(# up) · (1 - E[A_ws])^(# down)
```

Because the enumeration works at the workstation level, a shared workstation appears exactly once in each state, and its failure propagates simultaneously to all components that depend on it — correctly capturing the correlation.

For up to 22 workstations this is solved exactly (~4.2 M states, completes in under a second). For larger factories a Monte Carlo fallback with 500,000 samples is used (see `_rbd.py`).

---

## 5. Methodology — Two Approaches

### Integrated theoretical (`theoretical_integrated.py`)

Computes **E[A_ws]** by 2-D numerical quadrature over the full joint distribution of (β, λ) on a 500×500 grid:

```
E[A_ws] = (1/N²) Σ_{i,j}  MTBF(β_i, λ_j) / (MTBF(β_i, λ_j) + E[MTTR])
```

Mean MTTR is used directly in the denominator rather than integrating over the MTTR distribution. This is the physically correct choice: in the Monte Carlo, each machine undergoes many repairs over the horizon, drawing a fresh repair time each time, so the per-machine long-run downtime converges to the mean MTTR. Integrating availability over the MTTR distribution would instead model a machine whose repair time is fixed for its entire lifetime — which is not what the simulation does.

This method produces results that agree closely with the Monte Carlo ground truth.

### Experimental Monte Carlo (`experimental.py`)

For each of N replications:
1. Each workstation is assigned its own randomly sampled (β_i, λ_i) from the configured ranges.
2. A failure-repair sequence is simulated: the machine runs until a Weibull-drawn TTF elapses, fails, is repaired after a uniform MTTR, then repeats — for the full horizon.
3. A boolean matrix `ws_failed[workstation, timepoint]` is built on an adaptive time grid fine enough to resolve the shortest possible repair (at least 5 grid points per minimum MTTR window, minimum 5 000 points).
4. The system is up at a timepoint iff every component has at least one non-failed capable workstation.
5. The fraction of up-timepoints = replication availability. All consecutive system-down episodes are also recorded for the outage duration distribution.

The mean and 95% CI across replications are the experimental estimate. This is the ground truth — it makes no closed-form approximations.

**Key assumption:** machines run at 100% utilisation, i.e. age accumulates continuously. This is the standard assumption for Weibull wear-out analysis. In a real production schedule, idle machines would age more slowly, giving higher observed availability.

---

## 6. Tunable Parameters

**Via the UI:** only **Replications** is exposed — the horizon and warm-up are computed automatically from the MTBF (see below).

**Standalone (`availability.py`):**

| Constant | Default | Effect |
|---|---|---|
| `N_REPLICATIONS` | 1000 | More replications → narrower CI. 200 ≈ ±0.5pp, 1000 ≈ ±0.24pp. Scales runtime linearly. |
| `WARMUP_MTBF_MULT` | 4.0 | Warm-up = this multiplier × MTBF. Discards the initial transient before steady state. |
| `HORIZON_MTBF_MULT` | 50.0 | Measurement window = this multiplier × MTBF after warm-up. Ensures many failure-repair cycles. |
| `POINTS_PER_MIN_MTTR` | 5 | Minimum grid points inside one minimum-MTTR window. Prevents short outages from falling between grid points. |
| `N_TIMEPOINTS_FLOOR` | 5 000 | Minimum number of time-grid points regardless of horizon length. |

The simulation seed is taken from `metadata.seed` in `config.yaml`, so all runs at the same seed are reproducible.

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
| `NEAR PASS` | Within ~3pp of the CI. May indicate a wide parameter range or high replication count making the CI very narrow. |
| `DIVERGE` | 3–10pp outside CI. Check whether parameter ranges are unusually wide. |
| `FAIL` | >10pp outside CI. Likely a topology mismatch or modelling error. |

### Expected agreement between theoretical and experimental

The integrated method uses mean MTTR in the denominator — which matches exactly how the simulation accumulates downtime over many repair events. The remaining difference between the two methods comes only from:

- **Monte Carlo sampling variance** — the experimental result is itself a random estimate with a 95% CI. With 1000 replications the CI half-width is roughly ±0.12pp (at σ ≈ 2pp), so the theoretical value must agree to that level of precision.
- **Per-workstation (β_i, λ_i) heterogeneity** — the Monte Carlo assigns each workstation its own independent draw from the parameter ranges, while the theoretical method computes a single integrated E[A_ws] shared by all workstations. When the factory is large and parameter ranges are wide, this introduces a small discrepancy.

A `PASS` verdict is the expected outcome for most configurations. A `NEAR PASS` with a very narrow CI simply means the two estimates differ by a few tenths of a percentage point — within the expected modelling resolution.

### Outage duration panel

Panel (2) shows the distribution of how long each system-down episode lasts, pooled across all replications. A right-skewed distribution (many short outages, few long ones) is typical when SPOF workstations fail independently. A bimodal distribution can indicate two distinct failure modes — for example, isolated workstation failures (short) versus cascading failures where multiple components lose their sole producer simultaneously (longer).

The mean outage duration and its distribution together with A_sys give a fuller picture of reliability than availability alone: two factories with identical A_sys but different outage duration distributions have very different operational profiles.

### Convergence panel

Panel (3) shows the cumulative mean A_sys as replications accumulate. The CI band narrows as 1/√N. Once the band is stable (flat) and narrow, additional replications add little information. For most configurations 200–500 replications is sufficient; the default of 1000 gives a conservatively tight estimate.
