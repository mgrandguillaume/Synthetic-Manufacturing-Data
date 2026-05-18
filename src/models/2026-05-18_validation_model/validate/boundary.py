"""
Boundary / degenerate-case checks — unit tests with known-correct answers.

Tests
-----
1. n_orders = 0        → throughput DataFrame is empty (0 rows).
2. n_orders = 1        → exactly 1 completed order in throughput.
3. Large buffer        → BlockedPct = 0 for every workstation.
4. Large Weibull λ     → FailedPct ≈ 0 when failures are enabled with
                         an astronomically long characteristic life.
5. sharing_ratio = 1.0 → every BOM level uses one shared component, so
                         n_non_raw_components == depth (one per level).
"""

from __future__ import annotations

import os
import sys

# ── Path setup ─────────────────────────────────────────────────────────────────
_MODEL_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, _MODEL_ROOT)

from generate.generate import generate_from_params   # noqa: E402
from simulate.simulate import simulate               # noqa: E402

# ── Base parameters (overridden per test) ──────────────────────────────────────
_GEN_BASE = {
    "n_products":              1,
    "depth":                   2,
    "workstations_count":      4,
    "sharing_ratio":           0.0,
    "branching":               [2, 2],
    "quantity":                [1, 1],
    "producers_per_component": [1, 1],
    "processing_time":         [0.2, 0.2],
    "setup_time":              [0.5, 0.5],
    "setup_cost":              [100, 100],
    "operating_cost":          [5,   5  ],
    "flow_capacity":           [100, 100],
    "transport_cost":          [1.0, 1.0],
    "seed":                    42,
}

_SIM_BASE = dict(
    n_orders           = 5,
    tick_duration      = 0.05,
    buffer_capacity    = 20,
    order_interarrival = 5,
    n_ticks            = 2000,
    log_buffers        = False,
    failures_enabled   = False,
    seed               = 42,
)


def _gen(**overrides):
    return {**_GEN_BASE, **overrides}

def _sim(**overrides):
    return {**_SIM_BASE, **overrides}


# ── Individual tests ───────────────────────────────────────────────────────────

def _test_zero_orders() -> tuple[str, bool, str]:
    """n_orders = 0 → throughput is empty."""
    gen    = generate_from_params(_gen())
    result = simulate(gen, **_sim(n_orders=0, n_ticks=10))
    tp     = result["throughput"]
    passed = tp.empty or len(tp) == 0
    msg = (
        "throughput DataFrame is empty — correct."
        if passed else
        f"Expected 0 rows in throughput, got {len(tp)}."
    )
    return "boundary_zero_orders", passed, msg


def _test_single_order() -> tuple[str, bool, str]:
    """n_orders = 1 → exactly 1 completed order in throughput."""
    gen    = generate_from_params(_gen())
    result = simulate(gen, **_sim(n_orders=1))
    tp     = result["throughput"]
    n      = len(tp)
    passed = n == 1
    msg = (
        "1 order completed — correct."
        if passed else
        f"Expected 1 completed order, got {n}."
    )
    return "boundary_single_order", passed, msg


def _test_large_buffer() -> tuple[str, bool, str]:
    """Large buffer capacity → BlockedPct = 0 for every workstation."""
    gen    = generate_from_params(_gen())
    result = simulate(gen, **_sim(buffer_capacity=1_000_000))
    util   = result["utilization"]
    if "BlockedPct" in util.columns:
        blocked = util["BlockedPct"]
    else:
        failed = util["Failed"] if "Failed" in util.columns else 0
        total  = (util["Busy"] + util["Setup"] + util["Blocked"]
                  + util["Starved"] + util["Idle"] + failed)
        blocked = util["Blocked"] / total.replace(0, 1) * 100
    max_blocked = float(blocked.max())
    passed = max_blocked < 1e-6
    msg = (
        "BlockedPct = 0 for all workstations — correct."
        if passed else
        f"Max BlockedPct = {max_blocked:.4f} % despite buffer_capacity = 1 000 000."
    )
    return "boundary_large_buffer", passed, msg


def _test_large_lambda() -> tuple[str, bool, str]:
    """
    Weibull λ = 1 000 000 h → effectively no failures.
    FailedPct must be 0 for every workstation.
    """
    gen    = generate_from_params(_gen())
    result = simulate(gen, **_sim(
        failures_enabled   = True,
        weibull_beta_range   = [2.0, 2.0],
        weibull_lambda_range = [1_000_000.0, 1_000_000.0],
        mttr_range           = [1.0, 1.0],
        repair_cost_range    = [0.0, 0.0],
        n_ticks              = 2000,
        n_orders             = 5,
    ))
    util = result["utilization"]
    if "FailedPct" in util.columns:
        max_failed = float(util["FailedPct"].max())
    elif "Failed" in util.columns:
        state_cols = ["Busy", "Setup", "Blocked", "Starved", "Idle", "Failed"]
        total_h    = util[[c for c in state_cols if c in util.columns]].sum(axis=1)
        max_failed = float((util["Failed"] / total_h * 100).max())
    else:
        max_failed = 0.0

    passed = max_failed < 1e-6
    msg = (
        "FailedPct = 0 with λ = 1 000 000 h — correct."
        if passed else
        f"Max FailedPct = {max_failed:.6f} % despite λ = 1 000 000 h."
    )
    return "boundary_large_lambda", passed, msg


def _test_full_sharing() -> tuple[str, bool, str]:
    """
    sharing_ratio = 1.0, n_products = 1 → only one component per BOM level,
    so n_non_raw_components (level > 0) must equal depth.
    """
    depth = 3
    gen_params = _gen(
        depth         = depth,
        sharing_ratio = 1.0,
        n_products    = 1,
        branching     = [2, 2, 2],
        quantity      = [1, 1, 1],
        workstations_count = depth,    # at least depth workstations
    )
    gen_result = generate_from_params(gen_params)
    components = gen_result["components"]
    n_non_raw  = sum(1 for c in components if c.level > 0)
    passed     = n_non_raw == depth
    msg = (
        f"n_non_raw_components = {n_non_raw} == depth ({depth}) — correct."
        if passed else
        f"Expected n_non_raw_components = depth ({depth}), got {n_non_raw}."
    )
    return "boundary_full_sharing", passed, msg


# ── Public check function ──────────────────────────────────────────────────────

def check() -> list[tuple[str, bool, str]]:
    """
    Run all boundary checks.

    Returns
    -------
    list of (test_name, passed, message)
    """
    return [
        _test_zero_orders(),
        _test_single_order(),
        _test_large_buffer(),
        _test_large_lambda(),
        _test_full_sharing(),
    ]
