#!/usr/bin/env python3
"""
Public API for the Assembly Factory generator.

Two entry points are provided:

  generate_simple_assembly(config_path, export_csv=True)
      Read parameters from a YAML config file and generate a factory.
      Writes five CSVs to the output directory specified in the config.

  generate_from_params(params, export_csv=False, out_dir=None)
      Generate a factory from a parameter dictionary.
      Intended for programmatic use (e.g. parameter sweeps).

Run standalone:  python generate.py   (reads config.yaml two levels up)
"""

from __future__ import annotations

import os
import random
import sys

# ── Path setup ─────────────────────────────────────────────────────────────────
_HERE       = os.path.dirname(os.path.abspath(__file__))
_MODEL_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _MODEL_ROOT not in sys.path:
    sys.path.insert(0, _MODEL_ROOT)

from shared_utils import utils                  # noqa: E402
from engine.generate import factory             # noqa: E402
from engine.generate.models import write_csvs   # noqa: E402


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_simple_assembly(config_path: str, export_csv: bool = True) -> dict:
    """
    Generate a factory from a YAML config file.

    Reads the config, resolves the processing-time range (formula-based or
    explicit), then delegates to generate_from_params.  When export_csv=True,
    five CSV files are written to cfg["output"]["directory"].

    Returns
    -------
    dict with keys: components, bom_edges, workstations, configurations,
                    layout_edges, producible, out_dir
    """
    cfg = utils.load_config(config_path)

    from shared_utils import validate_config
    validate_config.validate(cfg)

    bom = cfg["bom"]
    ws  = cfg["workstations"]
    cc  = cfg["configurations"]
    lay = cfg["layout"]

    # Resolve processing-time range: formula-based or legacy explicit range.
    if "assembly_type" in cc:
        pt_r = factory.pt_range(
            assembly_type = cc["assembly_type"],
            depth         = bom["depth"],
            variation     = cc.get("variation", 0.10),
        )
    else:
        pt_r = cc["processing_time"]

    params = {
        "seed":                    cfg["metadata"].get("seed"),
        "n_products":              bom["n_products"],
        "depth":                   bom["depth"],
        "branching":               bom["branching"],
        "quantity":                bom["quantity"],
        "sharing_ratio":           bom.get("sharing_ratio", 0.0),
        "workstations_count":      ws["count"],
        "stage_balance":           ws.get("stage_balance", None),
        "producers_per_component": cc["producers_per_component"],
        "processing_time":         pt_r,
        "setup_time":              cc["setup_time"],
        "setup_cost":              cc["setup_cost"],
        "operating_cost":          cc["operating_cost"],
        "flow_capacity":           lay["flow_capacity"],
        "transport_cost":          lay["transport_cost"],
    }

    out_dir = None
    if export_csv:
        rel        = cfg["output"]["directory"]
        script_dir = os.path.dirname(os.path.abspath(__file__))
        out_dir    = rel if os.path.isabs(rel) else os.path.normpath(
            os.path.join(script_dir, rel))

    return generate_from_params(params, export_csv=export_csv, out_dir=out_dir)


def generate_from_params(params: dict, export_csv: bool = False,
                         out_dir: str | None = None) -> dict:
    """
    Generate a factory from a parameter dictionary.

    Expected keys
    -------------
    n_products, depth, branching, quantity, sharing_ratio,
    workstations_count, producers_per_component,
    processing_time, setup_time, setup_cost, operating_cost,
    flow_capacity, transport_cost

    Optional keys
    -------------
    seed          (int | None)
    stage_balance (float | None) — Dirichlet concentration for stage sizing;
                                   None = uniform floor-based split (default)

    Returns
    -------
    dict with keys: components, bom_edges, workstations, configurations,
                    layout_edges, producible, out_dir
    """
    seed = params.get("seed")
    if seed is not None:
        random.seed(seed)

    result = factory.build_factory(
        n_products    = params["n_products"],
        depth         = params["depth"],
        branch_min    = params["branching"][0],
        branch_max    = params["branching"][1],
        qty_min       = params["quantity"][0],
        qty_max       = params["quantity"][1],
        sharing_ratio = params.get("sharing_ratio", 0.0),
        n_ws          = params["workstations_count"],
        prod_min      = params["producers_per_component"][0],
        prod_max      = params["producers_per_component"][1],
        pt_r          = params["processing_time"],
        st_r          = params["setup_time"],
        sc_r          = params["setup_cost"],
        oc_r          = params["operating_cost"],
        cap_r         = params["flow_capacity"],
        cost_r        = params["transport_cost"],
        stage_balance = params.get("stage_balance", None),
    )

    # ── Validate generated output ──────────────────────────────────────────────
    from engine.generate.validate_output import validate as _validate_generate
    _validate_generate(result)

    if export_csv and out_dir:
        write_csvs(result, out_dir)
        result["out_dir"] = out_dir
    else:
        result["out_dir"] = None

    return result


# ── Script entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    script_dir  = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.normpath(os.path.join(script_dir, "..", "..", "config.yaml"))
    result = generate_simple_assembly(config_path)
    print(f"Config:         {config_path}")
    print(f"Components:     {len(result['components'])}")
    print(f"BOM edges:      {len(result['bom_edges'])}")
    print(f"Workstations:   {len(result['workstations'])}")
    print(f"Configurations: {len(result['configurations'])}")
    print(f"Layout edges:   {len(result['layout_edges'])}")
    print(f"Exported ->     {result['out_dir']}")
