"""
Data models for the Assembly Factory generator.

Defines the five dataclasses that represent a factory, plus the helper
that serialises them to CSV files.

    Component     — a BOM node (raw material, sub-assembly, or product)
    BomEdge       — a directed dependency in the Bill of Materials
    Workstation   — a physical station (source, production, or sink)
    Configuration — one workstation × component production recipe
    LayoutEdge    — a physical transport link between two workstations

    write_csvs(result, out_dir) — write all five tables to CSV
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class Component:
    id:         str
    name:       str
    level:      int
    is_product: bool


@dataclass
class BomEdge:
    input:    str
    output:   str
    quantity: int


@dataclass
class Workstation:
    id:   str
    name: str
    type: str


@dataclass
class Configuration:
    id:              str
    workstation:     str
    component:       str
    processing_time: float
    setup_time:      float
    setup_cost:      float
    operating_cost:  float


@dataclass
class LayoutEdge:
    origin:      str
    destination: str
    capacity:    float
    cost:        float


# ── CSV export ─────────────────────────────────────────────────────────────────

def write_csvs(result: dict, out_dir: str) -> None:
    """
    Write the five factory tables to CSV files in out_dir.

    Files written
    -------------
    components.csv, bom.csv, workstations.csv, configurations.csv, layout.csv
    """
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "components.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Name", "Level", "IsProduct"])
        for c in result["components"]:
            w.writerow([c.id, c.name, c.level, c.is_product])

    with open(os.path.join(out_dir, "bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Input", "Output", "Quantity"])
        for e in result["bom_edges"]:
            w.writerow([e.input, e.output, e.quantity])

    with open(os.path.join(out_dir, "workstations.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Name", "Type"])
        for ws in result["workstations"]:
            w.writerow([ws.id, ws.name, ws.type])

    with open(os.path.join(out_dir, "configurations.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Workstation", "Component",
                    "ProcessingTime", "SetupTime", "SetupCost", "OperatingCost"])
        for c in result["configurations"]:
            w.writerow([c.id, c.workstation, c.component,
                        c.processing_time, c.setup_time, c.setup_cost, c.operating_cost])

    with open(os.path.join(out_dir, "layout.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Origin", "Destination", "Capacity", "Cost"])
        for e in result["layout_edges"]:
            w.writerow([e.origin, e.destination, e.capacity, e.cost])
