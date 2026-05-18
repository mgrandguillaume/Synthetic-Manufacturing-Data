"""
Validation orchestrator for the Assembly Factory model.

Runs every validation check and writes a plain-text report.

Usage
-----
  # From model root:
  python -c "import sys; sys.path.insert(0,'validate'); from validate import validate; validate.run_all()"

  # More conveniently, via run.py:
  python run.py --validate        # generate → sweep → visualize → validate
  python run.py --validate-only   # validate only (no generate/sweep/visualize)
"""

from __future__ import annotations

import datetime
import os
import sys
import time

# ── Path setup ─────────────────────────────────────────────────────────────────
_MODEL_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, _MODEL_ROOT)

# ── Import validation modules ──────────────────────────────────────────────────
# (lazy imports so a broken sub-module doesn't crash the orchestrator)
from validate import conservation as conservation  # noqa: E402
from validate import boundary     as boundary      # noqa: E402
from validate import monotonicity as monotonicity  # noqa: E402
from validate import statistical  as statistical   # noqa: E402


# ── Formatting helpers ─────────────────────────────────────────────────────────

_PASS = "PASS"
_FAIL = "FAIL"
_SEP  = "─" * 72


def _fmt(results: list[tuple[str, bool, str]]) -> list[str]:
    lines: list[str] = []
    for name, passed, msg in results:
        label = _PASS if passed else _FAIL
        lines.append(f"  [{label}]  {name}")
        lines.append(f"         {msg}")
    return lines


# ── Public run_all function ────────────────────────────────────────────────────

def run_all(
    show_charts: bool = True,
    report_dir:  str  = None,
) -> bool:
    """
    Execute all validation checks and (optionally) show diagnostic charts.

    Parameters
    ----------
    show_charts
        If True, open the three diagnostic Plotly charts in the browser after
        the numerical checks finish.
    report_dir
        Directory in which to write ``validation_report.txt``.
        Defaults to ``<model_root>/validate/validation_output/``.

    Returns
    -------
    bool
        True if every check passed, False if any check failed.
    """
    if report_dir is None:
        report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "validation_output")
    os.makedirs(report_dir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []

    lines.append(_SEP)
    lines.append(f"  Validation Report — Assembly Factory Model")
    lines.append(f"  Generated: {timestamp}")
    lines.append(_SEP)

    all_passed = True

    # ── 1. Conservation laws ───────────────────────────────────────────────────
    lines.append("")
    lines.append("  1. Conservation Laws  (must never fail)")
    lines.append("")
    t0 = time.perf_counter()
    try:
        results = conservation.check()
    except Exception as exc:
        results = [("conservation_error", False, f"Exception: {exc}")]
    dt = time.perf_counter() - t0
    lines += _fmt(results)
    lines.append(f"     ({dt:.1f} s)")
    all_passed = all_passed and all(r[1] for r in results)

    # ── 2. Boundary / degenerate cases ────────────────────────────────────────
    lines.append("")
    lines.append("  2. Boundary / Degenerate Cases  (unit tests)")
    lines.append("")
    t0 = time.perf_counter()
    try:
        results = boundary.check()
    except Exception as exc:
        results = [("boundary_error", False, f"Exception: {exc}")]
    dt = time.perf_counter() - t0
    lines += _fmt(results)
    lines.append(f"     ({dt:.1f} s)")
    all_passed = all_passed and all(r[1] for r in results)

    # ── 3. Monotonicity ───────────────────────────────────────────────────────
    lines.append("")
    lines.append("  3. Monotonicity  (direction-of-effect tests)")
    lines.append("")
    t0 = time.perf_counter()
    try:
        results = monotonicity.check()
    except Exception as exc:
        results = [("monotonicity_error", False, f"Exception: {exc}")]
    dt = time.perf_counter() - t0
    lines += _fmt(results)
    lines.append(f"     ({dt:.1f} s)")
    all_passed = all_passed and all(r[1] for r in results)

    # ── 4. Statistical / theoretical ──────────────────────────────────────────
    lines.append("")
    lines.append("  4. Statistical / Theoretical  (Little's Law + availability)")
    lines.append("")
    t0 = time.perf_counter()
    try:
        results = statistical.check()
    except Exception as exc:
        results = [("statistical_error", False, f"Exception: {exc}")]
    dt = time.perf_counter() - t0
    lines += _fmt(results)
    lines.append(f"     ({dt:.1f} s)")
    all_passed = all_passed and all(r[1] for r in results)

    # ── Summary ───────────────────────────────────────────────────────────────
    lines.append("")
    lines.append(_SEP)
    lines.append(
        f"  Overall: {'ALL CHECKS PASSED' if all_passed else 'ONE OR MORE CHECKS FAILED'}"
    )
    lines.append(_SEP)

    # ── Print and write report ─────────────────────────────────────────────────
    report = "\n".join(lines)
    print(report)

    report_path = os.path.join(report_dir, "validation_report.txt")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report + "\n")
    print(f"\n  Report written to {report_path}")

    # ── Generate chart data and (optionally) show charts ─────────────────────────
    try:
        from validate import visualize_validation as _vv
        print("\n  Generating validation chart data…")
        _vv.generate_data(report_dir)
        if show_charts:
            print("  Rendering validation charts…")
            _vv.show(report_dir)
    except Exception as exc:
        print(f"  [WARN] Could not generate/render validation charts: {exc}")

    return all_passed
