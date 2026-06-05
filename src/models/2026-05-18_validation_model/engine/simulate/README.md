# engine/simulate

Runs a discrete-time simulation of production orders through a factory built by
`engine/generate`.  Uses a Numba-compiled tick loop for speed, with optional
Weibull-distributed machine failures.

---

## Files

| File | Purpose |
|---|---|
| `tick_loop.py` | State codes, Numba helpers, and the compiled tick loop |
| `preprocess.py` | Converts factory objects into NumPy arrays for the tick loop |
| `postprocess.py` | Converts tick-loop output arrays back into DataFrames |
| `simulate.py` | Public API and script entry point |

---

## Overall flow

```
simulate()
    │
    ├─ preprocess()          Python objects  →  NumPy arrays
    │
    ├─ _numba_tick_loop()    Compiled tick loop (machine code)
    │
    └─ postprocess()         NumPy arrays  →  DataFrames
```

---

## Processing model — unit-rate (one unit per job)

The simulator uses a **unit-rate processing model**: every machine job processes
exactly **one unit** of the target component, regardless of how many units the
order ultimately requires.  This is the central design decision of the model.

### Why not a batch model?

The straightforward alternative is a *batch model*: BOM explosion says an order
needs 540 × COMP_L1_1, so one demand is created for `qty = 540`, one machine job
runs for `proc_time × 540` hours, and all 540 units are deposited at once when
the job finishes.

This creates an immediate problem: a `buffer_capacity = 10` cannot hold 540 units,
so every job that tries to deposit its batch instantly goes BLOCKED and can never
complete — 0 throughput.  The only "fix" would be to auto-scale the buffer
capacity up to the batch size, which defeats the purpose of having a capacity
constraint.

### The unit-rate model

In the unit-rate model:

- BOM explosion still determines the **total units needed** per component
  (`demand_qty`).  This is preserved for reporting.
- A separate counter, `demand_remaining`, starts at `demand_qty` and counts
  down by 1 each time a unit is successfully deposited into the output buffer.
- Each machine job processes **exactly 1 unit** (`ws_job_qty` is always 1).
  The job duration is `proc_time_m[wi, ci]` — the time to make one unit.
- When the job finishes:
  - If the output buffer has space (`stock + 1 <= buffer_capacity`):
    deposit 1 unit (`stock += 1`), decrement `demand_remaining`.
    - If `demand_remaining` reaches 0, the demand is marked fulfilled.
    - Otherwise, the demand is released back to the queue
      (`demand_assigned = False`) so any capable workstation can pick up the
      next unit on the next tick.
  - If the buffer is full: the workstation goes **BLOCKED** and retries every
    tick until space is available.

### Pipeline parallelism

Because units enter the buffer one at a time, a downstream workstation can begin
consuming a component type **as soon as the first unit arrives**, rather than
waiting for the entire quantity to be produced.  For example:

```
WS_1 produces COMP_L1_1:    ●  ●  ●  ●  ●  ●  ...   (1 unit / proc_time hours)
WS_2 consumes COMP_L1_1:       ○  ○  ○  ○  ○  ...   (starts after 1st unit)
```

This pipeline overlap dramatically reduces lead time for multi-level BOMs
compared with a batch model that forces each level to complete entirely before
the next can start.

### buffer_capacity as a real constraint

`buffer_capacity` is the maximum number of intermediate units any buffer may
hold.  It is enforced by the BLOCKED state: a workstation that finishes a unit
but cannot deposit it stalls until space opens (i.e., until downstream
consumption frees a slot).  There is no auto-scaling of any kind.

Tuning guidance:
- **Too small** (e.g. 1): workstations block frequently; throughput drops.
- **Too large** (e.g. 10 000): buffers never fill; no blocking; higher WIP.
- A good starting point is 10–50 units.  The UI default is 20.

---

## Scheduling and deadlock prevention

### Assignment order

