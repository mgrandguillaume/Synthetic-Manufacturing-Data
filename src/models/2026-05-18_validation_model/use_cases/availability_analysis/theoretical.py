"""
Theoretical steady-state system availability.

Maps the factory's topology to a reliability block diagram (RBD) and computes
system availability using midpoint Weibull parameters.

Topology rules
--------------
  Parallel subsystem (OR gate)
    For each producible component, any one capable workstation is sufficient.
    A_comp = 1 - prod(1 - A_ws_i)   for all ws_i capable of producing comp

  Series system (AND gate)
    The system is available only when EVERY producible component can be produced
    simultaneously.

System availability — exact vs naive
-------------------------------------
  A naive approach multiplies per-component availabilities:
      A_sys ≈ prod(A_comp_c)
  This is ONLY correct when all component availability events are independent,
  i.e. no two components share a capable workstation.

  In a typical factory workstations ARE shared (e.g. one workstation may be the
  sole producer of several components).  When WS_k fails, every component that
  has WS_k as its only producer goes down simultaneously — correlated failures
  that the product formula double-counts.

  This module therefore uses an EXACT workstation-state enumeration:
    • List all n_ws production workstations.
    • Iterate over every 2^n_ws (up, down) state combination.
    • For each state, check whether the system is available (all components
      have at least one capable workstation that is up).
    • Weight each state by its probability  A_ws^(#up) * (1-A_ws)^(#down).
    • Sum over all system-available states.

  For n_ws ≤ 25 this runs in well under a second.  For larger factories a
  fallback Monte Carlo estimate is used instead (see _sys_avail_large).

Workstation availability
------------------------
  Each workstation is modelled as Weibull with shape beta and scale lambda.

    MTTF = lambda * Gamma(1 + 1/beta)     [hours]
    A_ws = MTTF / (MTTF + E[MTTR])

  The midpoint of each configured range is used as the representative value:

    beta_rep   = (weibull_beta[0]   + weibull_beta[1])   / 2
    lambda_rep = (weibull_lambda[0] + weibull_lambda[1]) / 2
    mttr_rep   = (mttr[0]           + mttr[1])           / 2

  Because all workstations are drawn from the same distribution, every
  production workstation gets the same A_ws in this analysis.

Note on approximation
---------------------
  Using E[params] in a non-linear function underestimates variance effects
  (Jensen's inequality).  For narrow parameter ranges the error is negligible;
  for wide ranges the experimental result may differ by a few percentage points.
  The experimental Monte Carlo naturally accounts for this.
"""

import math
from collections import defaultdict


# Maximum number of workstations for exact enumeration (2^N states).
# For N=25 this is ~33 M iterations — feasible but slow.  Above this threshold
# a Monte Carlo fallback is used.
_EXACT_THRESHOLD = 22   # 2^22 = ~4 M, comfortably fast


