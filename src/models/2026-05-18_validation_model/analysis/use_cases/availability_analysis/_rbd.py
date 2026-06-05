"""
Reliability block diagram (RBD) system-availability solvers.

Shared by theoretical.py (midpoint A_ws) and theoretical_integrated.py
(integrated E[A_ws]) so the system-level calculation lives in exactly one
place.

Factory model
-------------
  The factory is a SERIES system of PARALLEL component-producer groups:
  the system is available iff every producible component has at least one
  capable workstation that is up.  With shared workstations the per-component
  events are correlated, so the system availability cannot be obtained by
  multiplying marginal component availabilities — it requires either exact
  state enumeration or simulation.

Solvers
-------
  sys_avail_exact   Exact, by enumerating all 2^n_ws workstation up/down
                    states.  Vectorised with NumPy; at the default threshold
                    (n_ws = 22, ~4.2 M states) it completes in well under a
                    second and uses ~34 MB.

  sys_avail_mc      Vectorised Monte Carlo fallback for larger factories,
                    where exact enumeration grows as 2^n_ws and becomes
                    memory- and time-prohibitive.
"""

import numpy as np

# Maximum number of workstations for exact enumeration (2^N states).
# At N = 22 the state array holds ~4.2 M entries (~34 MB as uint64) and the
# vectorised solver runs in well under a second.  Memory and time both grow as
# 2^N, so beyond this threshold the Monte Carlo fallback is used instead.
EXACT_THRESHOLD = 22

# Default number of samples for the Monte Carlo fallback.
_MC_SAMPLES = 500_000

# Per-byte population-count lookup table (number of set bits in 0..255).
_POPCOUNT_TABLE = np.array([bin(i).count("1") for i in range(256)], dtype=np.int16)


def sys_avail_exact(n_ws: int, comp_masks: list[int], A_ws: float) -> float:
    """
    Exact system availability by exhaustive workstation-state enumeration.

    Enumerates all 2^n_ws combinations of workstation up/down states, weights
    each by its probability  A_ws^(#up) * (1 - A_ws)^(#down), and sums over the
    states in which every component has at least one capable workstation up.

    Parameters
    ----------
    n_ws:
        Number of production workstations (must be <= EXACT_THRESHOLD).
    comp_masks:
        Bitmasks; comp_masks[i] has bit k set iff workstation k can produce
        component i.  Component i is available in a state iff
        (state & comp_masks[i]) != 0.
    A_ws:
        Per-workstation steady-state availability (identical for all stations).
    """
    total_states = 1 << n_ws
    states = np.arange(total_states, dtype=np.uint64)

    # Number of UP workstations per state, via a per-byte popcount table.
    n_up = _POPCOUNT_TABLE[states.view(np.uint8).reshape(total_states, 8)].sum(axis=1)

    # P(state) = A_ws^n_up * (1 - A_ws)^(n_ws - n_up).
    pow_A = A_ws ** np.arange(n_ws + 1)
    pow_q = (1.0 - A_ws) ** np.arange(n_ws + 1)
    p = pow_A[n_up] * pow_q[n_ws - n_up]

    # System available iff every component has >= 1 capable workstation up.
    avail = np.ones(total_states, dtype=bool)
    for m in comp_masks:
        avail &= (states & np.uint64(m)) != 0

    return float(p[avail].sum())


def sys_avail_mc(
    n_ws: int,
    comp_masks: list[int],
    A_ws: float,
    n_samples: int = _MC_SAMPLES,
    seed: int = 0,
) -> float:
    """
    Vectorised Monte Carlo estimate of system availability.

    Fallback for factories larger than EXACT_THRESHOLD, where exact enumeration
    is infeasible.  Draws random workstation up/down states (each station up
    independently with probability A_ws) and returns the fraction of states in
    which every component has at least one capable workstation up.
    """
    rng = np.random.default_rng(seed)
    up = rng.random((n_samples, n_ws)) < A_ws   # bool[n_samples, n_ws]

    avail = np.ones(n_samples, dtype=bool)
    for m in comp_masks:
        capable_idx = [k for k in range(n_ws) if (m >> k) & 1]
        if not capable_idx:
            return 0.0
        avail &= up[:, capable_idx].any(axis=1)

    return float(avail.mean())
