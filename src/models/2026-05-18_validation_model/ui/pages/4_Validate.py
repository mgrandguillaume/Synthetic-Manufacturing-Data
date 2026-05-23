"""Validate page — run all validation checks and show the report."""

import os
import sys

import streamlit as st

# ── Path setup ─────────────────────────────────────────────────────────────────
_UI_DIR     = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_MODEL_ROOT = os.path.normpath(os.path.join(_UI_DIR, ".."))
if _UI_DIR     not in sys.path: sys.path.insert(0, _UI_DIR)
if _MODEL_ROOT not in sys.path: sys.path.insert(0, _MODEL_ROOT)

import state
state.setup_path()

from analysis.validate.validate             import run_all
from analysis.validate.visualize_validation import generate_data, show as val_show

_VALIDATE_DIR = os.path.join(_MODEL_ROOT, "analysis", "validate", "validation_output")
_REPORT_PATH  = os.path.join(_VALIDATE_DIR, "validation_report.txt")

# ── Page ───────────────────────────────────────────────────────────────────────
st.title("✅ Validate")
st.caption("Runs four test suites: Conservation Laws, Boundary Cases, Monotonicity, and Statistical checks.")

# ── Run button ─────────────────────────────────────────────────────────────────
if st.button("✅ Run validation", type="primary", use_container_width=True):
    with st.spinner("Running validation suite (runs several simulations)…"):
        passed = run_all(show_charts=False, report_dir=_VALIDATE_DIR)
    state.set("validate_done", True)
    state.set("validate_passed", passed)
    if passed:
        st.success("All checks passed.")
    else:
        st.error("One or more checks failed — see the report below.")

# ── Report ─────────────────────────────────────────────────────────────────────
if os.path.exists(_REPORT_PATH):
    with open(_REPORT_PATH) as f:
        report_text = f.read()

    passed = state.get("validate_passed")
    if passed is True:
        st.success("Overall: **ALL CHECKS PASSED**")
    elif passed is False:
        st.error("Overall: **ONE OR MORE CHECKS FAILED**")

    with st.expander("Full validation report", expanded=True):
        st.code(report_text, language=None)

    # ── Diagnostic charts ──────────────────────────────────────────────────────
    st.divider()
    st.subheader("Diagnostic charts")

    val_csvs = [os.path.join(_VALIDATE_DIR, f)
                for f in ["val_orders.csv", "val_buffers.csv", "val_availability.csv"]]

    if not all(os.path.exists(p) for p in val_csvs):
        with st.spinner("Generating chart data (runs three simulations)…"):
            generate_data(_VALIDATE_DIR)

    with st.spinner("Rendering charts…"):
        fig = val_show(_VALIDATE_DIR)
    st.plotly_chart(fig, use_container_width=True)

else:
    st.info("Click **Run validation** to generate the report.")
