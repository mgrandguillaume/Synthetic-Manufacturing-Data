"""
Statistical / theoretical checks.

Tests
-----
1. Little's Law  (L = λ × W)
   Run a simulation with a known arrival rate λ (1/order_interarrival).
   To remove start-up and end-of-run transients, measurement is restricted
   to the middle 80 % of the release horizon (warm-up / drain deletion).
   Over that window, L is computed directly as the time-average number of
   in-flight orders and compared against λ_obs × W̄ within a 5 % relative
   tolerance.  The residual error is a finite-window boundary effect:
   in-flight time crossing the window edges enters the two sides of the
   identity in slightly different proportions.  It is bounded by
   ~W / window_length and vanishes as n_orders grows.

2. Steady-state availability  (A ≈ λ / (λ + MTTR))
   This classical reliability formula is exact when the inter-failure time
   follows an Exponential distribution (Weibull β = 1).
   Configure a run with β = 1, λ = 20 h, MTTR = 4 h → A_theory = 20/24 ≈ 0.833.
   Measure A_observed = mean(1 − FailedPct/100) across all workstations.
   Accept ± 10 percentage-point tolerance to allow for finite-sample noise.
"""

from __future__ import annotations

import os
import sys

# ── Path setup ─────────────────────────────────────────────────────────────────
_MODEL_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, _MODEL_ROOT)

from engine.generate.generate import generate_from_params   # noqa: E402
from engine.simulate.simulate import simulate               # noqa: E402


# ── Base parameters ────────────────────────────────────────────────────────────
_GEN_BASE = {
    "n_products":              1,
    "depth":                   2,
    "workstations_count":      4,
    "sharing_ratio":           0.0,
    "branching":               [2, 2],
    "quantity":                [1, 1],
    "producers_per_component": [2, 2],
    "processing_time":         [0.2, 0.2],
    "setup_time":              [0.5, 0.5],
    "setup_cost":              [100, 100],
    "operating_cost":          [5,   5  ],
    "flow_capacity":           [100, 100],
    "transport_cost":          [1.0, 1.0],
    "seed":                    42,
}


# ── Individual tests ───────────────────────────────────────────────────────────

def _test_littles_law() -> tuple[str, bool, str]:
    """
    Little's Law: L = λ × W.

    L  = average number of orders simultaneously in the system.
    λ  = order arrival rate (1 / order_interarrival in orders / tick,
         converted to orders / hour).
    W  = mean lead time per order (from throughput DataFrame).

    To avoid start-up and end-of-run bias, the comparison uses **warm-up /
    drain deletion** (standard simulation practice): measurement is
    restricted to the middle 80 % of the release horizon — the first and
    last 10 % of orders define the window edges and are excluded.

    Over the window [T_a, T_b]:
        L_direct = (total order in-flight time inside the window) / (T_b − T_a)
        λ_obs    = (orders released inside the window) / (T_b − T_a)
        L_theory = λ_obs × W̄,  W̄ = mean lead time of those orders

    With both transients removed, the residual error is a finite-window
    boundary effect: orders whose [release, completion] interval crosses a
    window edge contribute to L_direct (clipped at the edge) and to W̄
    (full lead time, window orders only) in slightly different proportions.
    The imbalance is bounded by ~W̄ / (T_b − T_a), so we check a 5 %
    relative tolerance.
    """
    n_orders           = 100
    order_interarrival = 5       # ticks between releases
    tick_duration      = 0.05   # hours per tick

    gen    = generate_from_params({**_GEN_BASE, "workstations_count": 4})
    result = simulate(
        gen,
        n_orders           = n_orders,
        tick_duration      = tick_duration,
        buffer_capacity    = 50,
        order_interarrival = order_interarrival,
        n_ticks            = 8000,
        log_buffers        = False,
        failures_enabled   = False,
        seed               = 42,
    )

    tp = result["throughput"]
    if tp.empty or len(tp) < 2:
        return (
            "little_law",
            False,
            "Not enough completed orders to compute Little's Law.",
        )

    # Release time of each order (completion − lead time), in hours
    release_h = tp["Time"] - tp["LeadTime"]

    # Warm-up / drain deletion: the middle 80 % of the release horizon.
    # The 10th- and 90th-percentile release times bound the window.
    rel_sorted = release_h.sort_values().to_numpy()
    T_a = float(rel_sorted[int(0.10 * len(rel_sorted))])
    T_b = float(rel_sorted[int(0.90 * len(rel_sorted))])
    if T_b <= T_a:
        return (
            "little_law",
            False,
            "Release window degenerate — not enough spread in release times.",
        )

    # Time-average number in system over [T_a, T_b]: each order contributes
    # the part of its [release, completion] interval that overlaps the window.
    in_flight_h = (tp["Time"].clip(upper=T_b) - release_h.clip(lower=T_a)).clip(lower=0.0)
    L_direct    = float(in_flight_h.sum()) / (T_b - T_a)

    # Arrival rate and mean lead time of orders released inside the window
    mask        = (release_h >= T_a) & (release_h < T_b)
    n_window    = int(mask.sum())
    mean_lead_h = float(tp.loc[mask, "LeadTime"].mean())   # hours
    lam_obs     = n_window / (T_b - T_a)                    # orders / hour
    L_theory    = lam_obs * mean_lead_h

    rel_err = abs(L_direct - L_theory) / max(L_theory, 1e-9)
    tol     = 0.05   # 5 % relative tolerance

    passed = rel_err <= tol
    msg = (
        f"L_direct={L_direct:.3f}, L_theory={L_theory:.3f}, "
        f"rel_err={rel_err*100:.1f}% ≤ {tol*100:.0f}% — correct."
        if passed else
        f"Little's Law violated: L_direct={L_direct:.3f}, L_theory={L_theory:.3f}, "
        f"rel_err={rel_err*100:.1f}% > {tol*100:.0f}%."
    )
    return "little_law", passed, msg