The scheduler (phase 4 of the tick loop) processes demands in BOM-level order —
lowest levels first.  This ensures raw inputs are produced before the assemblies
that need them.  Within a level, demands are scanned in creation order.  For
each eligible demand, the scheduler picks the **fastest eligible workstation**
(minimum setup time + processing time for one unit).

### Buffer-full guard (deadlock prevention)

Without a guard, a pathological deadlock can arise with complex multi-input BOMs
and a single workstation covering many components at the same BOM level:

1. WS_1 is the only level-1 workstation and is capable of producing all 30
   COMP_L1 variants.
2. The scheduler assigns WS_1 to COMP_L1_1 (first in the demand list) and keeps
   re-assigning it after each unit, filling COMP_L1_1's buffer to capacity.
3. WS_1 then goes BLOCKED (buffer full).
4. Level-2 workstations are STARVED: they need both COMP_L1_1 *and* COMP_L1_3,
   but COMP_L1_3 stock is 0 (WS_1 never made any).
5. COMP_L1_1 buffer stays full (nobody can consume it) and WS_1 stays BLOCKED —
   a permanent deadlock, 0 throughput.

The fix is simple: **if the output buffer for a demand is already at capacity,
skip that demand in the assignment phase**.

```python
if not is_product[ci] and stock[ci] >= buffer_capacity:
    continue   # buffer full — try the next demand
```

Effect: once COMP_L1_1's buffer is full, the scheduler skips it and assigns
WS_1 to the next COMP_L1 demand (e.g. COMP_L1_3).  WS_1 naturally rotates
across all 30 component types until each buffer contains some stock.  Level-2
workstations can then start as soon as all their required inputs have at least
the BOM-required quantity in stock.

This guard is in phase 4 of `_numba_tick_loop` (see `tick_loop.py`, section
labelled "Buffer-full guard (deadlock prevention)").

---

## tick_loop.py — state codes and compiled loop

### Workstation states

At every tick, each production workstation is in exactly one of six states:

| Code | Name | Meaning |
|---|---|---|
| 0 | `idle` | No job assigned and no pending demand |
| 1 | `setup` | Running a changeover before starting a new job |
| 2 | `processing` | Actively producing one unit |
| 3 | `blocked` | Unit finished but the output buffer is full |
| 4 | `starved` | Capable of work but BOM inputs not yet in stock |
| 5 | `failed` | Down for repair |

### Eight-phase tick structure

Each tick executes these phases in order:

**Phase 0 — Failures and repairs**
Each workstation accumulates age only during `setup` or `processing` states
(not while idle, starved, or blocked).  When accumulated age reaches the
workstation's pre-sampled time-to-failure (TTF), the machine enters `failed`.
Any in-progress job has its consumed inputs returned to stock and its demand
released back to the queue.  A repair timer is started (sampled uniformly from
`[mttr_min, mttr_max]`).  When the timer expires, the machine returns to `idle`,
age resets to 0, and a fresh TTF is drawn from `Weibull(beta, lambda)`.

**Phase 1 — Release orders**
Every `order_interarrival` ticks, one new production order is released (up to
`n_orders` total).  The BOM explosion table (pre-computed in `preprocess.py`)
is read to create one demand record per required component.  Each demand stores:
`demand_comp`, `demand_level`, `demand_qty` (total), `demand_remaining` (units
left), `demand_order`, `demand_created` (tick).

**Phase 2 — Advance in-progress jobs**
Each workstation in `setup` or `processing` decrements its tick counter by 1.
When the counter reaches 0:

- *Setup completing*: transition to `processing`, set counter to
  `proc_time_m[wi, ci]` in ticks, record setup cost.
- *Processing completing (one unit done)*:
  - **Product component** (`is_product=True`): deposit to QI unconditionally
    (no buffer constraint on finished goods).  Decrement `demand_remaining`.
    If it reaches 0, log throughput.  Otherwise release demand for re-pickup.
  - **Intermediate component**: try to deposit into the buffer.
    - Buffer has space (`stock + 1 <= buffer_capacity`): deposit, record
      operating cost, decrement `demand_remaining`, release demand if not done.
    - Buffer full: go `blocked` — unit held in "machine output hopper".

