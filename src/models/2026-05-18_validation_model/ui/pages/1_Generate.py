"""Generate page — build a factory and inspect the result."""

import os
import sys

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yaml

# ── Path setup ─────────────────────────────────────────────────────────────────
_UI_DIR     = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_MODEL_ROOT = os.path.normpath(os.path.join(_UI_DIR, ".."))
if _UI_DIR     not in sys.path: sys.path.insert(0, _UI_DIR)
if _MODEL_ROOT not in sys.path: sys.path.insert(0, _MODEL_ROOT)

import state
state.setup_path()

from engine.generate.generate      import generate_simple_assembly, generate_from_params
from engine.generate.factory       import pt_range
from engine.generate.visualize_gen import build_html

# ── Page ───────────────────────────────────────────────────────────────────────
st.title("🏗️ Generate")

# ── Source selector ────────────────────────────────────────────────────────────
use_config = st.toggle("Use config.yaml values", value=True)

# ── Load config defaults ───────────────────────────────────────────────────────
with open(state.CONFIG_PATH) as f:
    cfg = yaml.safe_load(f)

bom  = cfg.get("bom", {})
ws   = cfg.get("workstations", {})
cc   = cfg.get("configurations", {})
lay  = cfg.get("layout", {})
meta = cfg.get("metadata", {})

# ── Parameter form (shown only in custom mode) ────────────────────────────────
if not use_config:
    st.subheader("Parameters")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**BOM**")
        n_products    = st.number_input("Products",       value=int(bom.get("n_products", 1)),   step=1, min_value=1)
        depth         = st.number_input("Depth",          value=int(bom.get("depth", 2)),        step=1, min_value=1)
        branch_lo     = st.number_input("Branching min",  value=int(bom.get("branching", [2,3])[0]), step=1, min_value=1)
        branch_hi     = st.number_input("Branching max",  value=int(bom.get("branching", [2,3])[1]), step=1, min_value=1)
        qty_lo        = st.number_input("Quantity min",   value=int(bom.get("quantity", [1,1])[0]),   step=1, min_value=1)
        qty_hi        = st.number_input("Quantity max",   value=int(bom.get("quantity", [1,1])[1]),   step=1, min_value=1)
        sharing_ratio = st.number_input("Sharing ratio",  value=float(bom.get("sharing_ratio", 0.0)),
                                        min_value=0.0, max_value=1.0, step=0.05, format="%.2f")

    with col2:
        st.markdown("**Workstations & Configurations**")
        n_ws          = st.number_input("Workstation count", value=int(ws.get("count", 4)),    step=1, min_value=1)
        prod_lo       = st.number_input("Producers / comp min", value=int(cc.get("producers_per_component", [1,2])[0]), step=1, min_value=1)
        prod_hi       = st.number_input("Producers / comp max", value=int(cc.get("producers_per_component", [1,2])[1]), step=1, min_value=1)
        assembly_type = st.selectbox("Assembly type", ["low", "medium", "high"],
                                     index=["low","medium","high"].index(cc.get("assembly_type","medium")))
        variation     = st.number_input("Processing-time variation (±)",
                                        value=float(cc.get("variation", 0.10)),
                                        min_value=0.0, max_value=1.0, step=0.01, format="%.2f")
        seed_val      = st.number_input("Seed (0 = random)", value=int(meta.get("seed") or 0), step=1, min_value=0)

    with st.expander("Cost & layout ranges"):
        c1, c2 = st.columns(2)
        st_lo  = c1.number_input("Setup time min (h)",   value=float(cc.get("setup_time",     [0.5, 2.0])[0]), step=0.1)
        st_hi  = c2.number_input("Setup time max (h)",   value=float(cc.get("setup_time",     [0.5, 2.0])[1]), step=0.1)
        sc_lo  = c1.number_input("Setup cost min",       value=float(cc.get("setup_cost",     [50,  300 ])[0]), step=10.0)
        sc_hi  = c2.number_input("Setup cost max",       value=float(cc.get("setup_cost",     [50,  300 ])[1]), step=10.0)
        oc_lo  = c1.number_input("Operating cost min",   value=float(cc.get("operating_cost", [2,   15  ])[0]), step=0.5)
        oc_hi  = c2.number_input("Operating cost max",   value=float(cc.get("operating_cost", [2,   15  ])[1]), step=0.5)
        cap_lo = c1.number_input("Flow capacity min",    value=float(lay.get("flow_capacity",  [50, 200])[0]), step=10.0)
        cap_hi = c2.number_input("Flow capacity max",    value=float(lay.get("flow_capacity",  [50, 200])[1]), step=10.0)
        cst_lo = c1.number_input("Transport cost min",   value=float(lay.get("transport_cost", [0.5, 5.0])[0]), step=0.1)
        cst_hi = c2.number_input("Transport cost max",   value=float(lay.get("transport_cost", [0.5, 5.0])[1]), step=0.1)

