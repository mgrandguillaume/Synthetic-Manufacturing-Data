"""
Monotonicity checks — directional-effect tests.

These checks verify that changing one parameter in a known direction produces
a consistent effect on the output.  Due to randomness, no individual run is
guaranteed to satisfy the trend, but across the repeated runs used here the
direction should be clear.  A consistent violation is a red flag.

Tests
-----
1. More workstations → shorter or equal makespan.
   (workstations_count: 2 → 4 → 8, everything else fixed)

2. Larger buffer capacity → shorter or equal makespan.
   (buffer_capacity: 2 → 10 → 100, everything else fixed)

3. More orders → longer makespan.
   (n_orders: 3 → 6 → 12, everything else fixed)

Each test runs the simulation at three levels of the swept parameter and
checks that the direction of the trend in makespan is (weakly) correct.
Because each run uses the same seed, results are deterministic and can be
audited exactly.

producers_per_component is set high so every workstation can be a producer,
making the capacity effect clearly visible.
"""

from __future__ import annotations

import os
import sys

# ── Path setup ─────────────────────────────────────────────────────────────────
_MODEL_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, _MODEL_ROOT)

from generate.generate import generate_from_params   # noqa: E402
from simulate.simulate import simulate               # noqa: E402

# ── Base parameters ────────────────────────────────────────────────────────────
_GEN_BASE = {
    "n_products":              1,
    "depth":                   2,
    "workstations_count":      4,
    "sharing_ratio":           0.0,
    "branching":               [2, 2],
    "quantity":                [1, 1],
    "producers_per_component": [4, 4],   # high → all WSs become producers
    "processing_time":         [0.2, 0.2],
    "setup_time":              [0.5, 0.5],
    "setup_cost":              [100, 100],
    "operating_cost":          [5,   5  ],
    "flow_capacity":           [100, 100],
    "transport_cost":          [1.0, 1.0],
    "seed":                    42,
}

_SIM_BASE = dict(
    n_orders           = 10,
    tick_duration      = 0.05,
    buffer_capacity    = 50,
    order_interarrival = 5,
    n_ticks            = 5000,
    log_buffers        = False,
    failures_enabled   = False,
    seed               = 42,
)


def _gen(**overrides):
    return {**_GEN_BASE, **overrides}

def _sim(**overrides):
    return {**_SIM_BASE, **overrides}


def _makespan(sim_result: dict) -> float:
    """Return the completion time of the last order (hours)."""
    tp = sim_result["throughput"]
    if tp.empty:
        return float("inf")
    return float(tp["Time"].max())


# ── Individual tests ───────────────────────────────────────────────────────────

def _test_more_workstations() -> tuple[str, bool, str]:
    """More workstations → shorter or equal makespan."""
    ws_values  = [2, 4, 8]
    makespans: list[float] = []

    for n_ws in ws_values:
        gen    = generate_from_params(_gen(workstations_count=n_ws))
        result = simulate(gen, **_sim())
        makespans.append(_makespan(result))

    # Check weakly decreasing (each value ≤ previous + small tolerance).
    # We allow a tolerance of 1 % of the first makespan to absorb tiny
    # floating-point noise from integer tick rounding.
    tol        = makespans[0] * 0.01
    monotone   = all(makespans[i+1] <= makespans[i] + tol
                     for i in range(len(makespans) - 1))
    detail     = ", ".join(
        f"ws={ws}: {ms:.2f} h"
        for ws, ms in zip(ws_values, makespans)
    )
    msg = (
        f"Makespans decrease with more workstations — correct. ({detail})"
        if monotone else
        f"Makespan did NOT decrease consistently with more workstations. ({detail})"
    )
    return "monotonicity_more_workstations", monotone, msg


def _test_larger_buffer() -> tuple[str, bool, str]:
    """Larger buffer capacity → shorter or equal makespan."""
    buf_values = [2, 10, 100]
    makespans: list[float] = []

    gen = generate_from_params(_gen())   # factory layout is fixed
    for buf in buf_values:
        result = simulate(gen, **_sim(buffer_capacity=buf))
        makespans.append(_makespan(result))

    tol      = makespans[0] * 0.01
    monotone = all(makespans[i+1] <= makespans[i] + tol
                   for i in range(len(makespans) - 1))
    detail   = ", ".join(
        f"buf={buf}: {ms:.2f} h"
        for buf, ms in zip(buf_values, makespans)
    )
    msg = (
        f"Makespans decrease with larger buffer — correct. ({detail})"
        if monotone else
        f"Makespan did NOT decrease consistently with larger buffer. ({detail})"
    )
    return "monotonicity_larger_buffer", monotone, msg


def _test_more_orders() -> tuple[str, bool, str]:
    """More orders → longer makespan."""
    order_values = [3, 6, 12]
    makespans: list[float] = []

    gen = generate_from_params(_gen())
    for n_ord in order_values:
        result = simulate(gen, **_sim(n_orders=n_ord))
        makespans.append(_makespan(result))

    tol      = makespans[0] * 0.01
    monotone = all(makespans[i+1] >= makespans[i] - tol
                   for i in range(len(makespans) - 1))
    detail   = ", ".join(
        f"orders={n}: {ms:.2f} h"
        for n, ms in zip(order_values, makespans)
    )
    msg = (
        f"Makespans increase with more orders — correct. ({detail})"
        if monotone else
        f"Makespan did NOT increase consistently with more orders. ({detail})"
    )
    return "monotonicity_more_orders", monotone, msg


# ── Public check function ──────────────────────────────────────────────────────

def check() -> list[tuple[str, bool, str]]:
    """
    Run all monotonicity checks.

    Returns
    -------
    list of (test_name, passed, message)
    """
    return [
        _test_more_workstations(),
        _test_larger_buffer(),
        _test_more_orders(),
    ]