**Phase 3 — Retry blocked workstations**
Every BLOCKED workstation attempts to deposit its held unit again.  If a
downstream workstation consumed from the buffer in the same tick, the slot may
now be available.  On success: deposit, decrement remaining, release demand
if more units needed, go `idle`.

**Phase 4 — Assign idle workstations**
Demands are scanned lowest BOM level first.  For each eligible demand, the
scheduler picks the fastest `idle`/`starved` capable workstation.

Eligibility checks (in order, all must pass):
1. `demand_assigned` is False and `demand_fulfilled` is False.
2. `demand_remaining > 0`.
3. BOM level matches the current scan level.
4. **Buffer-full guard**: `stock[ci] < buffer_capacity` (or it is a product).
5. All BOM inputs present in stock for one unit (`_inputs_ok`).

On assignment: BOM inputs for 1 unit are deducted from stock immediately,
transport cost is recorded, `ws_job_qty = 1`, and the workstation begins
`setup` (or skips to `processing` if no changeover needed).

**Phase 5 — Classify starved workstations**
Any `idle` workstation capable of a pending-but-unstarted demand, where the
demand's inputs are not yet in stock, is reclassified as `starved`.

**Phase 6 — Log workstation states**
`state_log[tick, wi]` is written for every workstation.

**Phase 7 — Log buffer levels (optional)**
If `log_buffers=True`, `buf_log[tick, ci]` is written for every component.

**Phase 8 — Early exit**
The loop exits as soon as `orders_done >= n_orders`, before reaching `n_ticks`.

---

## preprocess.py — Python objects to NumPy

Takes the dict returned by `generate.py` and produces all arrays the tick loop
needs.  Key transformations:

**Index maps** — component IDs and workstation IDs become contiguous integer
indices, enabling plain array lookups instead of hash maps inside Numba.

**BOM in CSR format** — the bill-of-materials is stored as a Compressed Sparse
Row matrix (`bom_ptr`, `bom_inputs`, `bom_qtys`).  For a given output component
`ci`, its input components and quantities are at
`bom_inputs[bom_ptr[ci] : bom_ptr[ci+1]]`.  This allows the Numba loop to check
input availability with a tight inner loop and zero Python overhead.

During CSR construction, duplicate `(parent, child)` edges — which can arise
when `sharing_ratio > 0` if the generator picks the same component twice for
the same parent — are **aggregated by summing their quantities** into a single
edge.  Without this, `_inputs_ok` would check each edge independently (passing
if `stock ≥ qty` per edge) while Phase 4 would decrement stock for every edge,
consuming more than was actually available and causing buffer stock to go
negative.

**BOM explosion** — for each product, the full set of component demands generated
by one order is pre-computed (`expl_comps`, `expl_qtys`, `expl_n`).  When an
order is released in the tick loop, the loop simply reads from this table rather
than traversing the BOM tree at runtime.

**Demand queue arrays** — all demand arrays (`demand_comp`, `demand_level`,
`demand_qty`, `demand_remaining`, `demand_order`, `demand_created`,
`demand_assigned`, `demand_fulfilled`) are pre-allocated for the maximum possible
number of demands (`n_orders × max_comps_per_order + 16`).  The tick loop fills
them by index as orders are released.

**Weibull parameters** — if failures are enabled, per-workstation `ws_beta` and
`ws_lambda` are sampled from the configured ranges and the initial `ws_ttf`
(time-to-failure in ticks) is drawn before the loop starts.  Raw materials
(level 0) have stock initialised to `_INF = 10_000_000`.

**Output arrays** — `state_log`, `tp_log`, `buf_log`, and cost accumulators are
allocated here and passed into the tick loop as writable arrays.

---

## postprocess.py — NumPy arrays to DataFrames

