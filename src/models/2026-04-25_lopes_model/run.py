#!/usr/bin/env python3
"""
Runner for the Lopes / CLEMATIS model.

Wires ModelGenerator → igraph.Graph → DynamicManufacturing and writes
the per-tick state counts to sim_output/states.csv.

Parameters
----------
Edit the block below to change the factory configuration.

Dependencies
------------
    pip install numpy python-igraph

Run
---
    python run.py
"""

import os
import csv
import igraph

from generate import ModelGenerator
from simulate import DynamicManufacturing

# ── Parameters ────────────────────────────────────────────────────────────────

N             = 10      # total number of workstations
S             = 0.5     # seriality  (0 = fully parallel, 1 = fully serial)
FAILURE_RATE  = 0.05    # P(failure per tick) — same for every workstation
BUFFER_SIZE   = 5       # buffer capacity between stations
N_TICKS       = 500     # number of simulation ticks to run
SEED          = 42      # random seed (None for non-reproducible)

# ── Output directory ──────────────────────────────────────────────────────────

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim_output")
os.makedirs(_DIR, exist_ok=True)

# ── 1. Generate factory graph ─────────────────────────────────────────────────

print(f"Generating factory  (n={N}, s={S})…")
gen = ModelGenerator(n=N, s=S, failure_rate=FAILURE_RATE, buffer_size=BUFFER_SIZE)
work_stations, edges, edge_attr, vertex_attr = gen.generate_graph()

n_steps = len(work_stations)
print(f"  Production steps : {n_steps}")
print(f"  Production rate  : {gen.production_rate:.4f} units/tick")
for step, nodes in work_stations.items():
    print(f"  Step {step}: workstations {nodes}")

# ── 2. Build igraph.Graph ─────────────────────────────────────────────────────
# ModelGenerator returns buffer_size on edges and does not include
# production_step in vertex_attr.  DynamicManufacturing needs both as
# vertex attributes, so we derive them here from the work_stations dict.

# Invert work_stations dict: node → step index
node_to_step = {}
for step, nodes in work_stations.items():
    for node in nodes:
        node_to_step[node] = step

g = igraph.Graph(n=N, directed=True)
g.add_edges(edges)

g.vs["label"]           = vertex_attr["label"]
g.vs["production_rate"] = vertex_attr["production_rate"]
g.vs["failure_rate"]    = vertex_attr["failure_rate"]
g.vs["production_step"] = [node_to_step[i] for i in range(N)]
g.vs["buffer_size"]     = [BUFFER_SIZE] * N   # uniform; DynamicManufacturing reads per-node

# Edge buffer_size kept for reference but not used by DynamicManufacturing.
g.es["buffer_size"] = edge_attr["buffer_size"]

print(f"\nGraph built: {g.vcount()} nodes, {g.ecount()} edges")

# ── 3. Run simulation ─────────────────────────────────────────────────────────

print(f"Running simulation  ({N_TICKS} ticks)…")
sim = DynamicManufacturing(network=g, seed=SEED)

rows = []   # collect (time, starved, blocked, working, total_production)

# Pass a dummy file object — we collect data in `rows` instead of writing
# to a plain text file so we can produce a proper CSV with a header.
import io
_dummy = io.StringIO()

for tick in range(N_TICKS):
    total_prod, n_starved, n_blocked, n_working, state_array = sim.iterate(
        _dummy, write2file=False
    )
    rows.append({
        "Tick":             tick + 1,
        "Starved":          n_starved,
        "Blocked":          n_blocked,
        "Working":          n_working,
        "TotalProduction":  round(total_prod, 6),
    })

# ── 4. Write CSV ──────────────────────────────────────────────────────────────

out_path = os.path.join(_DIR, "states.csv")
with open(out_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["Tick", "Starved", "Blocked", "Working", "TotalProduction"])
    writer.writeheader()
    writer.writerows(rows)

print(f"  Wrote {out_path}  ({len(rows):,} rows)")

# ── 5. Summary ────────────────────────────────────────────────────────────────

import statistics
total_produced  = sum(r["TotalProduction"] for r in rows)
mean_working    = statistics.mean(r["Working"]  for r in rows)
mean_starved    = statistics.mean(r["Starved"]  for r in rows)
mean_blocked    = statistics.mean(r["Blocked"]  for r in rows)

print(f"\nSimulation complete")
print(f"  Total production : {total_produced:.2f} units")
print(f"  Mean working     : {mean_working:.2f} / {N} workstations  "
      f"({100*mean_working/N:.1f}%)")
print(f"  Mean starved     : {mean_starved:.2f} / {N} workstations  "
      f"({100*mean_starved/N:.1f}%)")
print(f"  Mean blocked     : {mean_blocked:.2f} / {N} workstations  "
      f"({100*mean_blocked/N:.1f}%)")
print(f"\nResults → {_DIR}/")
