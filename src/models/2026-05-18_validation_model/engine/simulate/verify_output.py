"""
Runtime boundary checks on simulation output DataFrames.

Called automatically at the end of simulate().  Checks are split into two
severity levels:

Hard violations  — indicate a genuine simulation bug; ``simulate()`` raises
                   ``SimulateOutputError`` and does **not** return results.
                   Examples: negative buffer stock, negative lead time,
                   state percentages not summing to 100 %.

Soft warnings    — expected artefacts of the discrete-time approach; results
                   are still returned but ``dfs["warnings"]`` is populated
                   so the UI can surface them without blocking the user.
                   Example: buffer overflow by a small margin due to
                   simultaneous deposition in the same tick.

Raises
------
SimulateOutputError
    Only for hard violations.  The exception message lists every violation
    as a bullet point; the raw list is also available as ``exc.violations``.
"""

from __future__ import annotations


class SimulateOutputError(RuntimeError):
    """Raised when a simulation output DataFrame fails a hard boundary check."""

    def __init__(self, violations: list[str]) -> None:
        bullet_list = "\n".join(f"  • {v}" for v in violations)
        super().__init__(
            f"Simulation output failed {len(violations)} boundary check(s):\n"
            + bullet_list
        )
        self.violations = violations


def validate(
    dfs:             dict,
    buffer_capacity: int,
    gen_result:      dict,
) -> list[str]:
    """
    Check all boundary conditions on the simulation output DataFrames.

    Hard violations raise ``SimulateOutputError`` immediately.
    Soft warnings are collected and returned as a list of strings so that
    ``simulate()`` can attach them to the result dict (``dfs["warnings"]``).

    Parameters
    ----------
    dfs : dict
        The dict returned by ``postprocess()``.  Expected keys: ``states``,
        ``utilization``, ``throughput``, ``costs``, ``buffers``.
    buffer_capacity : int
        The buffer capacity used in the simulation run.
    gen_result : dict
        The original dict from ``generate_from_params()``.  Used to look up
        valid product IDs when validating the throughput log.

    Returns
    -------
    list[str]
        Soft warning messages (may be empty).  Hard violations are raised
        rather than returned.

    Raises
    ------
    SimulateOutputError
        If one or more hard violations are found.
    """
    violations: list[str] = []   # hard — simulation bug → raise, discard results
    warnings:   list[str] = []   # soft — DTS artefact   → return alongside results

    buf_df  = dfs.get("buffers")
    util_df = dfs.get("utilization")
    tp_df   = dfs.get("throughput")
    cost_df = dfs.get("costs")

    product_ids = {c.id for c in gen_result["components"] if c.is_product}

    # ── Buffers ───────────────────────────────────────────────────────────────

    if buf_df is not None and not buf_df.empty:

        # HARD: Stock < 0 — material was consumed without being produced first.
        neg = buf_df[buf_df["Stock"] < 0]
        if not neg.empty:
            worst = neg.loc[neg["Stock"].idxmin()]
            violations.append(
                f"Negative buffer stock: component '{worst['Component']}' "
                f"reached stock={int(worst['Stock'])} at time={worst['Time']:.3f} h "
                f"({len(neg)} total negative observations across all ticks)"
            )

        # HARD: Stock > buffer_capacity for intermediate components.
        #
        # The tick loop enforces buffer_capacity on every deposit attempt
        # (Phases 2 and 3).  The only known path that can bypass this guard
        # is the failure-restoration code (Phase 0): when a workstation fails
        # mid-job, its consumed inputs are returned to stock without a
        # capacity check — if those buffers are already full, stock exceeds
        # buffer_capacity.  That is a genuine model bug, not a DTS artefact.
        max_level     = int(buf_df["Level"].max())
        intermediates = buf_df[buf_df["Level"] < max_level]
        over = intermediates[intermediates["Stock"] > buffer_capacity]
        if not over.empty:
            worst = over.loc[over["Stock"].idxmax()]
            violations.append(
                f"Buffer overflow: component '{worst['Component']}' "
                f"reached stock={int(worst['Stock'])} > buffer_capacity={buffer_capacity} "
                f"at time={worst['Time']:.3f} h "
                f"({len(over)} total overflow observations across all ticks)"
            )

    # ── Utilization ───────────────────────────────────────────────────────────

    if util_df is not None and not util_df.empty:

        # HARD: negative time-in-state (accounting bug)
        time_cols = ["Busy", "Setup", "Blocked", "Starved", "Idle", "Failed"]
        for col in time_cols:
            if col not in util_df.columns:
                continue
            neg_rows = util_df[util_df[col] < 0]
            if not neg_rows.empty:
                offenders = ", ".join(f"'{w}'" for w in neg_rows["Workstation"])
                violations.append(
                    f"Utilization '{col}' is negative for workstation(s): {offenders}"
                )

        # HARD: state percentages not summing to 100 % (time-balance bug)
        pct_cols = ["BusyPct", "SetupPct", "BlockedPct", "StarvedPct", "IdlePct", "FailedPct"]
        if all(c in util_df.columns for c in pct_cols):
            total_pct = util_df[pct_cols].sum(axis=1)
            bad = util_df[(total_pct - 100.0).abs() > 0.1]
            for _, row in bad.iterrows():
                s = sum(row[c] for c in pct_cols)
                violations.append(
                    f"Workstation '{row['Workstation']}': state percentages sum to "
                    f"{s:.3f} % (expected 100 %)"
                )

    # ── Throughput ────────────────────────────────────────────────────────────

    if tp_df is not None and not tp_df.empty:

        # HARD: non-positive lead time
        bad_lt = tp_df[tp_df["LeadTime"] <= 0]
        if not bad_lt.empty:
            violations.append(
                f"Throughput: {len(bad_lt)} completed order(s) have LeadTime <= 0"
            )

        # HARD: non-monotonic completion times
        times = tp_df["Time"].to_numpy()
        if len(times) > 1 and (times[1:] < times[:-1]).any():
            violations.append(
                "Throughput: completion times are not monotonically non-decreasing"
            )

        # HARD: unrecognised product IDs
        unknown = set(tp_df["Product"].unique()) - product_ids
        if unknown:
            violations.append(
                f"Throughput: unrecognised product ID(s) in log: "
                + ", ".join(f"'{p}'" for p in sorted(unknown))
            )

    # ── Costs ─────────────────────────────────────────────────────────────────

    if cost_df is not None and not cost_df.empty:
        # HARD: negative costs (accounting bug)
        cost_cols = ["SetupCost", "OperatingCost", "TransportCost", "RepairCost"]
        for col in cost_cols:
            if col not in cost_df.columns:
                continue
            neg_rows = cost_df[cost_df[col] < 0]
            if not neg_rows.empty:
                offenders = ", ".join(f"'{w}'" for w in neg_rows["Workstation"])
                violations.append(
                    f"Costs '{col}' is negative for workstation(s): {offenders}"
                )

    # ── Raise for hard violations; return soft warnings ───────────────────────

    if violations:
        raise SimulateOutputError(violations)

    return warnings
