#!/usr/bin/env python3
"""
Config validation for the Assembly Factory model.

``validate(cfg)`` checks all parameters in a loaded config dict against two
classes of rule:

  Hard errors   — structural violations that would cause a crash or silently
                  wrong output.  Every violation is collected and all are
                  reported together in a single ``ConfigError`` exception.

  Soft warnings — feasibility issues that won't crash the run but will
                  produce misleading results (e.g. zero throughput).
                  Printed to stderr; execution continues.

Usage
-----
Called automatically before generation and simulation::

    import validate_config
    validate_config.validate(cfg)   # cfg = utils.load_config(path)
"""

import sys

# ── Terminal colour helpers ────────────────────────────────────────────────────
# ANSI codes only when stderr is connected to a real terminal.

_TTY = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


def _red(s: str)    -> str: return f"\033[91m{s}\033[0m" if _TTY else s
def _yellow(s: str) -> str: return f"\033[93m{s}\033[0m" if _TTY else s
def _bold(s: str)   -> str: return f"\033[1m{s}\033[0m"  if _TTY else s


# ── Public exception ──────────────────────────────────────────────────────────

class ConfigError(ValueError):
    """Raised when one or more hard config assertions fail."""


# ── Main entry point ──────────────────────────────────────────────────────────

def validate(cfg: dict) -> None:
    """
    Validate a loaded config dict (as returned by ``utils.load_config``).

    Parameters
    ----------
    cfg:
        Config dictionary loaded from config.yaml.

    Raises
    ------
    ConfigError
        If any hard assertion fails.  The message lists every violation found
        so the user can fix them all in one edit.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    def err(msg: str)  -> None: errors.append(msg)
    def warn(msg: str) -> None: warnings.append(msg)

    # ── Section shortcuts ──────────────────────────────────────────────────────
    bom  = cfg.get("bom",           {})
    ws   = cfg.get("workstations",  {})
    cc   = cfg.get("configurations",{})
    lay  = cfg.get("layout",        {})
    sim  = cfg.get("simulation",    {})
    fail = cfg.get("failures",      {})

    # ── Helper: validate a [min, max] range field ──────────────────────────────
    def _range(path: str, lo, hi, *, pos: bool = False) -> None:
        """
        Check a two-element numeric range [lo, hi].

        pos=True  → lo must be strictly positive (> 0)
        pos=False → lo must be non-negative (>= 0)
        """
        if lo is None:
            err(f"{path}[0] (min) is missing"); return
        if hi is None:
            err(f"{path}[1] (max) is missing"); return
        if pos and lo <= 0:
            err(f"{path}[0] (min) must be > 0  (got {lo})")
        elif not pos and lo < 0:
            err(f"{path}[0] (min) must be >= 0  (got {lo})")
        if hi < lo:
            err(f"{path}[1] (max) must be >= [0] (min)  (got [{lo}, {hi}])")

    # =========================================================================
    # HARD ASSERTIONS
    # =========================================================================

    # ── BOM ───────────────────────────────────────────────────────────────────
    n_products    = bom.get("n_products")
    depth         = bom.get("depth")
    branching     = bom.get("branching",     [None, None])
    quantity      = bom.get("quantity",      [None, None])
    sharing_ratio = bom.get("sharing_ratio", 0.0)

    if n_products is None or n_products < 1:
        err(f"bom.n_products must be >= 1  (got {n_products})")
    if depth is None or depth < 1:
        err(f"bom.depth must be >= 1  (got {depth})")

    _range("bom.branching", branching[0], branching[1], pos=True)
    _range("bom.quantity",  quantity[0],  quantity[1],  pos=True)

    if not (0.0 <= sharing_ratio <= 1.0):
        err(f"bom.sharing_ratio must be in [0.0, 1.0]  (got {sharing_ratio})")

    # ── Workstations ──────────────────────────────────────────────────────────
    n_ws          = ws.get("count")
    stage_balance = ws.get("stage_balance")

    if n_ws is None or n_ws < 1:
        err(f"workstations.count must be >= 1  (got {n_ws})")

    if depth is not None and n_ws is not None and n_ws < depth:
        err(
            f"workstations.count ({n_ws}) must be >= bom.depth ({depth})  "
            f"— every BOM level needs at least one workstation"
        )

    if stage_balance is not None and stage_balance <= 0:
        err(
            f"workstations.stage_balance must be > 0 when set  (got {stage_balance})  "
            f"— it is a Dirichlet concentration parameter; zero or negative is undefined"
        )

    # ── Configurations ────────────────────────────────────────────────────────
    ppc = cc.get("producers_per_component", [None, None])
    pt  = cc.get("processing_time",         [None, None])
    st  = cc.get("setup_time",              [None, None])
    sc  = cc.get("setup_cost",              [None, None])
    oc  = cc.get("operating_cost",          [None, None])

    if ppc[0] is None or ppc[0] < 1:
        err(f"configurations.producers_per_component[0] (min) must be >= 1  (got {ppc[0]})")
    if ppc[0] is not None and ppc[1] is not None and ppc[1] < ppc[0]:
        err(
            f"configurations.producers_per_component[1] (max) must be >= [0] (min)  "
            f"(got [{ppc[0]}, {ppc[1]}])"
        )

    _range("configurations.processing_time", pt[0], pt[1], pos=True)
    _range("configurations.setup_time",      st[0], st[1])
    _range("configurations.setup_cost",      sc[0], sc[1])
    _range("configurations.operating_cost",  oc[0], oc[1])

    # ── Layout ────────────────────────────────────────────────────────────────
    cap = lay.get("flow_capacity",  [None, None])
    tc  = lay.get("transport_cost", [None, None])

    if cap[0] is not None and cap[0] < 1:
        err(
            f"layout.flow_capacity[0] (min) must be >= 1  (got {cap[0]})  "
            f"— zero-capacity links block all material flow"
        )
    _range("layout.flow_capacity",  cap[0], cap[1], pos=True)
    _range("layout.transport_cost", tc[0],  tc[1])

    # ── Simulation ────────────────────────────────────────────────────────────
    tick_duration      = sim.get("tick_duration")
    buffer_capacity    = sim.get("buffer_capacity")
    order_interarrival = sim.get("order_interarrival")
    n_ticks            = sim.get("n_ticks")
    n_orders           = sim.get("n_orders")

    if tick_duration is None or tick_duration <= 0:
        err(f"simulation.tick_duration must be > 0  (got {tick_duration})")
    if buffer_capacity is None or buffer_capacity < 1:
        err(f"simulation.buffer_capacity must be >= 1  (got {buffer_capacity})")
    if order_interarrival is None or order_interarrival < 1:
        err(f"simulation.order_interarrival must be >= 1  (got {order_interarrival})")
    if n_ticks is None or n_ticks < 1:
        err(f"simulation.n_ticks must be >= 1  (got {n_ticks})")
    if n_orders is None or n_orders < 1:
        err(f"simulation.n_orders must be >= 1  (got {n_orders})")

    # ── Failures (only when enabled) ──────────────────────────────────────────
    failures_enabled = fail.get("enabled", False)
    if failures_enabled:
        wb   = fail.get("weibull_beta",   [None, None])
        wl   = fail.get("weibull_lambda", [None, None])
        mttr = fail.get("mttr",           [None, None])
        rc   = fail.get("repair_cost",    [None, None])

        _range("failures.weibull_beta",   wb[0],   wb[1],   pos=True)
        _range("failures.weibull_lambda", wl[0],   wl[1],   pos=True)
        _range("failures.mttr",           mttr[0], mttr[1])
        _range("failures.repair_cost",    rc[0],   rc[1])

    # =========================================================================
    # SOFT WARNINGS (feasibility)
    # =========================================================================

    # W1 — will all orders even be released before the simulation ends?
    if None not in (n_ticks, n_orders, order_interarrival):
        ticks_needed = n_orders * order_interarrival
        if n_ticks < ticks_needed:
            warn(
                f"simulation.n_ticks ({n_ticks}) < n_orders ({n_orders}) x "
                f"order_interarrival ({order_interarrival}) = {ticks_needed}  "
                f"— not all orders will be released before the simulation ends"
            )

    # W2 — can a completed batch ever fit in the buffer?
    if None not in (buffer_capacity, quantity[1]):
        if buffer_capacity < quantity[1]:
            warn(
                f"simulation.buffer_capacity ({buffer_capacity}) < "
                f"bom.quantity max ({quantity[1]})  "
                f"— completed batches may never fit in the buffer; "
                f"workstations will be permanently blocked"
            )

    # W3 — is total simulation time enough for even one order to complete?
    if None not in (tick_duration, n_ticks, depth, pt[1], st[1], quantity[1]):
        min_one_order_h = depth * (st[1] + pt[1] * quantity[1])
        total_sim_h     = n_ticks * tick_duration
        if total_sim_h < min_one_order_h:
            warn(
                f"Total simulation time ({total_sim_h:.1f} h = "
                f"n_ticks {n_ticks} x tick_duration {tick_duration} h) "
                f"< estimated minimum for one order to complete "
                f"({min_one_order_h:.1f} h = depth {depth} x "
                f"(setup_max {st[1]} h + pt_max {pt[1]} h x qty_max {quantity[1]}))  "
                f"— zero throughput is almost certain"
            )

    # W4 — are machines so fragile they fail almost every tick?
    if failures_enabled:
        wl_check = fail.get("weibull_lambda", [None, None])
        if None not in (tick_duration, wl_check[0]) and wl_check[0] < tick_duration * 10:
            warn(
                f"failures.weibull_lambda min ({wl_check[0]} h) is only "
                f"{wl_check[0] / tick_duration:.1f} ticks  "
                f"— machines will fail almost every tick; "
                f"simulation will degenerate into pure repair downtime"
            )

    # W5 — will producers_per_component[1] be silently clamped?
    if None not in (n_ws, depth, ppc[1]) and depth >= 1:
        avg_ws_per_stage = n_ws / depth
        if ppc[1] > avg_ws_per_stage:
            warn(
                f"configurations.producers_per_component max ({ppc[1]}) > "
                f"average workstations per stage "
                f"({n_ws} / {depth} = {avg_ws_per_stage:.1f})  "
                f"— the upper bound will be silently clamped in stages with fewer workstations"
            )

    # =========================================================================
    # REPORT
    # =========================================================================

    for w in warnings:
        print(_yellow(f"  [WARNING] {w}"), file=sys.stderr)

    if errors:
        bullet_list = "\n".join(f"  • {e}" for e in errors)
        raise ConfigError(
            _bold(_red("[CONFIG ERROR]")) +
            f" {len(errors)} validation error(s) in config.yaml:\n{bullet_list}"
        )

    if not warnings:
        print("  [validate_config] OK — all checks passed.")
