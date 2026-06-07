"""
Theoretical steady-state system availability.

Maps the factory's topology to a reliability block diagram (RBD) and computes
system availability by integrating E[A_ws] over the full (β, λ) distributions.

Workstation availability
------------------------
  Each workstation is modelled as an alternating renewal process with Weibull
  failure times and a uniformly distributed repair duration.

    MTBF(beta, lambda) = lambda * Gamma(1 + 1/beta)   [hours]
    A_ws(beta, lambda) = MTBF / (MTBF + E[MTTR])

  beta   ~ Uniform[beta_min,  beta_max]
  lambda ~ Uniform[lam_min,   lam_max ]

  E[MTTR] (the mean repair time) is used directly in the denominator rather
  than integrating over the MTTR distribution.  This is the physically correct
  choice: in the Monte Carlo, each machine undergoes many independent repairs
  over the horizon, so its long-run downtime per cycle converges to the mean
  MTTR by the law of large numbers.

Integration method
------------------
  E[A_ws] is evaluated by 2-D numerical quadrature over (beta, lambda) on a
  500×500 uniform grid — equivalent to the two-dimensional rectangle rule.
  With GRID_N = 500 points per axis the approximation error is < 0.01pp.

System availability
-------------------
  The system is available only when every producible component can be produced
  simultaneously (series AND gate).  Each component is available when at least
  one of its capable workstations is up (parallel OR gate).

  Because workstations can be shared across components, a naive product formula
  is incorrect.  This module therefore uses an exact workstation-state
  enumeration over all 2^n_ws states (n_ws ≤ 22) with a Monte Carlo fallback
  for larger factories.
"""

import math
from collections import defaultdict

import numpy as np

from . import _rbd

# Grid resolution for the 2-D numerical integration over (beta, lambda).
# 500x500 = 250 000 evaluations — runs in well under a second.
GRID_N = 500