Reads the output arrays written by the tick loop and constructs five DataFrames:

| Key | Content |
|---|---|
| `states` | One row per (tick, workstation): tick index, simulated time (h), and state name |
| `utilization` | One row per workstation: total hours and percentage in each of the 6 states, plus Factory Physics metrics (see below) |
| `throughput` | One row per completed order: completion time, order number, product ID, lead time |
| `costs` | One row per workstation: setup, operating, transport, and repair costs |
| `buffers` | One row per (tick, component): stock level over time (empty if `log_buffers=False`) |

`utilization` always includes `Failed` and `FailedPct` columns (zero when
failures are disabled).  `costs` always includes a `RepairCost` column.

---

## Factory Physics metrics in the utilization output

> **Primary source:** Hopp, W. J., & Spearman, M. L. (2008). *Factory Physics*
> (3rd ed.). Waveland Press. Chapters 7 and 8.
>
> The MTBF formula comes from standard Weibull distribution theory, not from
> Hopp & Spearman directly (see note below).

The `utilization` DataFrame includes four additional columns derived analytically
from the sampled Weibull failure parameters.  These are *theoretical* predictions
computed before any simulation result is needed; they can therefore be used to
reason about the factory's expected behaviour before or after running the
simulation.

### MTBF — Mean time between failures

For a workstation whose failure inter-arrival times follow a Weibull distribution
with shape parameter **β** and scale parameter **λ** (hours), the mean time
between failures is:

```
MTBF = λ · Γ(1 + 1/β)
```

where Γ is the standard gamma function.

> **⚠ Citation note:** This formula is the expectation of the Weibull
> distribution — standard probability theory.  Hopp & Spearman (Ch. 8) use a
> generic symbol *m₀* for mean time between failures without specifying the
> underlying failure distribution or this formula.  The Weibull parameterisation
> is a model design choice, not a prescription from the book.

| Column | Type | Meaning |
|---|---|---|
| `MTBF_h` | float or None | Theoretical MTBF in hours; `None` when failures are disabled |

The values of `ws_lambda` and `ws_beta` used here are the per-workstation
samples drawn in `preprocess.py` from the configured ranges — so each
workstation gets its own MTBF.

### Availability

The long-run fraction of time a workstation is operational (not under repair).
Following Hopp & Spearman (Ch. 8), where *m₀* = mean time between failures and
*mᵣ* = mean repair time:

```
A = m₀ / (m₀ + mᵣ)   →   A = MTBF / (MTBF + MTTR_mean)
```

> **Model adaptation:** Hopp & Spearman use generic *mᵣ* (mean repair time).
> Because the configuration specifies a repair-time range `[mttr_min, mttr_max]`,
> this model uses `MTTR_mean = (mttr_min + mttr_max) / 2` as *mᵣ*.  This is a
> practical approximation; the book does not specify a particular repair-time
> distribution.

| Column | Type | Meaning |
|---|---|---|
| `Availability` | float [0, 1] | Theoretical long-run uptime fraction; 1.0 when failures are disabled |

A value of 0.80 means the machine is expected to be operational 80 % of the
time; it spends 20 % under repair on average.

### Effective process time — Hopp & Spearman Equation 8.2

Machine failures inflate the time to produce each unit beyond the natural
(failure-free) processing time **t₀**.  Hopp & Spearman (Eq. 8.2) give the
**effective process time**:

```
t_e = t₀ / A
```

A workstation with `A = 0.80` takes on average 25 % longer to produce each
unit than a fully reliable machine, because it is unavailable 20 % of the time.
This relationship holds regardless of whether failures occur during a job or
between jobs — the availability penalty applies uniformly over the long run.

| Column | Type | Meaning |
|---|---|---|
| `t_e_h` | float | Effective process time per unit (hours), including availability penalty |

`t₀` is the mean processing time averaged over all components the workstation
is capable of making (mean over all capable `(workstation, component)` pairs
from the configuration matrix).  When failures are disabled, `t_e_h = t₀`.

