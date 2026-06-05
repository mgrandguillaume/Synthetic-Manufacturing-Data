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
   (buffer_capacity: 1 → 3 → 8, everything else fixed)

3. More orders → longer makespan.
   (n_orders: 3 → 6 → 12, everything else fixed)

4. Higher branching → more non-raw components.
   (branching: 1 → 2 → 3, depth=3, sharing_ratio=0, n_products=1)
   Generator-only test; no simulation needed.

5. Higher BOM quantity → longer mean lead time.
   (quantity: [1,1] → [2,2] → [3,3], everything else fixed)

Each test runs the simulation / generator at three levels of the swept
parameter and checks that the direction of the trend is (weakly or strictly)
correct.  Because each run uses the same seed, results are deterministic and
can be audited exactly.

producers_per_component is set high so every workstation can be a producer,
making the capacity effect clearly visible.
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

def _test_more_workstations() -> tuple[str, bool, str, dict]:
    """More workstations → shorter or equal makespan."""
    ws_values  = [2, 3, 4]
    makespans: list[float] = []

    for n_ws in ws_values:
        gen    = generate_from_params(_gen(workstations_count=n_ws))
        # More orders keeps the factory capacity-constrained across all three
        # workstation levels; without this ws=4 and ws=8 give the same makespan.
        result = simulate(gen, **_sim(n_orders=20, n_ticks=8_000))
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
    plot_data = dict(
        title="More workstations → shorter makespan",
        x_label="Workstations", y_label="Makespan (h)",
        x_values=ws_values, y_values=makespans, direction="decreasing",
    )
    return "monotonicity_more_workstations", monotone, msg, plot_data


def _test_larger_buffer() -> tuple[str, bool, str, dict]:
    """Larger buffer capacity → shorter or equal makespan."""
    buf_values = [1, 3, 8]
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
    plot_data = dict(
        title="Larger buffer → shorter makespan",
        x_label="Buffer capacity", y_label="Makespan (h)",
        x_values=buf_values, y_values=makespans, direction="decreasing",
    )
    return "monotonicity_larger_buffer", monotone, msg, plot_data


def _test_more_orders() -> tuple[str, bool, str, dict]:
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
    plot_data = dict(
        title="More orders → longer makespan",
        x_label="Orders", y_label="Makespan (h)",
        x_values=order_values, y_values=makespans, direction="increasing",
    )
    return "monotonicity_more_orders", monotone, msg, plot_data


def _test_higher_branching_more_components() -> tuple[str, bool, str, dict]:
    """
    Higher branching factor → strictly more non-raw components.

    With depth = 3, n_products = 1, sharing_ratio = 0 and branching fixed to
    b, the BOM is a perfect b-ary tree with node count:

        n_non_raw = 1 + b + b²   (levels 1, 2, 3)

    Testing branching 1 → 2 → 3 gives counts 3 → 7 → 13, which must be
    strictly increasing.  This is a generator-only test (no simulation).
    """
    depth            = 3
    branching_values = [1, 2, 3]
    counts: list[int] = []

    for b in branching_values:
        gen_result = generate_from_params(_gen(
            depth              = depth,
            branching          = [b, b],
            sharing_ratio      = 0.0,
            n_products         = 1,
            workstations_count = depth,   # minimum valid
        ))
        n_non_raw = sum(1 for c in gen_result["components"] if c.level > 0)
        counts.append(n_non_raw)

    monotone = all(counts[i + 1] > counts[i] for i in range(len(counts) - 1))
    detail   = ", ".join(
        f"branching={b}: {n} components"
        for b, n in zip(branching_values, counts)
    )
    msg = (
        f"Component count strictly increases with branching — correct. ({detail})"
        if monotone else
        f"Component count did NOT strictly increase with branching. ({detail})"
    )
    plot_data = dict(
        title="Higher branching → more components",
        x_label="Branching factor", y_label="Non-raw components",
        x_values=branching_values, y_values=[float(c) for c in counts],
        direction="increasing",
    )
    return "monotonicity_higher_branching_more_components", monotone, msg, plot_data


def _test_higher_quantity_longer_leadtime() -> tuple[str, bool, str, dict]:
    """
    Higher BOM edge quantity → strictly longer mean lead time.

    With quantity = [q, q] for q = 1, 2, 3 and everything else fixed, each
    order requires proportionally more units of every component.  More
    production work per order must translate into a longer lead time.

    buffer_capacity is set generously (200) so that blocking is not the
    binding constraint — the effect must come from processing volume alone.
    """
    qty_values  = [1, 2, 3]
    lead_times: list[float] = []

    for q in qty_values:
        gen    = generate_from_params(_gen(quantity=[q, q]))
        result = simulate(gen, **_sim(
            n_orders        = 3,
            n_ticks         = 15_000,
            buffer_capacity = 200,
        ))
        tp = result["throughput"]
        lead_times.append(
            float(tp["LeadTime"].mean()) if not tp.empty else float("inf")
        )

    monotone = all(lead_times[i + 1] > lead_times[i] for i in range(len(lead_times) - 1))
    detail   = ", ".join(
        f"qty={q}: {lt:.2f} h" for q, lt in zip(qty_values, lead_times)
    )
    msg = (
        f"Mean lead time strictly increases with BOM quantity — correct. ({detail})"
        if monotone else
        f"Mean lead time did NOT strictly increase with BOM quantity. ({detail})"
    )
    plot_data = dict(
        title="Higher BOM quantity → longer lead time",
        x_label="BOM quantity", y_label="Mean lead time (h)",
        x_values=qty_values, y_values=lead_times, direction="increasing",
    )
    return "monotonicity_higher_quantity_longer_leadtime", monotone, msg, plot_data


# ── Public check functions ─────────────────────────────────────────────────────

def check_with_data() -> list[tuple[str, bool, str, dict]]:
    """
    Run all monotonicity checks, returning raw plot data alongside pass/fail.

    Returns
    -------
    list of (test_name, passed, message, plot_data)
        plot_data keys: title, x_label, y_label, x_values, y_values, direction
    """
    return [
        _test_more_workstations(),
        _test_larger_buffer(),
        _test_more_orders(),
        _test_higher_branching_more_components(),
        _test_higher_quantity_longer_leadtime(),
    ]


def check() -> list[tuple[str, bool, str]]:
    """
    Run all monotonicity checks.

    Returns
    -------
    list of (test_name, passed, message)
    """
    return [(name, passed, msg) for name, passed, msg, _ in check_with_data()]