def _test_steady_state_availability() -> tuple[str, bool, str]:
    """
    Steady-state availability with β = 1 (exponential failures).

    For an exponential distribution, the classical reliability formula is exact:
        A_theory = λ / (λ + MTTR)

    where λ is the Weibull scale (mean TTF in hours) and MTTR is the mean
    repair duration.  We check that the simulated FailedPct agrees within
    ±10 percentage points.
    """
    weibull_lambda = 20.0   # h  (mean TTF for β=1)
    mttr           = 4.0    # h  (mean repair duration)
    A_theory       = weibull_lambda / (weibull_lambda + mttr)  # ≈ 0.833

    gen    = generate_from_params({**_GEN_BASE, "workstations_count": 4})
    result = simulate(
        gen,
        n_orders             = 20,
        tick_duration        = 0.05,
        buffer_capacity      = 50,
        order_interarrival   = 5,
        n_ticks              = 10_000,
        log_buffers          = False,
        failures_enabled     = True,
        weibull_beta_range   = [1.0, 1.0],    # β = 1 → exponential
        weibull_lambda_range = [weibull_lambda, weibull_lambda],
        mttr_range           = [mttr, mttr],
        repair_cost_range    = [0.0, 0.0],
        seed                 = 42,
    )

    util = result["utilization"]
    if "FailedPct" not in util.columns:
        return (
            "steady_state_availability",
            False,
            "FailedPct column missing from utilization — failures may be disabled.",
        )

    A_observed = float(1.0 - util["FailedPct"].mean() / 100.0)
    tol_pp     = 0.10   # ±10 percentage points
    passed     = abs(A_observed - A_theory) <= tol_pp

    msg = (
        f"A_observed={A_observed:.3f}, A_theory={A_theory:.3f}, "
        f"|diff|={abs(A_observed-A_theory)*100:.1f}pp ≤ {tol_pp*100:.0f}pp — correct."
        if passed else
        f"Availability mismatch: A_observed={A_observed:.3f}, "
        f"A_theory={A_theory:.3f}, "
        f"|diff|={abs(A_observed-A_theory)*100:.1f}pp > {tol_pp*100:.0f}pp."
    )
    return "steady_state_availability", passed, msg


# ── Public check function ──────────────────────────────────────────────────────

def check() -> list[tuple[str, bool, str]]:
    """
    Run all statistical / theoretical checks.

    Returns
    -------
    list of (test_name, passed, message)
    """
    return [
        _test_littles_law(),
        _test_steady_state_availability(),
    ]
