"""
Experimental (Monte Carlo) steady-state system availability.

Each replication independently simulates continuous Weibull failure-repair
cycles for every production workstation over a long time horizon, then
measures what fraction of steady-state time the factory system is available.

System availability definition
-------------------------------
The system is AVAILABLE at time t if and only if, for every producible
component in the factory, at least one capable workstation is operational
(not in a failed-and-under-repair state) at that time.

This is decoupled from the production scheduling simulation: machines are
assumed to be under continuous mechanical load (100% utilisation), which is
the correct assumption for Weibull wear-out reliability modelling and gives a
fair comparison with the theoretical model.

Implementation
--------------
For efficiency, availability is evaluated on a discrete time grid using NumPy
boolean matrices rather than per-point Python loops:

  ws_failed_matrix[wi, tk] = True  iff  workstation wi is failed at time tk

  comp_down[tk]  = all(ws_failed_matrix[capable_ws, tk])
  system_up[tk]  = not any(comp_down[tk] for any component)

  The grid spacing must be smaller than the shortest possible repair, or brief
  outages can fall entirely between two grid points and availability is
  over-estimated.  The caller (availability.py) sizes n_timepoints from the
  minimum configured MTTR to guarantee this; pass a sufficiently large
  n_timepoints if calling run() directly.

Warm-up
-------
The first `warmup_hours` of each replication are discarded to avoid measuring
the initial transient before the failure-repair process reaches steady state.
A warm-up of 2-3x the expected MTBF is recommended.
"""

import math
from collections import defaultdict

import numpy as np


