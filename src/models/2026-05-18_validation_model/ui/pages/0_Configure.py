"""
Config editor page — read and write config.yaml through the UI.

Note: PyYAML does not preserve inline comments when writing the file.
All parameter values are preserved exactly; only comments are stripped.
"""

import os
import sys

import streamlit as st
import yaml

# ── Path setup ─────────────────────────────────────────────────────────────────
_UI_DIR     = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_MODEL_ROOT = os.path.normpath(os.path.join(_UI_DIR, ".."))
if _UI_DIR     not in sys.path: sys.path.insert(0, _UI_DIR)
if _MODEL_ROOT not in sys.path: sys.path.insert(0, _MODEL_ROOT)

import state
import ui_theme

# ── Page ───────────────────────────────────────────────────────────────────────
ui_theme.apply(
    title   = "Configure",
    eyebrow = f"project · configure · {state.CONFIG_PATH}",
)
st.caption(
    "Inline comments in config.yaml are stripped on save (PyYAML limitation). "
    "All values are preserved."
)

# ── Load current config ────────────────────────────────────────────────────────
with open(state.CONFIG_PATH, "r") as f:
    cfg = yaml.safe_load(f)


# ── Helper for [min, max] range fields ────────────────────────────────────────
def _range_row(label: str, key_lo: str, key_hi: str,
               lo_default: float, hi_default: float,
               is_int: bool = False, step: float = 0.1) -> None:
    c1, c2 = st.columns(2)
    if is_int:
        c1.number_input(f"{label} — min", key=key_lo, value=int(lo_default))
        c2.number_input(f"{label} — max", key=key_hi, value=int(hi_default))
    else:
        c1.number_input(f"{label} — min", key=key_lo, value=float(lo_default), step=step, format="%.4g")
        c2.number_input(f"{label} — max", key=key_hi, value=float(hi_default), step=step, format="%.4g")


# ── Tabs ───────────────────────────────────────────────────────────────────────
bom  = cfg.get("bom", {})
ws   = cfg.get("workstations", {})
cc   = cfg.get("configurations", {})
lay  = cfg.get("layout", {})
sim  = cfg.get("simulation", {})
fail = cfg.get("failures", {})
meta = cfg.get("metadata", {})
out  = cfg.get("output", {})

tabs = st.tabs([
    "bom", "workstations", "configurations",
    "layout", "simulation", "failures",
    "sweep", "metadata · output",
])

# ── Tab 0: BOM ────────────────────────────────────────────────────────────────
with tabs[0]:
    ui_theme.section("Bill of materials", meta="bom.*")
    c1, c2 = st.columns(2)
    c1.number_input("Number of products", key="bom_n_products", value=int(bom.get("n_products", 1)), step=1, min_value=1)
    c2.number_input("BOM depth",          key="bom_depth",      value=int(bom.get("depth", 2)),      step=1, min_value=1)
    _range_row("Branching (children per node)", "bom_branch_lo", "bom_branch_hi",
               bom.get("branching", [2, 3])[0], bom.get("branching", [2, 3])[1], is_int=True)
    _range_row("Quantity per BOM edge", "bom_qty_lo", "bom_qty_hi",
               bom.get("quantity", [1, 1])[0], bom.get("quantity", [1, 1])[1], is_int=True)
    st.number_input("Sharing ratio  (0 = no sharing, 1 = always reuse)",
                    key="bom_sharing", value=float(bom.get("sharing_ratio", 0.0)),
                    min_value=0.0, max_value=1.0, step=0.05, format="%.2f")

# ── Tab 1: Workstations ───────────────────────────────────────────────────────
with tabs[1]:
    ui_theme.section("Workstations", meta="workstations.*")
    st.number_input("Assembly workstation count", key="ws_count",
                    value=int(ws.get("count", 4)), step=1, min_value=1)
    use_stage_balance = st.checkbox(
        "Custom stage balance (Dirichlet concentration)",
        key="ws_use_stage_balance",
        value=ws.get("stage_balance") is not None,
    )
    st.number_input(
        "Stage balance  (null = uniform; high ≥ 5 = near-uniform; low ≤ 0.5 = skewed)",
        key="ws_stage_balance",
        value=float(ws.get("stage_balance") or 1.0),
        min_value=0.01, step=0.5, format="%.2f",
        disabled=not use_stage_balance,
    )

