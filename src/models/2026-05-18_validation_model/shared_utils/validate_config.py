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

Hard errors
-----------
  All range fields valid (min/max present, min <= max, pos where required).
  bom.n_products >= 1
  bom.depth >= 1
  bom.sharing_ratio in [0, 1]
  workstations.count >= 1
  workstations.count >= bom.depth  (every BOM level needs a workstation)
  workstations.stage_balance > 0 when set
  configurations.producers_per_component[0] >= 1
  configurations specifies assembly_type or processing_time (not neither)
  assembly_type in {low, medium, high}
  configurations.variation in (0, 1) when assembly_type is used
  simulation.tick_duration > 0
  simulation.buffer_capacity >= bom.quantity[1]   ← E-NEW-1 (deadlock guard)
  simulation.buffer_capacity >= 1
  simulation.order_interarrival >= 1
  simulation.n_ticks >= 1
  simulation.n_orders >= 1
  failures.* ranges valid (when failures.enabled = true)

Soft warnings
-------------
  W1  n_ticks too small to release all orders
  W2  (removed — upgraded to hard error E-NEW-1)
  W3  total simulation horizon too short for even one order (includes branching)
  W4  weibull_lambda so small machines fail almost every tick
  W5  producers_per_component[1] will be silently clamped in small stages
  W6  BOM explosion very large — quotes recommended n_ticks
  W7  theoretical worst-case availability A_worst < 0.5 (Hopp & Spearman Ch. 8; MTTF via Weibull theory)
  W8  buffer_capacity < branching_max x qty_max (heavy blocking expected)
  W9  setup_time_max > 2x processing_time (changeover dominates)
  W10 sweep grid contains invalid (depth, workstations_count) combinations

Usage
-----
Called automatically before generation and simulation::

    import validate_config
    validate_config.validate(cfg)   # cfg = utils.load_config(path)
