"""
Verification orchestrator for the Assembly Factory model.

Runs every verification check and writes a plain-text report.

Usage
-----
  # From model root:
  python -c "import sys; sys.path.insert(0,'analysis/model_verification'); from verification import run_all; run_all()"

  # More conveniently, via run.py:
  python run.py --verify        # generate → sweep → visualize → verify
  python run.py --verify-only   # verify only (no generate/sweep/visualize)
"""

from __future__ import annotations

import datetime
import os
import sys
import time

import pandas as pd

# ── Path setup ─────────────────────────────────────────────────────────────────
_MODEL_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, _MODEL_ROOT)

# ── Import validation modules ──────────────────────────────────────────────────
# (lazy imports so a broken sub-module doesn't crash the orchestrator)
from . import conservation  # noqa: E402
from . import boundary      # noqa: E402
from . import monotonicity  # noqa: E402
from . import statistical   # noqa: E402


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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save_monotonicity_csv(
    results_with_data: list[tuple[str, bool, str, dict]],
    output_dir: str,
) -> None:
    """Flatten monotonicity plot_data into a tidy CSV for the UI chart."""
    rows = []
    for name, passed, _msg, plot_data in results_with_data:
        for x, y in zip(plot_data["x_values"], plot_data["y_values"]):
            rows.append({
                "test_name": name,
                "title":     plot_data["title"],
                "x_label":   plot_data["x_label"],
                "y_label":   plot_data["y_label"],
                "x_value":   x,
                "y_value":   y,
                "direction": plot_data["direction"],
                "passed":    passed,
            })
    pd.DataFrame(rows).to_csv(
        os.path.join(output_dir, "val_monotonicity.csv"), index=False
    )


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
        Directory in which to write ``verification_report.txt``.
        Defaults to ``<model_root>/analysis/model_verification/verification_output/``.

    Returns
    -------
    bool
        True if every check passed, False if any check failed.
    """
    if report_dir is None:
        report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "verification_output")
    os.makedirs(report_dir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []

    lines.append(_SEP)
    lines.append(f"  Verification Report — Assembly Factory Model")
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
    lines.append("     zero orders · single order · large buffer · large λ · "
                 "full sharing · deterministic · order cycling · BOM component count")
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
    lines.append("     more workstations · larger buffer · more orders · "
                 "higher branching · higher BOM quantity")
    lines.append("")
    t0 = time.perf_counter()
    try:
        mono_with_data = monotonicity.check_with_data()
        results        = [(n, p, m) for n, p, m, _ in mono_with_data]
        _save_monotonicity_csv(mono_with_data, report_dir)
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

    report_path = os.path.join(report_dir, "verification_report.txt")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report + "\n")
    print(f"\n  Report written to {report_path}")

    # ── Generate chart data and (optionally) show charts ─────────────────────────
    try:
        from . import visualize_verification as _vv
        print("\n  Generating validation chart data…")
        _vv.generate_data(report_dir)
        if show_charts:
            print("  Rendering validation charts…")
            _vv.show(report_dir)
    except Exception as exc:
        print(f"  [WARN] Could not generate/render validation charts: {exc}")

    return all_passed
