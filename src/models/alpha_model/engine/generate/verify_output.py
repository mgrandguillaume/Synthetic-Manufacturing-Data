"""
Runtime boundary checks on the generated factory data.

Called automatically at the end of generate_from_params().  Collects every
violation before raising so the full picture is visible at once.

Raises
------
GenerateOutputError
    If one or more boundary conditions are violated.  The exception message
    lists every violation as a bullet point; the raw list is also available
    as ``exc.violations``.
"""

from __future__ import annotations


class GenerateOutputError(RuntimeError):
    """Raised when the generated factory data fails a boundary check."""

    def __init__(self, violations: list[str]) -> None:
        bullet_list = "\n".join(f"  • {v}" for v in violations)
        super().__init__(
            f"Generated factory failed {len(violations)} boundary check(s):\n"
            + bullet_list
        )
        self.violations = violations


def validate(result: dict) -> None:
    """
    Check all boundary conditions on the generated factory data.

    Parameters
    ----------
    result : dict
        The dict returned by ``generate_from_params()`` / ``build_factory()``.
        Expected keys: ``components``, ``bom_edges``, ``workstations``,
        ``configurations``, ``layout_edges``, ``producible``.

    Raises
    ------
    GenerateOutputError
        Lists every violation found.  Does not raise if all checks pass.
    """
    components     = result["components"]
    bom_edges      = result["bom_edges"]
    workstations   = result["workstations"]
    configurations = result["configurations"]
    producible     = set(result.get("producible", []))

    violations: list[str] = []

    comp_by_id = {c.id: c for c in components}

    # ── Components ────────────────────────────────────────────────────────────

    # No duplicate component IDs
    seen_ids: set[str] = set()
    for c in components:
        if c.id in seen_ids:
            violations.append(f"Duplicate component ID: '{c.id}'")
        seen_ids.add(c.id)

    # All levels are non-negative integers
    for c in components:
        if c.level < 0:
            violations.append(
                f"Component '{c.id}' has negative level {c.level}"
            )

    # At least one product must exist
    if not any(c.is_product for c in components):
        violations.append("No product components found (is_product=True required on at least one)")

    # ── BOM edges ─────────────────────────────────────────────────────────────

    # No self-loops
    for e in bom_edges:
        if e.input == e.output:
            violations.append(f"BOM self-loop: '{e.input}' → '{e.input}'")

    # No duplicate (input, output) pairs
    seen_pairs: set[tuple[str, str]] = set()
    for e in bom_edges:
        pair = (e.input, e.output)
        if pair in seen_pairs:
            violations.append(
                f"Duplicate BOM edge: '{e.input}' → '{e.output}' "
                f"(same (parent, child) pair appears more than once)"
            )
        seen_pairs.add(pair)

    # All quantities strictly positive
    for e in bom_edges:
        if e.quantity <= 0:
            violations.append(
                f"BOM edge '{e.input}' → '{e.output}': "
                f"quantity={e.quantity} (must be > 0)"
            )

    # Both endpoints exist as components
    for e in bom_edges:
        if e.input not in comp_by_id:
            violations.append(
                f"BOM edge references unknown input component: '{e.input}'"
            )
        if e.output not in comp_by_id:
            violations.append(
                f"BOM edge references unknown output component: '{e.output}'"
            )

    # Level consistency: level[input] + 1 == level[output]
    for e in bom_edges:
        if e.input in comp_by_id and e.output in comp_by_id:
            in_lvl  = comp_by_id[e.input].level
            out_lvl = comp_by_id[e.output].level
            if in_lvl + 1 != out_lvl:
                violations.append(
                    f"BOM level mismatch: '{e.input}' (level {in_lvl}) "
                    f"→ '{e.output}' (level {out_lvl}) — "
                    f"expected level[input] + 1 == level[output]"
                )

    # ── Workstations ──────────────────────────────────────────────────────────

    # No duplicate workstation IDs
    seen_ws: set[str] = set()
    for w in workstations:
        if w.id in seen_ws:
            violations.append(f"Duplicate workstation ID: '{w.id}'")
        seen_ws.add(w.id)

    # Exactly one Inv (source) and one QI (sink)
    inv_count = sum(1 for w in workstations if w.id == "Inv")
    qi_count  = sum(1 for w in workstations if w.id == "QI")
    if inv_count != 1:
        violations.append(
            f"Expected exactly 1 'Inv' workstation, found {inv_count}"
        )
    if qi_count != 1:
        violations.append(
            f"Expected exactly 1 'QI' workstation, found {qi_count}"
        )

    # ── Configurations ────────────────────────────────────────────────────────

    # No duplicate (workstation, component) pairs
    seen_cfgs: set[tuple[str, str]] = set()
    for cfg in configurations:
        pair = (cfg.workstation, cfg.component)
        if pair in seen_cfgs:
            violations.append(
                f"Duplicate configuration: workstation '{cfg.workstation}', "
                f"component '{cfg.component}'"
            )
        seen_cfgs.add(pair)

    # processing_time > 0
    for cfg in configurations:
        if cfg.processing_time <= 0:
            violations.append(
                f"Configuration '{cfg.workstation}' / '{cfg.component}': "
                f"processing_time={cfg.processing_time} (must be > 0)"
            )

    # setup_time, setup_cost, operating_cost all >= 0
    for cfg in configurations:
        for attr, label in [
            (cfg.setup_time,     "setup_time"),
            (cfg.setup_cost,     "setup_cost"),
            (cfg.operating_cost, "operating_cost"),
        ]:
            if attr < 0:
                violations.append(
                    f"Configuration '{cfg.workstation}' / '{cfg.component}': "
                    f"{label}={attr} (must be >= 0)"
                )

    # Every producible component has at least one configuration
    configured = {cfg.component for cfg in configurations}
    for comp_id in producible:
        if comp_id not in configured:
            violations.append(
                f"Producible component '{comp_id}' has no configuration — "
                f"no workstation can produce it"
            )

    # ── Raise if any violations found ─────────────────────────────────────────

    if violations:
        raise GenerateOutputError(violations)