"""

import math
import sys

# ── Terminal colour helpers ────────────────────────────────────────────────────
# ANSI codes only when stderr is connected to a real terminal.

_TTY = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


def _red(s: str)    -> str: return f"\033[91m{s}\033[0m" if _TTY else s
def _yellow(s: str) -> str: return f"\033[93m{s}\033[0m" if _TTY else s
def _bold(s: str)   -> str: return f"\033[1m{s}\033[0m"  if _TTY else s


# ── Public exception ──────────────────────────────────────────────────────────

class ConfigError(ValueError):
    """Raised when one or more hard config assertions fail.

    Attributes
    ----------
    errors   : list[str]   — the hard error messages
    warnings : list[str]   — soft warnings collected before the errors were found
    """

    def __init__(self, message: str, errors: list = (), warnings: list = ()):
        super().__init__(message)
        self.errors   = list(errors)
        self.warnings = list(warnings)


# ── Module-level constants ─────────────────────────────────────────────────────

# (alpha, beta) coefficients for the assembly_type processing-time formula:
#   pt_mean = alpha * depth^beta   (hours per unit)
_PT_COEFFS: dict[str, tuple[float, float]] = {
    "low":    (0.33, 1.39),
    "medium": (0.28, 1.45),
    "high":   (0.12, 1.79),
}


# ── Private helpers ────────────────────────────────────────────────────────────

def _pt_range(assembly_type, variation, pt_explicit, depth) -> tuple:
    """
    Return (pt_min_h, pt_max_h) for processing time regardless of which
    configuration mode is active.

    Returns (None, None) if the parameters are incomplete or invalid.
    """
    if assembly_type in _PT_COEFFS and depth is not None:
        alpha, beta = _PT_COEFFS[assembly_type]
        pt_mean = alpha * (depth ** beta)
        var = float(variation) if isinstance(variation, (int, float)) else 0.10
        return pt_mean * (1.0 - var), pt_mean * (1.0 + var)
    if pt_explicit[0] is not None and pt_explicit[1] is not None:
        return float(pt_explicit[0]), float(pt_explicit[1])
    return None, None


def _expand_sweep_param(v) -> list:
    """
    Expand a sweep parameter value (scalar / list / {min,max,step} dict)
    to a flat list of numeric values, mirroring sweep.py's expansion logic.
    """
    if v is None:
        return []
    if isinstance(v, (int, float)):
        return [v]
    if isinstance(v, list):
        return list(v)
    if isinstance(v, dict):
        lo   = v.get("min")
        hi   = v.get("max")
        step = v.get("step", 1)
        if lo is None or hi is None or step <= 0:
            return []
        result, val = [], lo
        while val <= hi + 1e-9:
            result.append(round(val, 10))
            val += step
        return result
    return []


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
    bom   = cfg.get("bom",            {})
    ws    = cfg.get("workstations",   {})
    cc    = cfg.get("configurations", {})
    lay   = cfg.get("layout",         {})
    sim   = cfg.get("simulation",     {})
    fail  = cfg.get("failures",       {})
    sweep = cfg.get("sweep",          {})

    # ── Helper: validate a [min, max] range field ──────────────────────────────
    def _range(path: str, lo, hi, *, pos: bool = False) -> None:
        """
        Check a two-element numeric range [lo, hi].

        pos=True  -> lo must be strictly positive (> 0)
        pos=False -> lo must be non-negative (>= 0)
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
    ppc           = cc.get("producers_per_component", [None, None])
    assembly_type = cc.get("assembly_type")
    variation     = cc.get("variation", 0.10)
    pt            = cc.get("processing_time", [None, None])
    st            = cc.get("setup_time",      [None, None])
    sc            = cc.get("setup_cost",      [None, None])
    oc            = cc.get("operating_cost",  [None, None])

    if ppc[0] is None or ppc[0] < 1:
        err(f"configurations.producers_per_component[0] (min) must be >= 1  (got {ppc[0]})")
    if ppc[0] is not None and ppc[1] is not None and ppc[1] < ppc[0]:
        err(
            f"configurations.producers_per_component[1] (max) must be >= [0] (min)  "
            f"(got [{ppc[0]}, {ppc[1]}])"
        )

    # Processing time: either formula-based (assembly_type) or explicit range.
    _VALID_ASSEMBLY_TYPES = ("low", "medium", "high")
    if assembly_type is not None:
        if assembly_type not in _VALID_ASSEMBLY_TYPES:
            err(
                f"configurations.assembly_type must be one of "
                f"{list(_VALID_ASSEMBLY_TYPES)}  (got '{assembly_type}')"
            )
        if not isinstance(variation, (int, float)) or not (0.0 < variation < 1.0):
            err(
                f"configurations.variation must be a fraction in (0, 1)  "
                f"(got {variation})  — e.g. 0.10 for +-10%"
            )
    elif pt[0] is not None or pt[1] is not None:
        # Legacy explicit range still supported.
        _range("configurations.processing_time", pt[0], pt[1], pos=True)
    else:
        err(
            "configurations must specify either 'assembly_type' (formula-based) "
            "or 'processing_time' (explicit [min, max] range)"
        )

    _range("configurations.setup_time",     st[0], st[1])
    _range("configurations.setup_cost",     sc[0], sc[1])
    _range("configurations.operating_cost", oc[0], oc[1])

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

    # ── E-NEW-1: buffer_capacity must be >= max BOM edge quantity ─────────────
    # In the unit-rate model every component buffer can hold at most
    # buffer_capacity units.  A downstream workstation assembling one output
    # unit consumes bom.quantity[1] units from each input buffer.  If that
    # required quantity exceeds buffer_capacity, the input buffer can never
    # accumulate enough stock — the upstream producer fills it and goes BLOCKED
    # while the downstream stays STARVED.  This is an unrecoverable deadlock
    # that always produces zero throughput.
    if None not in (buffer_capacity, quantity[1]):
        if buffer_capacity < quantity[1]:
            err(
                f"simulation.buffer_capacity ({buffer_capacity}) < "
                f"bom.quantity max ({quantity[1]})  "
                f"— a downstream workstation needs up to {quantity[1]} units "
                f"from each input buffer to produce one output unit, but the "
                f"buffer caps at {buffer_capacity}.  The input buffer can never "
                f"accumulate enough stock: producer goes BLOCKED, consumer stays "
                f"STARVED — guaranteed deadlock.  "
                f"Set buffer_capacity >= bom.quantity[1] (>= {quantity[1]})."
            )

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

    # Derive pt range once — used by several warnings below.
    pt_min_h, pt_max_h = _pt_range(assembly_type, variation, pt, depth)

    # ── W1 — will all orders be released before the simulation ends? ───────────
    if None not in (n_ticks, n_orders, order_interarrival):
        ticks_to_release_all = n_orders * order_interarrival
        if n_ticks < ticks_to_release_all:
            warn(
                f"simulation.n_ticks ({n_ticks:,}) < n_orders ({n_orders}) x "
                f"order_interarrival ({order_interarrival}) = {ticks_to_release_all:,}  "
                f"— not all {n_orders} orders will be released before the "
                f"simulation ends.  Increase n_ticks to at least "
                f"{ticks_to_release_all:,} (plus processing time for the last order)."
            )

    # ── W3 — is total simulation time enough for even one order? ──────────────
    # Estimate: at each of 'depth' BOM levels, 'branching_max' different
    # component types must be produced, each needing 'qty_max' units, each
    # taking 'pt_max' hours.  This assumes a single workstation per level
    # (worst case / lower bound on parallelism).
    if None not in (tick_duration, n_ticks, depth, quantity[1], branching[1], pt_max_h, st[1]):
        branching_max = branching[1]
        qty_max       = quantity[1]
        # Sequential lower bound: depth levels × branching_max types × qty_max
        # units × pt_max per unit, plus one setup per level.
        est_one_order_h = depth * (st[1] + branching_max * qty_max * pt_max_h)
        total_sim_h     = n_ticks * tick_duration
        if total_sim_h < est_one_order_h:
            warn(
                f"Total simulation time ({total_sim_h:,.0f} h = "
                f"n_ticks {n_ticks:,} x tick_duration {tick_duration} h) "
                f"< estimated minimum for one order to complete "
                f"({est_one_order_h:,.0f} h).  "
                f"Estimate: depth {depth} x (setup_max {st[1]} h + "
                f"branching_max {branching_max} x qty_max {qty_max} x "
                f"pt_max {pt_max_h:.2f} h).  "
                f"With tick_duration {tick_duration} h this requires roughly "
                f"{math.ceil(est_one_order_h / tick_duration):,} ticks for "
                f"one order — zero throughput is almost certain."
            )

    # ── W4 — are machines so fragile they fail almost every tick? ─────────────
    if failures_enabled:
        wl_check = fail.get("weibull_lambda", [None, None])
        if None not in (tick_duration, wl_check[0]) and wl_check[0] < tick_duration * 10:
            warn(
                f"failures.weibull_lambda min ({wl_check[0]} h) is only "
                f"{wl_check[0] / tick_duration:.1f} ticks  "
                f"— machines will fail almost every tick; "
                f"simulation will degenerate into pure repair downtime"
            )

    # ── W5 — will producers_per_component[1] be silently clamped? ─────────────
    if None not in (n_ws, depth, ppc[1]) and depth >= 1:
        avg_ws_per_stage = n_ws / depth
        if ppc[1] > avg_ws_per_stage:
            warn(
                f"configurations.producers_per_component max ({ppc[1]}) > "
                f"average workstations per stage "
                f"({n_ws} / {depth} = {avg_ws_per_stage:.1f})  "
                f"— the upper bound will be silently clamped in stages with "
                f"fewer workstations than the requested max"
            )

    # ── W6 — BOM explosion very large: quote recommended n_ticks ──────────────
    # Compute the geometric sum of total non-raw component units per order.
    #
    # For one product, the full BOM explosion produces (worst case):
    #   sum_{l=1}^{depth} (branching_max * qty_max)^l  units across all levels
    #
    # Each unit takes ~pt_max / tick_duration ticks to process.  The resulting
    # ticks estimate is a sequential upper bound; real run time is shorter due
    # to parallel workstations and pipeline effects, but the ratio
    # (estimated / n_ticks) is a reliable indicator of under-sizing.
    if None not in (depth, branching[1], quantity[1], pt_max_h, tick_duration, n_ticks, n_orders):
        bq = branching[1] * quantity[1]        # fan-out factor per level
        if bq == 1:
            approx_units = depth
        else:
            approx_units = int(bq * (bq ** depth - 1) / (bq - 1))

        ticks_per_unit  = math.ceil(pt_max_h / tick_duration)
        est_one_order   = approx_units * ticks_per_unit   # sequential upper bound
        est_all_orders  = est_one_order * n_orders
        threshold_units = 1_000

        if approx_units > threshold_units and est_all_orders > n_ticks:
            warn(
                f"BOM explosion is large: ~{approx_units:,} component units "
                f"per order "
                f"(depth={depth}, branching_max={branching[1]}, qty_max={quantity[1]})."
                f"  At pt_max {pt_max_h:.2f} h/unit with tick_duration "
                f"{tick_duration} h, one order needs up to "
                f"~{est_one_order:,} ticks (sequential upper bound; "
                f"parallel workstations reduce this significantly).  "
                f"For {n_orders} orders: ~{est_all_orders:,} ticks.  "
                f"Current n_ticks={n_ticks:,} — consider increasing it."
            )

    # ── W7 — low machine availability ────────────────────────────────────────────
    #
    # For a Weibull failure distribution with shape β and scale λ (hours) the
    # mean time to failure is:
    #     MTTF = λ · Γ(1 + 1/β)
    #     (standard Weibull distribution expectation formula — not from H&S)
    #
    # The long-run availability is (Hopp & Spearman, Ch. 8):
    #     A = MTTF / (MTTF + MTTR_mean)
    #
    # The worst-case availability (most fragile machine) uses the smallest
    # possible MTTF and the largest possible MTTR:
    #     MTTF_min  = lambda_min · Γ(1 + 1/beta_max)
    #     A_worst   = MTTF_min / (MTTF_min + mttr_max)
    #
    # Warn when A_worst < 0.5 (machine spends more time under repair than
    # producing).  This is a much more precise signal than the old raw
    # comparison of MTTR vs λ.
    if failures_enabled:
        wb_check   = fail.get("weibull_beta",   [None, None])
        wl_check   = fail.get("weibull_lambda", [None, None])
        mttr_check = fail.get("mttr",           [None, None])
        if None not in (wb_check[1], wl_check[0], mttr_check[1]):
            try:
                mttf_min = wl_check[0] * math.gamma(1.0 + 1.0 / wb_check[1])
                a_worst  = mttf_min / (mttf_min + mttr_check[1])
                if a_worst < 0.5:
                    warn(
                        f"Low machine availability predicted for the worst-case "
                        f"workstation configuration.  "
                        f"Using Weibull parameters (lambda_min={wl_check[0]} h, "
                        f"beta_max={wb_check[1]}):  "
                        f"MTTF_min = lambda_min · Gamma(1 + 1/beta_max) "
                        f"= {mttf_min:.2f} h  [Weibull distribution formula].  "
                        f"With mttr_max={mttr_check[1]} h:  "
                        f"A_worst = MTTF / (MTTF + MTTR) = {a_worst:.2f}  "
                        f"[Hopp & Spearman, Ch. 8]  "
                        f"— machines with these parameters spend more than half "
                        f"their time under repair.  "
                        f"Throughput will be heavily reduced.  "
                        f"Consider increasing weibull_lambda[0] or "
                        f"reducing failures.mttr[1] so that A_worst >= 0.5."
                    )
            except (ValueError, ZeroDivisionError):
                pass   # skip if parameters are invalid (already caught by hard errors)

    # ── W8 — buffer too small relative to BOM fan-in (heavy blocking) ─────────
    # A downstream workstation assembling one output unit simultaneously consumes
    # qty_max units from each of branching_max input buffers.  Buffers for the
    # different input types fill up while sibling types are still being produced.
    # If buffer_capacity < branching_max * qty_max, those buffers will routinely
    # saturate and cause cascading BLOCKED states — even though it is not an
    # unrecoverable deadlock (covered by E-NEW-1).
    if None not in (buffer_capacity, branching[1], quantity[1]):
        fan_in = branching[1] * quantity[1]
        if buffer_capacity < fan_in:
            warn(
                f"simulation.buffer_capacity ({buffer_capacity}) < "
                f"bom.branching_max x bom.quantity_max "
                f"({branching[1]} x {quantity[1]} = {fan_in})  "
                f"— a downstream workstation assembling one unit needs up to "
                f"{quantity[1]} units of each of {branching[1]} input types "
                f"({fan_in} slots total across those buffers).  "
                f"Buffers for one input type will fill while sibling types are "
                f"still being produced, causing heavy BLOCKED time.  "
                f"Consider buffer_capacity >= {fan_in}."
            )

    # ── W9 — setup time dominates processing time ─────────────────────────────
    # When setup_time_max > 2 x pt_max, changeover overhead dominates the
    # machine's time budget.  This produces high setup costs, low processing
    # utilisation, and makes the scheduler's changeover-avoidance heuristic
    # highly consequential — a single wrong assignment can waste many hours.
    if None not in (st[1], pt_max_h) and pt_max_h > 0:
        if st[1] > 2 * pt_max_h:
            what = (
                f"assembly_type='{assembly_type}' at depth={depth} "
                f"-> pt_max ~{pt_max_h:.2f} h"
                if assembly_type else
                f"configurations.processing_time max = {pt[1]} h"
            )
            warn(
                f"configurations.setup_time max ({st[1]} h) > "
                f"2 x processing_time max ({pt_max_h:.2f} h)  "
                f"[{what}]  "
                f"— changeover overhead dominates the machine's time budget.  "
                f"Expect low processing utilisation and high sensitivity to "
                f"scheduling order.  Consider reducing setup_time or "
                f"increasing producers_per_component to reduce changeovers."
            )

    # ── W10 — sweep grid contains invalid (depth, workstations_count) pairs ───
    # Some combinations of swept depth and workstations_count values violate the
    # hard constraint depth <= workstations_count.  Those runs will raise a
    # ConfigError mid-sweep, aborting it partway through and producing
    # incomplete output files.
    if sweep:
        sweep_depths = _expand_sweep_param(sweep.get("depth"))
        sweep_wc     = _expand_sweep_param(sweep.get("workstations_count"))
        if sweep_depths and sweep_wc:
            invalid = [
                (int(d), int(wc))
                for d  in sweep_depths
                for wc in sweep_wc
                if wc < d
            ]
            if invalid:
                n_total   = len(sweep_depths) * len(sweep_wc)
                n_invalid = len(invalid)
                worst     = max(invalid, key=lambda p: p[0] - p[1])
                warn(
                    f"sweep grid contains {n_invalid} of {n_total} "
                    f"(depth, workstations_count) combinations where "
                    f"depth > workstations_count "
                    f"(e.g. depth={worst[0]}, workstations_count={worst[1]}).  "
                    f"These runs will raise a ConfigError at runtime, leaving "
                    f"the sweep output incomplete.  "
                    f"Ensure sweep.depth.max <= sweep.workstations_count.min, "
                    f"or tighten the ranges to exclude invalid combinations."
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
            f" {len(errors)} validation error(s) in config.yaml:\n{bullet_list}",
            errors,
            warnings,
        )

    if not warnings:
        print("  [validate_config] OK -- all checks passed.")

    return warnings