The simulation already realises `t_e` implicitly: when a machine fails mid-job,
the job stalls until repair is complete, naturally inflating the wall-clock time
per unit.  Reporting `t_e_h` makes this effect explicit and comparable across
workstations without needing to observe many simulation runs.

### Predicted bottleneck

The **bottleneck** is the workstation that limits the factory's maximum
throughput.  Hopp & Spearman (Ch. 7) define it as the workstation with the
highest utilization:

```
u = r / r_e,   where r_e = m / t_e   (effective capacity rate)
```

For a fixed demand rate *r*, the station with the highest `t_e` has the lowest
`r_e` and therefore the highest utilization — making it the bottleneck.

| Column | Type | Meaning |
|---|---|---|
| `IsPredictedBottleneck` | bool | `True` for the one workstation with the highest `t_e_h` |

> **Multi-product note:** In a multi-product BOM factory the demand rate *r*
> differs per workstation (depending on which products it serves), so the true
> bottleneck also depends on BOM structure and product mix.  The prediction here
> (highest `t_e`) is an approximation valid for single-product serial lines and
> a useful heuristic otherwise.  Compare `IsPredictedBottleneck` against the
> empirically highest `BusyPct` after a simulation run to assess accuracy.

### Example interpretation

```
Workstation  t0_h  MTBF_h  A      t_e_h   IsPredictedBottleneck
WS_1         1.20  45.3    0.90   1.33    False
WS_3         0.95  18.7    0.79   1.20    False
WS_7         1.05  22.1    0.82   1.28    True    ← predicted bottleneck
```

WS_7 has a lower natural processing time than WS_1, but its lower availability
(A = 0.82 vs 0.90) inflates its effective rate enough to make it the binding
constraint.

---

## simulate.py — public API

```python
simulate(
    gen_result,
    n_orders           = 10,
    tick_duration      = 0.05,      # simulated hours per tick
    buffer_capacity    = 20,        # max units in any intermediate buffer
    order_interarrival = 10,        # ticks between successive order releases
    n_ticks            = 3000,      # hard upper bound on simulation length
    log_buffers        = True,
    failures_enabled   = False,
    weibull_beta_range   = [2.0,   2.0],
    weibull_lambda_range = [100.0, 100.0],
    mttr_range           = [1.0,   1.0],
    repair_cost_range    = [0.0,   0.0],
    seed               = None,
) -> dict[str, pd.DataFrame]
```

Sets default values for optional failure parameters, calls
`preprocess` → `_numba_tick_loop` → `postprocess`, and returns the
five-DataFrame result dict.

### Sizing n_ticks

`n_ticks × tick_duration` = total simulated hours.  For a factory with BOM
depth D and branching factor B at each level, a single order may require on the
order of `B^D` component units.  Each unit takes roughly `proc_time / tick_duration`
ticks to produce.  A rough lower bound for `n_ticks` is:

```
n_ticks > n_orders × (B^D × proc_time) / tick_duration
```

Example: depth=5, B=2, proc_time=2.9 h, tick_duration=0.05 h, n_orders=10:
```
n_ticks > 10 × (32 × 2.9) / 0.05  ≈  185 000
```

When in doubt, run with `n_orders=1` first and check `throughput["Time"].max()`
to gauge the required horizon.

---

## Numba compilation notes

`_numba_tick_loop` is decorated with `@numba.njit(cache=True)`.  On the first
call with a given Python environment, Numba compiles the function to machine
code and caches the result in `__pycache__`.  Subsequent calls load from cache
and execute immediately.

- If you change the **function signature** (add/remove/reorder parameters), the
  cache is invalidated automatically and recompilation occurs.
- If you see stale behaviour after a code change, delete `__pycache__` in the
  `engine/simulate/` directory and let it recompile.
- Compilation takes 5–20 seconds on first call; cached runs are effectively
  instant (the loop itself runs in milliseconds to seconds depending on
  `n_ticks`).
