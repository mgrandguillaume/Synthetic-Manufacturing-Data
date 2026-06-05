"""
Improved theoretical steady-state system availability.

Identical to theoretical.py in every respect EXCEPT for how the
representative workstation availability A_ws is computed.

theoretical.py          uses A_ws at the MIDPOINT of each parameter range.
theoretical_integrated  uses E[A_ws] integrated over the FULL distributions.

Why this matters
----------------
  A_ws = MTTF(beta, lambda) / (MTTF(beta, lambda) + MTTR)
       = lambda * Gamma(1 + 1/beta) / (lambda * Gamma(1 + 1/beta) + MTTR)

  This function is concave in lambda.  By Jensen's inequality:
      E[f(lambda)] < f(E[lambda])
  so plugging in the midpoint lambda overestimates the true mean A_ws.
  With a wide lambda range [20, 100] the bias is around 0.7pp per workstation,
  which compounds to ~2.6pp at the system level.

Integration method
------------------
  beta   ~ Uniform[beta_min,  beta_max]
  lambda ~ Uniform[lam_min,   lam_max ]

  MTTR is NOT integrated over its distribution.  Instead, the mean MTTR is
  used directly in the denominator:

    A_ws(beta, lambda) = MTTF(beta, lambda) / (MTTF(beta, lambda) + E[MTTR])

  This matches the Monte Carlo exactly: each simulated machine draws a fresh
  repair duration per event, so over a long horizon its effective downtime per
  cycle converges to the mean MTTR, not to a single random draw.  Integrating
  A_ws over the MTTR distribution would instead model a machine whose repair
  time is fixed for its entire lifetime — physically incorrect and a source of
  a small upward bias via Jensen's inequality (A is convex in MTTR).

  The two remaining dimensions (beta, lambda) are integrated over a 500x500
  grid.  With GRID_N = 500 points per axis the integral converges to < 0.01pp
  error.

Drop-in compatibility
---------------------
  compute() returns the same dict structure as theoretical.compute(), with
  two additional keys:
      E_A_ws_integrated   float   the numerically integrated E[A_ws]
      method              str     always "integrated (grid NxN)"
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
    Same dict as theoretical.compute(), plus:
        E_A_ws_integrated   float   numerically integrated per-WS availability
        method              str     "integrated (grid NxN)"
    """
    # ── Parameter ranges ──────────────────────────────────────────────────────
    beta_min,  beta_max  = float(failure_cfg["weibull_beta"][0]),   float(failure_cfg["weibull_beta"][1])
    lam_min,   lam_max   = float(failure_cfg["weibull_lambda"][0]), float(failure_cfg["weibull_lambda"][1])
    mttr_min,  mttr_max  = float(failure_cfg["mttr"][0]),           float(failure_cfg["mttr"][1])

    # Midpoint values (kept for reporting / per-component chart)
    beta_rep   = (beta_min  + beta_max)  / 2
    lambda_rep = (lam_min   + lam_max)   / 2
    mttr_rep   = (mttr_min  + mttr_max)  / 2
    mttf_h     = lambda_rep * math.gamma(1.0 + 1.0 / beta_rep)

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
                "MTTF_h":            mttf_h,
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
        "MTTF_h":            mttf_h,
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

    A_ws(beta, lambda) = MTTF(beta, lambda) / (MTTF(beta, lambda) + E[MTTR])
    """
    mttr_mean = (mttr_min + mttr_max) / 2

    betas   = np.linspace(beta_min, beta_max, GRID_N)
    lambdas = np.linspace(lam_min,  lam_max,  GRID_N)

    # 2-D grid: shape (GRID_N, GRID_N)
    B, L = np.meshgrid(betas, lambdas, indexing="ij")

    # MTTF = lambda * Gamma(1 + 1/beta)  — vectorised via lookup
    gamma_vals = np.array([math.gamma(1.0 + 1.0 / b) for b in betas])  # shape (GRID_N,)
    MTTF = L * gamma_vals[:, np.newaxis]   # broadcast: (GRID_N, GRID_N)

    A_ws_grid = MTTF / (MTTF + mttr_mean)

    # Average over the uniform (beta, lambda) grid
    return float(np.mean(A_ws_grid))
