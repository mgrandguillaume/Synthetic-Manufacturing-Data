# Synthetic Factory Data Generator

## Foundation

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

## This Project

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


## Development

### Possible additions to the model
Generation
- Add intermediate topology (in between parallel and series)
- Add a 'broken machine' function / failure rate / downtime
- Add the fact that new machines are more efficient
- Buffer capacity
- Failure rates

Simulation
- How the 

Input
- Give a standard distribution per input variable, less user overwrite this with a constant value if inputted

---

### Validation

The following validation approaches are recommended to verify that the simulation is behaving correctly. They are grouped from most mechanical (exact, deterministic) to most analytical (statistical, theoretical).

#### 1. Conservation laws — exact, should never fail

These properties must hold by construction. A violation indicates a bug in the simulation logic.

- **Time balance:** for every workstation, the sum of hours spent in all states (`busy + setup + blocked + starved + idle + failed`) must equal exactly `actual_ticks × tick_duration`. Verifiable directly from `utilization.csv`.
- **Material balance:** total units consumed from BOM edges + units remaining in buffers + units shipped to QI must equal the total units demanded across all released orders.
- **Cost identity:** summing all cost columns across all workstations in `costs.csv` must equal any independently computed total cost figure.

#### 2. Boundary / degenerate cases — unit tests

Run the simulation with extreme inputs where the correct output is known in advance:

| Input | Expected behaviour |
|---|---|
| `n_orders = 0` | Simulation ends at tick 0; all output DataFrames are empty or zero-row |
| `depth = 1`, `workstations_count = 1`, `n_products = 1` | No blocking possible; makespan ≈ n_orders × (setup_time + processing_time × qty) |
| `failures_enabled = true`, `weibull_lambda` very large (e.g. 1 000 000 h) | Results should be numerically identical to `failures_enabled = false` |
| `buffer_capacity` very large | `BlockedPct` should be zero for all workstations |
| `sharing_ratio = 1.0` | Only one component exists per BOM level; component count in `gen_stats.csv` should equal `depth` |

#### 3. Monotonicity — direction of effect

These properties will not hold for every individual run due to randomness, but should hold clearly when averaged across many runs. Any consistent violation is a red flag.

- **More workstations → shorter or equal makespan.** Adding capacity cannot make throughput worse.
- **Larger buffer capacity → shorter or equal makespan.** More buffer space can only reduce blocking.
- **Larger `weibull_lambda` → lower `FailedPct`.** A longer characteristic life means fewer failures per simulated hour.
- **Larger `n_orders` → longer makespan.** More work takes more time.

These are directly testable from existing sweep output by plotting each relationship and checking the direction of the trend.

#### 4. Weibull failure — statistical tests

These checks verify that the failure model produces lifetimes that match the intended distribution.

- **Mean failures per workstation** should be approximately `simulation_duration / lambda` (using the mean λ assigned to that workstation). Extract actual failure counts from `states.csv` by counting runs of the `"failed"` state per workstation.
- **Steady-state availability** should be approximately `lambda / (lambda + mttr_mean)`. This is the standard reliability formula. Compare against `1 − FailedPct` from `utilization.csv`.
- **With `weibull_beta = 1` (exponential special case):** inter-failure times (in hours) should pass a Kolmogorov–Smirnov test against `Exponential(lambda)`. Extract failure event timestamps from `states.csv`, compute the gaps between them, and run `scipy.stats.kstest`.

#### 5. Little's Law — theoretical benchmark

Little's Law states `L = λ × W`, where:
- **L** — average number of demand items simultaneously in the system (work-in-progress), estimable from `buffers.csv` as the average total stock across all buffers at each tick
- **λ** — demand arrival rate = `1 / (order_interarrival × tick_duration)` items per hour
- **W** — average lead time per item, from `throughput.csv`

The law should hold approximately. A large systematic deviation suggests unexpected queueing behaviour caused by the scheduler, the buffer layout, or the failure model.

#### 6. Cross-model consistency

Run the `2026-05-15_failure_rate` model with `failures_enabled: false` and the `2026-05-13_optimized_model` with an identical `config.yaml` and the same `seed`. Because both models use the same Numba tick loop without failure logic, every output CSV (`states.csv`, `throughput.csv`, `costs.csv`) should be **bit-for-bit identical**. This confirms that adding the failure extension did not accidentally alter the base simulation.

#### 7. Diagnostic graphs

The following charts are particularly effective at exposing problems quickly:

- **Cumulative orders completed over time** — should be a smooth staircase. A prolonged flat section indicates deadlock or starvation the scheduler cannot resolve.
- **Buffer level over time per component** — should oscillate between 0 and `buffer_capacity`. A buffer that reaches capacity and stays there reveals a persistent blocking cascade upstream.
- **Observed `FailedPct` vs. predicted availability `1 − lambda/(lambda + mttr_mean)`** as a scatter plot across sweep runs — points should lie close to the diagonal. Outliers indicate that the failure timing or repair duration is not being sampled correctly.