# ── Tab 2: Configurations ─────────────────────────────────────────────────────
with tabs[2]:
    ui_theme.section("Configurations", meta="configurations.*")
    st.selectbox("Assembly type  (sets processing-time formula)",
                 ["low", "medium", "high"], key="cfg_assembly_type",
                 index=["low", "medium", "high"].index(cc.get("assembly_type", "medium")))
    st.number_input("Variation  (±fraction around formula mean)",
                    key="cfg_variation", value=float(cc.get("variation", 0.10)),
                    min_value=0.0, max_value=1.0, step=0.01, format="%.2f")
    _range_row("Producers per component", "cfg_prod_lo", "cfg_prod_hi",
               cc.get("producers_per_component", [1, 2])[0],
               cc.get("producers_per_component", [1, 2])[1], is_int=True)
    st.divider()
    _range_row("Setup time (h)",   "cfg_st_lo", "cfg_st_hi",
               cc.get("setup_time",     [0.5, 2.0])[0], cc.get("setup_time",     [0.5, 2.0])[1])
    _range_row("Setup cost",       "cfg_sc_lo", "cfg_sc_hi",
               cc.get("setup_cost",     [50,  300 ])[0], cc.get("setup_cost",     [50,  300 ])[1], step=1.0)
    _range_row("Operating cost",   "cfg_oc_lo", "cfg_oc_hi",
               cc.get("operating_cost", [2,   15  ])[0], cc.get("operating_cost", [2,   15  ])[1], step=0.5)

# ── Tab 3: Layout ─────────────────────────────────────────────────────────────
with tabs[3]:
    ui_theme.section("Layout", meta="layout.*")
    _range_row("Flow capacity",  "lay_cap_lo",  "lay_cap_hi",
               lay.get("flow_capacity",  [50, 200])[0], lay.get("flow_capacity",  [50, 200])[1], step=5.0)
    _range_row("Transport cost", "lay_cost_lo", "lay_cost_hi",
               lay.get("transport_cost", [0.5, 5.0])[0], lay.get("transport_cost", [0.5, 5.0])[1])

# ── Tab 4: Simulation ─────────────────────────────────────────────────────────
with tabs[4]:
    ui_theme.section("Simulation", meta="simulation.*")
    c1, c2 = st.columns(2)
    c1.number_input("Number of orders",           key="sim_n_orders",  value=int(sim.get("n_orders", 10)),             step=1,   min_value=1)
    c2.number_input("Max ticks",                  key="sim_n_ticks",   value=int(sim.get("n_ticks", 3000)),            step=100, min_value=100)
    c1.number_input("Tick duration (h)",          key="sim_tick",      value=float(sim.get("tick_duration", 0.05)),    step=0.01,format="%.4f", min_value=0.001)
    c2.number_input("Buffer capacity",            key="sim_buf",       value=int(sim.get("buffer_capacity", 20)),      step=1,   min_value=1)
    c1.number_input("Order interarrival (ticks)", key="sim_interarr",  value=int(sim.get("order_interarrival", 10)),  step=1,   min_value=1)

# ── Tab 5: Failures ───────────────────────────────────────────────────────────
with tabs[5]:
    ui_theme.section("Machine failures (Weibull)", meta="failures.*")
    st.toggle("Enable failures", key="fail_enabled", value=bool(fail.get("enabled", False)))
    st.divider()
    _range_row("Weibull β (shape)",    "fail_beta_lo",  "fail_beta_hi",
               fail.get("weibull_beta",   [1.5, 3.0])[0], fail.get("weibull_beta",   [1.5, 3.0])[1])
    _range_row("Weibull λ (scale, h)", "fail_lam_lo",   "fail_lam_hi",
               fail.get("weibull_lambda", [20,  50 ])[0], fail.get("weibull_lambda", [20,  50 ])[1], step=1.0)
    _range_row("MTTR (h)",             "fail_mttr_lo",  "fail_mttr_hi",
               fail.get("mttr",          [0.5, 4.0])[0], fail.get("mttr",          [0.5, 4.0])[1])
    _range_row("Repair cost",          "fail_rc_lo",    "fail_rc_hi",
               fail.get("repair_cost",   [100, 500])[0], fail.get("repair_cost",   [100, 500])[1], step=10.0)

