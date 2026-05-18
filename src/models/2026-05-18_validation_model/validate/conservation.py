"""
Conservation-law checks — these must NEVER fail.

Tests
-----
1. Time balance   : for every workstation the sum of hours spent in all six
                    states equals exactly actual_ticks × tick_duration.
2. Cost identity  : every cost column across every workstation is ≥ 0.

Both checks operate on a single fresh simulation so they remain fast and
self-contained (no dependency on sweep output).
"""

from __future__ import annotations

import math
import os
import sys

# ── Path setup ─────────────────────────────────────────────────────────────────
_MODEL_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, _MODEL_ROOT)

from generate.generate import generate_from_params   # noqa: E402
from simulate.simulate import simulate               # noqa: E402

# ── Default parameters for conservation checks ─────────────────────────────────
# Small but realistic: 5 orders, 4 workstations, 2-level BOM.
_GEN = {
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

_SIM = dict(
    n_orders           = 5,
    tick_duration      = 0.05,
    buffer_capacity    = 20,
    order_interarrival = 5,
    n_ticks            = 2000,
    log_buffers        = False,
    failures_enabled   = False,
    seed               = 42,
)


# ── Public check function ──────────────────────────────────────────────────────

def check() -> list[tuple[str, bool, str]]:
    """
    Run conservation checks on a fresh simulation.

    Returns
    -------
    list of (test_name, passed, message)
    """
    results: list[tuple[str, bool, str]] = []

    gen_result = generate_from_params(_GEN)
    sim_result = simulate(gen_result, **_SIM)

    util   = sim_result["utilization"]
    states = sim_result["states"]
    costs  = sim_result["costs"]

    tick_duration = _SIM["tick_duration"]
    actual_ticks  = int(states["Tick"].max()) + 1 if not states.empty else 0
    expected_h    = actual_ticks * tick_duration

    # ── 1. Time balance ────────────────────────────────────────────────────────
    state_cols = ["Busy", "Setup", "Blocked", "Starved", "Idle", "Failed"]
    tol        = tick_duration * 0.5   # half a tick (floating-point rounding only)

    all_ok   = True
    worst_ws = ""
    worst_err = 0.0

    for _, row in util.iterrows():
        total = sum(row[c] for c in state_cols if c in row)
        err   = abs(total - expected_h)
        if err > tol:
            all_ok = False
            if err > worst_err:
                worst_err = err
                worst_ws  = str(row["Workstation"])

    if all_ok:
        results.append((
            "time_balance",
            True,
            f"All workstations: state hours sum = {expected_h:.4f} h "
            f"(actual_ticks={actual_ticks}, tick_duration={tick_duration})",
        ))
    else:
        results.append((
            "time_balance",
            False,
            f"Worst violator: {worst_ws} — error = {worst_err:.6f} h "
            f"(tolerance = {tol:.6f} h).  "
            "This indicates a bug in the state-transition logic.",
        ))

    # ── 2. Cost non-negativity ─────────────────────────────────────────────────
    cost_cols = ["SetupCost", "OperatingCost", "TransportCost", "RepairCost"]
    neg_found: list[str] = []

    for col in cost_cols:
        if col not in costs.columns:
            continue
        neg_rows = costs[costs[col] < 0]
        if not neg_rows.empty:
            neg_found.append(
                f"{col} < 0 at {neg_rows['Workstation'].tolist()}"
            )

    if not neg_found:
        results.append((
            "cost_nonnegative",
            True,
            "All cost columns are ≥ 0 across all workstations.",
        ))
    else:
        results.append((
            "cost_nonnegative",
            False,
            "Negative costs detected: " + "; ".join(neg_found),
        ))

    return results