def compute(gen_result: dict, failure_cfg: dict) -> dict:
    """
    Compute theoretical steady-state system availability.

    Parameters
    ----------
    gen_result:
        Output of generate_simple_assembly() or generate_from_params().
    failure_cfg:
        The 'failures' section of config.yaml as a dict.  Must contain:
        weibull_beta, weibull_lambda, mttr  (each a [min, max] list).

    Returns
    -------
    dict with keys:
        A_sys              float   overall system availability
        A_per_component    dict    component_id -> A_comp  (marginal, for charts)
        A_ws               float   per-workstation availability (all identical)
        MTTF_h             float   mean time to failure (hours)
        MTTR_h             float   mean time to repair  (hours)
        beta_rep           float   representative Weibull shape used
        lambda_rep         float   representative Weibull scale used
        bottlenecks        list    components sorted by A_comp ascending
                                   (weakest links first, based on marginal A_comp)
        method             str     "exact" or "monte_carlo_N" depending on n_ws
    """
    # ── Representative parameter values (midpoints of configured ranges) ──────
    beta_rep   = sum(failure_cfg["weibull_beta"])   / 2
    lambda_rep = sum(failure_cfg["weibull_lambda"]) / 2
    mttr_rep   = sum(failure_cfg["mttr"])           / 2

    # ── Per-workstation MTTF and steady-state availability ────────────────────
    # Weibull MTTF = lambda * Gamma(1 + 1/beta)
    mttf_h = lambda_rep * math.gamma(1.0 + 1.0 / beta_rep)
    A_ws   = mttf_h / (mttf_h + mttr_rep)

    # ── Build component -> capable workstation list ───────────────────────────
    prod_ws_list = [ws.id for ws in gen_result["workstations"]
                    if ws.type == "production"]
    prod_ws_ids  = set(prod_ws_list)

    comp_to_ws: dict[str, list[str]] = defaultdict(list)
    for cfg in gen_result["configurations"]:
        if cfg.workstation in prod_ws_ids:
            comp_to_ws[cfg.component].append(cfg.workstation)

    # ── Per-component MARGINAL availability (parallel combination) ────────────
    # Used for the bottleneck chart; does NOT account for shared-workstation
    # correlations — that is handled at the system level below.
    producible_comps = [c for c in gen_result["components"] if c.level > 0]

    A_per_comp: dict[str, float] = {}
    for comp in producible_comps:
        capable = comp_to_ws.get(comp.id, [])
        if not capable:
            A_per_comp[comp.id] = 0.0
            continue
        unavailability = (1.0 - A_ws) ** len(capable)
        A_per_comp[comp.id] = 1.0 - unavailability

    # ── System availability — exact workstation-state enumeration ─────────────
    # Build a compact list of (component_id, frozenset_of_capable_ws) for all
    # producible components that have at least one producer.  Components without
    # any producer immediately make A_sys = 0.
    comp_capable: list[list[int]] = []   # list of lists of workstation indices
    ws_to_idx = {ws_id: i for i, ws_id in enumerate(prod_ws_list)}
    n_ws = len(prod_ws_list)

    for comp in producible_comps:
        capable_ws = comp_to_ws.get(comp.id, [])
        if not capable_ws:
            # No producer → system permanently unavailable
            return {
                "A_sys":           0.0,
                "A_per_component": A_per_comp,
                "A_ws":            A_ws,
                "MTTF_h":          mttf_h,
                "MTTR_h":          mttr_rep,
                "beta_rep":        beta_rep,
                "lambda_rep":      lambda_rep,
                "bottlenecks":     [(comp.id, 0.0)],
                "method":          "n/a (unprocducible component)",
            }
        comp_capable.append([ws_to_idx[ws] for ws in capable_ws
                              if ws in ws_to_idx])

    # Pre-compute bitmasks for each component's capable workstations.
    # comp_mask[i] is an integer where bit k=1 means workstation k can produce
    # component i.  The component is available when (state & comp_mask[i]) != 0,
    # i.e. at least one of its producers is up.
    comp_masks: list[int] = [
        sum(1 << idx for idx in cap) for cap in comp_capable
    ]

    if n_ws <= _EXACT_THRESHOLD:
        A_sys, method = _sys_avail_exact(n_ws, comp_masks, A_ws)
    else:
        A_sys, method = _sys_avail_mc(n_ws, comp_masks, A_ws, n_samples=500_000)

    # ── Identify bottlenecks ──────────────────────────────────────────────────
    bottlenecks = sorted(A_per_comp.items(), key=lambda kv: kv[1])

    return {
        "A_sys":           A_sys,
        "A_per_component": A_per_comp,
        "A_ws":            A_ws,
        "MTTF_h":          mttf_h,
        "MTTR_h":          mttr_rep,
        "beta_rep":        beta_rep,
        "lambda_rep":      lambda_rep,
        "bottlenecks":     bottlenecks,
        "method":          method,
    }


# ── System availability helpers ───────────────────────────────────────────────

def _sys_avail_exact(n_ws: int, comp_masks: list[int], A_ws: float) -> tuple[float, str]:
    """
    Exact system availability by exhaustive workstation-state enumeration.

    Iterates over all 2^n_ws combinations of workstation up/down states,
    computes the probability of each state, and sums over states in which
    every component has at least one capable workstation that is up.

    Parameters
    ----------
    n_ws:
        Number of production workstations.
    comp_masks:
        List of bitmasks.  comp_masks[i] has bit k set iff workstation k can
        produce component i.
    A_ws:
        Per-workstation steady-state availability (same for all workstations).

    Returns
    -------
    (A_sys, method_label)
    """
    q   = 1.0 - A_ws
    total_states = 1 << n_ws

    # Pre-compute powers of A_ws and q to avoid repeated **-operations.
    pow_A = [A_ws ** k for k in range(n_ws + 1)]
    pow_q = [q        ** k for k in range(n_ws + 1)]

    A_sys = 0.0
    for state in range(total_states):
        # Number of workstations that are UP in this state.
        n_up = bin(state).count("1")
        p    = pow_A[n_up] * pow_q[n_ws - n_up]

        # System is available iff every component has at least one capable
        # workstation that is up: (state & comp_mask) != 0 for all components.
        if all((state & m) for m in comp_masks):
            A_sys += p

    return A_sys, "exact"


def _sys_avail_mc(
    n_ws: int,
    comp_masks: list[int],
    A_ws: float,
    n_samples: int = 500_000,
    seed: int = 0,
) -> tuple[float, str]:
    """
    Monte Carlo estimate of system availability (fallback for large factories).

    Draws random workstation up/down states and checks availability.
    """
    import random
    rng = random.Random(seed)

    up_count = 0
    for _ in range(n_samples):
        # Build random state: each workstation independently up with prob A_ws.
        state = sum(
            (1 << k)
            for k in range(n_ws)
            if rng.random() < A_ws
        )
        if all((state & m) for m in comp_masks):
            up_count += 1

    return up_count / n_samples, f"monte_carlo_{n_samples}"