def run(
    gen_result:      dict,
    failure_cfg:     dict,
    n_replications:  int   = 200,
    horizon_hours:   float = 1_000.0,
    warmup_hours:    float = 100.0,
    n_timepoints:    int   = 5_000,
    seed:            int   = 0,
) -> dict:
    """
    Estimate system availability by Monte Carlo simulation.

    Parameters
    ----------
    gen_result:
        Output of generate_simple_assembly() or generate_from_params().
    failure_cfg:
        The 'failures' section of config.yaml as a dict.  Must contain:
        weibull_beta, weibull_lambda, mttr  (each a [min, max] list).
    n_replications:
        Number of independent Monte Carlo runs.  200 gives a tight 95% CI.
    horizon_hours:
        Total time simulated per replication (hours).  Should be >> MTBF so
        many failure-repair cycles are observed.
    warmup_hours:
        Ticks before this time are excluded from the availability measurement.
        Must be < horizon_hours.
    n_timepoints:
        Number of evenly-spaced evaluation points in [warmup_hours, horizon_hours].
        Higher = smoother estimate; 5 000 is sufficient for most configs.
    seed:
        Base RNG seed for reproducibility.

    Returns
    -------
    dict with keys:
        A_sys_mean      float        mean empirical system availability
        A_sys_std       float        std deviation across replications
        A_sys_ci95      (lo, hi)     95% confidence interval
        A_per_run       list[float]  per-replication availability
        time_grid       np.ndarray   evaluation time points (hours)
        system_up_last  np.ndarray   bool[n_timepoints] — system state in the
                                     last replication (useful for plotting)
        ws_avail_mean   dict         ws_id -> mean empirical availability
    """
    if warmup_hours >= horizon_hours:
        raise ValueError("warmup_hours must be < horizon_hours")

    rng = np.random.default_rng(seed)

    # ── Failure parameter ranges ───────────────────────────────────────────────
    beta_min,  beta_max  = float(failure_cfg["weibull_beta"][0]),   float(failure_cfg["weibull_beta"][1])
    lam_min,   lam_max   = float(failure_cfg["weibull_lambda"][0]), float(failure_cfg["weibull_lambda"][1])
    mttr_min,  mttr_max  = float(failure_cfg["mttr"][0]),           float(failure_cfg["mttr"][1])

    # ── Factory structure ──────────────────────────────────────────────────────
    prod_ws     = [ws for ws in gen_result["workstations"] if ws.type == "production"]
    ws_ids      = [ws.id for ws in prod_ws]
    ws_idx_map  = {ws_id: i for i, ws_id in enumerate(ws_ids)}
    n_ws        = len(ws_ids)

    # component -> list of workstation indices capable of producing it
    comp_to_ws_idx: dict[str, list[int]] = defaultdict(list)
    for cfg in gen_result["configurations"]:
        if cfg.workstation in ws_idx_map:
            comp_to_ws_idx[cfg.component].append(ws_idx_map[cfg.workstation])

    # Producible components with at least one capable workstation
    producible: list[tuple[str, list[int]]] = [
        (c.id, comp_to_ws_idx[c.id])
        for c in gen_result["components"]
        if c.level > 0 and comp_to_ws_idx[c.id]
    ]

    # ── Evaluation time grid (after warm-up) ──────────────────────────────────
    time_grid = np.linspace(warmup_hours, horizon_hours, n_timepoints)

    # ── Monte Carlo loop ───────────────────────────────────────────────────────
    A_per_run:          list[float]       = []
    system_up_last:     np.ndarray | None = None
    ws_up_totals                          = np.zeros(n_ws)
    outage_durations_h: list[float]       = []   # duration of every system-down episode (hours)

    dt_h = float(time_grid[1] - time_grid[0]) if n_timepoints > 1 else 1.0

    for rep in range(n_replications):
        # Sample per-workstation Weibull parameters for this replication.
        betas   = rng.uniform(beta_min,  beta_max,  n_ws)
        lambdas = rng.uniform(lam_min,   lam_max,   n_ws)

        # Simulate failure-repair intervals for every workstation.
        fail_intervals = _simulate_machines(
            betas, lambdas, mttr_min, mttr_max, horizon_hours, rng
        )

        # Build ws_failed_matrix[wi, tk] = True iff ws wi is failed at time_grid[tk].
        # Shape: (n_ws, n_timepoints)
        ws_failed = np.zeros((n_ws, n_timepoints), dtype=np.bool_)
        for wi, intervals in enumerate(fail_intervals):
            for (t_start, t_end) in intervals:
                mask = (time_grid >= t_start) & (time_grid < t_end)
                ws_failed[wi] |= mask

        # System is up at tk iff for every component, at least one capable ws is up.
        system_up = np.ones(n_timepoints, dtype=np.bool_)
        for _comp_id, capable_idx in producible:
            if not capable_idx:
                system_up[:] = False
                break
            comp_down = np.all(ws_failed[capable_idx, :], axis=0)
            system_up &= ~comp_down

        A_rep = float(np.mean(system_up))
        A_per_run.append(A_rep)
        ws_up_totals += 1.0 - np.mean(ws_failed, axis=1)

        # Collect outage durations: find all consecutive runs of False in system_up.
        # prepend/append True so boundary outages are captured correctly.
        padded = np.empty(n_timepoints + 2, dtype=np.int8)
        padded[0]  = 1
        padded[-1] = 1
        padded[1:-1] = system_up.astype(np.int8)
        diff    = np.diff(padded)
        starts  = np.where(diff < 0)[0]   # 1→0 transitions (outage begins)
        ends    = np.where(diff > 0)[0]   # 0→1 transitions (outage ends)
        for s, e in zip(starts, ends):
            outage_durations_h.append((e - s) * dt_h)

        if rep == n_replications - 1:
            system_up_last = system_up

    # ── Summary statistics ─────────────────────────────────────────────────────
    A_arr   = np.array(A_per_run)
    mean_A  = float(np.mean(A_arr))
    std_A   = float(np.std(A_arr, ddof=1))
    ci_half = 1.96 * std_A / math.sqrt(n_replications)

    ws_avail_mean = {
        ws_ids[wi]: float(ws_up_totals[wi] / n_replications)
        for wi in range(n_ws)
    }

    return {
        "A_sys_mean":        mean_A,
        "A_sys_std":         std_A,
        "A_sys_ci95":        (mean_A - ci_half, mean_A + ci_half),
        "A_per_run":         A_per_run,
        "time_grid":         time_grid,
        "system_up_last":    system_up_last,
        "ws_avail_mean":     ws_avail_mean,
        "outage_durations_h": outage_durations_h,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _simulate_machines(
    betas:    np.ndarray,
    lambdas:  np.ndarray,
    mttr_min: float,
    mttr_max: float,
    T:        float,
    rng:      np.random.Generator,
) -> list[list[tuple[float, float]]]:
    """
    Simulate independent Weibull failure-repair sequences for all workstations.

    Returns
    -------
    list of lists of (t_fail, t_repair) pairs, one list per workstation.
    Only intervals within [0, T] are included.
    """
    n_ws = len(betas)
    fail_intervals: list[list[tuple[float, float]]] = [[] for _ in range(n_ws)]

    for wi in range(n_ws):
        t = 0.0
        while t < T:
            # Draw time-to-failure from Weibull(beta_i, lambda_i).
            # NumPy's weibull(a) samples from Weibull with shape a and scale 1;
            # multiplying by lambda gives scale lambda.
            ttf    = float(lambdas[wi]) * float(rng.weibull(float(betas[wi])))
            t_fail = t + ttf
            if t_fail >= T:
                break
            mttr     = rng.uniform(mttr_min, mttr_max)
            t_repair = t_fail + mttr
            fail_intervals[wi].append((t_fail, min(float(t_repair), T)))
            t = float(t_repair)

    return fail_intervals