def compute(gen_result: dict, failure_cfg: dict) -> dict:
    """
    Compute theoretical steady-state system availability using integrated E[A_ws].

    Parameters
    ----------
    gen_result:
        Output of generate_simple_assembly().
    failure_cfg:
        The 'failures' section of config.yaml.  Must contain:
        weibull_beta, weibull_lambda, mttr  (each a [min, max] list).

    Returns
    -------
    dict with keys:
        A_sys              float   overall system availability
        A_per_component    dict    component_id -> A_comp (marginal, for charts)
        A_ws               float   E[A_ws] — numerically integrated per-WS availability
        E_A_ws_integrated  float   same as A_ws (kept for explicitness)
        MTBF_h             float   MTBF at midpoint parameters (hours, used for scaling)
        MTTR_h             float   mean MTTR (hours)
        beta_rep           float   midpoint β (used for MTBF scaling only)
        lambda_rep         float   midpoint λ (used for MTBF scaling only)
        bottlenecks        list    components sorted by A_comp ascending
        method             str     "integrated (grid NxN)"
    """
    # ── Parameter ranges ──────────────────────────────────────────────────────
    beta_min,  beta_max  = float(failure_cfg["weibull_beta"][0]),   float(failure_cfg["weibull_beta"][1])
    lam_min,   lam_max   = float(failure_cfg["weibull_lambda"][0]), float(failure_cfg["weibull_lambda"][1])
    mttr_min,  mttr_max  = float(failure_cfg["mttr"][0]),           float(failure_cfg["mttr"][1])

    # Midpoint values (kept for reporting / per-component chart)
    beta_rep   = (beta_min  + beta_max)  / 2
    lambda_rep = (lam_min   + lam_max)   / 2
    mttr_rep   = (mttr_min  + mttr_max)  / 2
    mtbf_h     = lambda_rep * math.gamma(1.0 + 1.0 / beta_rep)

    # ── Integrate E[A_ws] over the full parameter distributions ───────────────
    E_A_ws = _integrate_A_ws(beta_min, beta_max, lam_min, lam_max, mttr_min, mttr_max)

    # ── Factory structure ─────────────────────────────────────────────────────
    prod_ws_list = [ws.id for ws in gen_result["workstations"]
                    if ws.type == "production"]
    prod_ws_ids  = set(prod_ws_list)

    comp_to_ws: dict[str, list[str]] = defaultdict(list)
    for cfg in gen_result["configurations"]:
        if cfg.workstation in prod_ws_ids:
            comp_to_ws[cfg.component].append(cfg.workstation)

    # ── Per-component MARGINAL availability (for bottleneck chart) ────────────
    producible_comps = [c for c in gen_result["components"] if c.level > 0]

    A_per_comp: dict[str, float] = {}
    for comp in producible_comps:
        capable = comp_to_ws.get(comp.id, [])
        if not capable:
            A_per_comp[comp.id] = 0.0
            continue
        A_per_comp[comp.id] = 1.0 - (1.0 - E_A_ws) ** len(capable)

    # ── System availability — exact workstation-state enumeration ─────────────
    ws_to_idx = {ws_id: i for i, ws_id in enumerate(prod_ws_list)}
    n_ws      = len(prod_ws_list)

    comp_masks: list[int] = []
    for comp in producible_comps:
        capable_ws = comp_to_ws.get(comp.id, [])
        if not capable_ws:
            return {
                "A_sys":             0.0,
                "A_per_component":   A_per_comp,
                "A_ws":              E_A_ws,
                "E_A_ws_integrated": E_A_ws,
                "MTBF_h":            mtbf_h,
                "MTTR_h":            mttr_rep,
                "beta_rep":          beta_rep,
                "lambda_rep":        lambda_rep,
                "bottlenecks":       [(comp.id, 0.0)],
                "method":            f"integrated (grid {GRID_N}x{GRID_N})",
            }
        comp_masks.append(sum(1 << ws_to_idx[ws] for ws in capable_ws
                              if ws in ws_to_idx))

    if n_ws <= _rbd.EXACT_THRESHOLD:
        A_sys = _rbd.sys_avail_exact(n_ws, comp_masks, E_A_ws)
    else:
        A_sys = _rbd.sys_avail_mc(n_ws, comp_masks, E_A_ws)

    bottlenecks = sorted(A_per_comp.items(), key=lambda kv: kv[1])

    return {
        "A_sys":             A_sys,
        "A_per_component":   A_per_comp,
        "A_ws":              E_A_ws,
        "E_A_ws_integrated": E_A_ws,
        "MTBF_h":            mtbf_h,
        "MTTR_h":            mttr_rep,
        "beta_rep":          beta_rep,
        "lambda_rep":        lambda_rep,
        "bottlenecks":       bottlenecks,
        "method":            f"integrated (grid {GRID_N}x{GRID_N})",
    }


# ── Numerical integration ─────────────────────────────────────────────────────

def _integrate_A_ws(
    beta_min: float, beta_max: float,
    lam_min:  float, lam_max:  float,
    mttr_min: float, mttr_max: float,
) -> float:
    """
    Compute E[A_ws] by 2-D numerical quadrature over (beta, lambda).

    MTTR is fixed at its mean value E[MTTR] = (mttr_min + mttr_max) / 2.
    This matches the Monte Carlo, where each machine draws a fresh repair
    duration per event and therefore experiences the mean MTTR over many
    cycles — not a single random draw held for its lifetime.

    A_ws(beta, lambda) = MTBF(beta, lambda) / (MTBF(beta, lambda) + E[MTTR])
    """
    mttr_mean = (mttr_min + mttr_max) / 2

    betas   = np.linspace(beta_min, beta_max, GRID_N)
    lambdas = np.linspace(lam_min,  lam_max,  GRID_N)

    # 2-D grid: shape (GRID_N, GRID_N)
    B, L = np.meshgrid(betas, lambdas, indexing="ij")

    # MTBF = lambda * Gamma(1 + 1/beta)  — vectorised via lookup
    gamma_vals = np.array([math.gamma(1.0 + 1.0 / b) for b in betas])  # shape (GRID_N,)
    MTBF = L * gamma_vals[:, np.newaxis]   # broadcast: (GRID_N, GRID_N)

    A_ws_grid = MTBF / (MTBF + mttr_mean)

    # Average over the uniform (beta, lambda) grid
    return float(np.mean(A_ws_grid))