else:
    # Show a read-only summary of what will be used
    with st.expander("Active config.yaml parameters", expanded=False):
        st.json({
            "n_products": bom.get("n_products"),
            "depth":      bom.get("depth"),
            "branching":  bom.get("branching"),
            "quantity":   bom.get("quantity"),
            "sharing_ratio": bom.get("sharing_ratio"),
            "workstations_count": ws.get("count"),
            "assembly_type": cc.get("assembly_type"),
            "variation": cc.get("variation"),
            "seed": meta.get("seed"),
        })

# ── Generate button ────────────────────────────────────────────────────────────
st.divider()
if st.button("🏗️ Generate factory", type="primary", use_container_width=True):
    with st.spinner("Generating factory…"):
        if use_config:
            result = generate_simple_assembly(state.CONFIG_PATH, export_csv=True)
        else:
            params = {
                "n_products":              int(n_products),
                "depth":                   int(depth),
                "branching":               [int(branch_lo), int(branch_hi)],
                "quantity":                [int(qty_lo),    int(qty_hi)],
                "sharing_ratio":           float(sharing_ratio),
                "workstations_count":      int(n_ws),
                "producers_per_component": [int(prod_lo), int(prod_hi)],
                "processing_time":         pt_range(assembly_type, int(depth), float(variation)),
                "setup_time":              [float(st_lo), float(st_hi)],
                "setup_cost":              [float(sc_lo), float(sc_hi)],
                "operating_cost":          [float(oc_lo), float(oc_hi)],
                "flow_capacity":           [float(cap_lo), float(cap_hi)],
                "transport_cost":          [float(cst_lo), float(cst_hi)],
                "seed":                    int(seed_val) if seed_val != 0 else None,
            }
            result = generate_from_params(params, export_csv=False)

    state.set("gen_result", result)
    st.success("Factory generated.")

# ── Display results ────────────────────────────────────────────────────────────
result = state.get("gen_result")
if result is None:
    st.info("Click **Generate factory** to build a factory.")
    st.stop()

st.divider()
st.subheader("Summary")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Components",    len(result["components"]))
m2.metric("BOM edges",     len(result["bom_edges"]))
m3.metric("Workstations",  len(result["workstations"]))
m4.metric("Configurations",len(result["configurations"]))
m5.metric("Layout edges",  len(result["layout_edges"]))

tab_comp, tab_cfg, tab_bom, tab_ws = st.tabs(
    ["Components", "Configurations", "BOM edges", "Workstations"])

with tab_comp:
    st.dataframe(pd.DataFrame([
        {"ID": c.id, "Name": c.name, "Level": c.level, "IsProduct": c.is_product}
        for c in result["components"]
    ]), use_container_width=True, height=400)

with tab_cfg:
    st.dataframe(pd.DataFrame([
        {"ID": c.id, "Workstation": c.workstation, "Component": c.component,
         "ProcessingTime": round(c.processing_time, 4), "SetupTime": round(c.setup_time, 4),
         "SetupCost": round(c.setup_cost, 2), "OperatingCost": round(c.operating_cost, 2)}
        for c in result["configurations"]
    ]), use_container_width=True, height=400)

with tab_bom:
    st.dataframe(pd.DataFrame([
        {"Input": e.input, "Output": e.output, "Quantity": e.quantity}
        for e in result["bom_edges"]
    ]), use_container_width=True, height=400)

with tab_ws:
    st.dataframe(pd.DataFrame([
        {"ID": w.id, "Name": w.name, "Type": w.type}
        for w in result["workstations"]
    ]), use_container_width=True)

# ── Factory layout graph ───────────────────────────────────────────────────────
st.divider()
st.subheader("Factory layout")
components.html(build_html(result, height="600px"), height=620, scrolling=False)