# ── Tab 6: Sweep ──────────────────────────────────────────────────────────────
with tabs[6]:
    ui_theme.section("Sweep grid", meta="sweep.*")
    st.markdown("""
Each parameter can be:
- **scalar** — `n_products: 5`
- **list** — `depth: [1, 2, 3]`
- **range** — `depth: {min: 1, max: 8, step: 1}`
""")
    sweep_yaml_str = yaml.dump(cfg.get("sweep", {}), default_flow_style=False, sort_keys=True)
    st.text_area("Sweep parameters (YAML)", key="sweep_raw", value=sweep_yaml_str, height=200)

# ── Tab 7: Metadata & Output ──────────────────────────────────────────────────
with tabs[7]:
    ui_theme.section("Metadata", meta="metadata.*")
    st.text_input("Factory name", key="meta_name", value=str(meta.get("name", "simple_assembly_factory")))
    use_seed = st.checkbox("Fixed seed (reproducible)", key="meta_use_seed",
                           value=meta.get("seed") is not None)
    st.number_input("Seed value", key="meta_seed",
                    value=int(meta.get("seed") or 42), step=1,
                    disabled=not use_seed)
    st.divider()
    ui_theme.section("Output", meta="output.*")
    st.text_input("Output directory (relative or absolute)",
                  key="out_dir", value=str(out.get("directory", "gen_output")))

# ── Save button ────────────────────────────────────────────────────────────────
st.divider()
if st.button("Save config", type="primary", use_container_width=True):
    s = st.session_state
    try:
        sweep_parsed = yaml.safe_load(s["sweep_raw"])
        if not isinstance(sweep_parsed, dict):
            st.error("Sweep section must be a YAML mapping. Fix the text above and try again.")
            st.stop()

        new_cfg = {
            "metadata": {
                "name": s["meta_name"],
                "seed": int(s["meta_seed"]) if s["meta_use_seed"] else None,
            },
            "bom": {
                "n_products":    int(s["bom_n_products"]),
                "depth":         int(s["bom_depth"]),
                "branching":     [int(s["bom_branch_lo"]), int(s["bom_branch_hi"])],
                "quantity":      [int(s["bom_qty_lo"]),    int(s["bom_qty_hi"])],
                "sharing_ratio": float(s["bom_sharing"]),
            },
            "workstations": {
                "count":         int(s["ws_count"]),
                "stage_balance": float(s["ws_stage_balance"]) if s["ws_use_stage_balance"] else None,
            },
            "configurations": {
                "producers_per_component": [int(s["cfg_prod_lo"]), int(s["cfg_prod_hi"])],
                "assembly_type": s["cfg_assembly_type"],
                "variation":     float(s["cfg_variation"]),
                "setup_time":    [float(s["cfg_st_lo"]),  float(s["cfg_st_hi"])],
                "setup_cost":    [float(s["cfg_sc_lo"]),  float(s["cfg_sc_hi"])],
                "operating_cost":[float(s["cfg_oc_lo"]),  float(s["cfg_oc_hi"])],
            },
            "layout": {
                "flow_capacity":  [float(s["lay_cap_lo"]),  float(s["lay_cap_hi"])],
                "transport_cost": [float(s["lay_cost_lo"]), float(s["lay_cost_hi"])],
            },
            "simulation": {
                "tick_duration":      float(s["sim_tick"]),
                "buffer_capacity":    int(s["sim_buf"]),
                "order_interarrival": int(s["sim_interarr"]),
                "n_ticks":            int(s["sim_n_ticks"]),
                "n_orders":           int(s["sim_n_orders"]),
            },
            "failures": {
                "enabled":        bool(s["fail_enabled"]),
                "weibull_beta":   [float(s["fail_beta_lo"]),  float(s["fail_beta_hi"])],
                "weibull_lambda": [float(s["fail_lam_lo"]),   float(s["fail_lam_hi"])],
                "mttr":           [float(s["fail_mttr_lo"]),  float(s["fail_mttr_hi"])],
                "repair_cost":    [float(s["fail_rc_lo"]),    float(s["fail_rc_hi"])],
            },
            "sweep":  sweep_parsed,
            "output": {"directory": s["out_dir"]},
        }

        with open(state.CONFIG_PATH, "w") as f:
            yaml.dump(new_cfg, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False)

        st.success("Config saved.")

    except Exception as exc:
        st.error(f"Failed to save config: {exc}")
