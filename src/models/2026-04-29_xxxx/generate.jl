#!/usr/bin/env julia
# Simple Assembly Factory — synthetic data generator.
# Builds an assembly-line factory from a YAML config and writes CSVs.
# Install Julia, then use the following command to instal the necessary packages:
# ] add YAML CSV Random DataFrames
#
# Run:    julia generate.jl
# Use:    include(...); result = generate_simple_assembly("config.yaml")

using YAML, Random, CSV, DataFrames

"""
    generate_simple_assembly(config_path; export_csv=true) -> NamedTuple

Returns `(components, bom_edges, workstations, configurations, layout_edges,
producible, out_dir)`. When `export_csv=true`, also writes 5 CSV files
(`components.csv`, `bom.csv`, `workstations.csv`, `configurations.csv`,
`layout.csv`) to `cfg["output"]["directory"]`.
"""
function generate_simple_assembly(config_path::String; export_csv::Bool=true)
    cfg = YAML.load_file(config_path)
    seed = get(cfg["metadata"], "seed", nothing)
    isnothing(seed) || Random.seed!(seed)

    # --- BOM ---------------------------------------------------------------
    bom = cfg["bom"]
    n_products             = bom["n_products"]
    depth                  = bom["depth"]
    branch_min, branch_max = bom["branching"]
    qty_min, qty_max       = bom["quantity"]
    sharing_ratio          = get(bom, "sharing_ratio", 0.0)

    @assert n_products ≥ 1   "bom.n_products must be ≥ 1"
    @assert depth ≥ 1        "bom.depth must be ≥ 1"
    @assert branch_min ≥ 1   "bom.branching[1] must be ≥ 1"
    @assert branch_max ≥ branch_min "bom.branching range invalid"

    components = Vector{NamedTuple{(:id,:name,:level,:is_product),
                                   Tuple{Symbol,String,Int,Bool}}}()
    bom_edges = Vector{NamedTuple{(:input,:output,:quantity),
                                  Tuple{Symbol,Symbol,Int}}}()
    producible  = Symbol[]
    shared_pool = Dict{Int, Vector{Symbol}}()
    counter     = Dict{Int, Int}()

    function build_subtree!(parent_id::Symbol, parent_level::Int)
        parent_level <= 0 && return
        child_level = parent_level - 1
        for _ in 1:rand(branch_min:branch_max)
            pool = get(shared_pool, child_level, Symbol[])
            if !isempty(pool) && rand() < sharing_ratio
                child = rand(pool)                         # reuse subtree
            else
                counter[child_level] = get(counter, child_level, 0) + 1
                n = counter[child_level]
                prefix = child_level == 0 ? "RAW" : "COMP"
                child  = Symbol("$(prefix)_L$(child_level)_$n")
                push!(components, (id=child, name="$prefix L$child_level #$n",
                                   level=child_level, is_product=false))
                push!(get!(shared_pool, child_level, Symbol[]), child)
                child_level > 0 && push!(producible, child)
                build_subtree!(child, child_level)
            end
            push!(bom_edges, (input=child, output=parent_id,
                              quantity=rand(qty_min:qty_max)))
        end
    end

    for p in 1:n_products
        pid = Symbol("PROD_$p")
        push!(components, (id=pid, name="Product $p", level=depth, is_product=true))
        push!(producible, pid)
        build_subtree!(pid, depth)
    end

    # --- Workstations (all assembly) --------------------------------------
    ws_cfg = cfg["workstations"]
    n_ws   = ws_cfg["count"]
    @assert n_ws ≥ 1 "workstations.count must be ≥ 1"

    workstations = Vector{NamedTuple{(:id,:name,:type),
                                     Tuple{Symbol,String,Symbol}}}()
    push!(workstations, (id=:Inv, name="Inventory",          type=:source))
    push!(workstations, (id=:QI,  name="Quality Inspection", type=:sink))

    assembly_ws = Symbol[]
    for i in 1:n_ws
        id = Symbol("WS_$i")
        push!(workstations, (id=id, name="Assembly $i", type=:production))
        push!(assembly_ws, id)
    end

    # --- Configurations ----------------------------------------------------
    ccfg = cfg["configurations"]
    prod_min, prod_max = ccfg["producers_per_component"]
    pt_r = ccfg["processing_time"]
    st_r = ccfg["setup_time"]
    sc_r = ccfg["setup_cost"]
    oc_r = ccfg["operating_cost"]

    @assert prod_min ≥ 1 "configurations.producers_per_component[1] must be ≥ 1"
    prod_min = min(prod_min, n_ws)
    prod_max = clamp(prod_max, prod_min, n_ws)

    usample(r) = rand() * (r[2] - r[1]) + r[1]

    configurations = Vector{NamedTuple{
        (:id,:workstation,:component,:processing_time,:setup_time,
         :setup_cost,:operating_cost),
        Tuple{Symbol,Symbol,Symbol,Float64,Float64,Float64,Float64}}}()

    cfg_idx = 0
    for comp in producible
        n = rand(prod_min:prod_max)
        for ws in shuffle(assembly_ws)[1:n]
            cfg_idx += 1
            push!(configurations, (
                id=Symbol("CFG_$cfg_idx"), workstation=ws, component=comp,
                processing_time=usample(pt_r), setup_time=usample(st_r),
                setup_cost=usample(sc_r),     operating_cost=usample(oc_r)))
        end
    end

    # --- Layout ------------------------------------------------------------
    # parallel: Inv → every assembly WS → QI  (independent stations)
    # linear:   Inv → WS_1 → WS_2 → … → WS_n → QI  (single chain)
    lay      = cfg["layout"]
    topology = Symbol(get(lay, "topology", "parallel"))
    cap_r    = lay["flow_capacity"]
    cost_r   = lay["transport_cost"]
    @assert topology in (:parallel, :linear) "layout.topology must be 'parallel' or 'linear'"

    layout_edges = Vector{NamedTuple{(:origin,:destination,:capacity,:cost),
                                     Tuple{Symbol,Symbol,Float64,Float64}}}()

    edge!(o, d) = push!(layout_edges, (origin=o, destination=d,
        capacity=Float64(rand(cap_r[1]:cap_r[2])), cost=usample(cost_r)))

    if topology == :parallel
        for ws in assembly_ws
            edge!(:Inv, ws)
            edge!(ws, :QI)
        end
    else  # :linear
        edge!(:Inv, assembly_ws[1])
        for i in 1:(length(assembly_ws) - 1)
            edge!(assembly_ws[i], assembly_ws[i+1])
        end
        edge!(assembly_ws[end], :QI)
    end

    # --- Self-validate -----------------------------------------------------
    # Every producible component must appear as the `component` of ≥1 config.
    produced = Set(c.component for c in configurations)
    for comp in producible
        @assert comp in produced "Producible component $comp has no configuration"
    end

    # --- Export CSVs -------------------------------------------------------
    # Output path: absolute → used as-is; relative → resolved next to this
    # script. So the script + config can be dropped into any folder and the
    # output appears right beside them.
    out_dir = nothing
    if export_csv
        rel = cfg["output"]["directory"]
        out_dir = isabspath(rel) ? rel : normpath(joinpath(@__DIR__, rel))
        mkpath(out_dir)
        CSV.write(joinpath(out_dir, "components.csv"), DataFrame(
            ID        = String.(getfield.(components, :id)),
            Name      =          getfield.(components, :name),
            Level     =          getfield.(components, :level),
            IsProduct =          getfield.(components, :is_product)))
        CSV.write(joinpath(out_dir, "bom.csv"), DataFrame(
            Input    = String.(getfield.(bom_edges, :input)),
            Output   = String.(getfield.(bom_edges, :output)),
            Quantity =          getfield.(bom_edges, :quantity)))
        CSV.write(joinpath(out_dir, "workstations.csv"), DataFrame(
            ID   = String.(getfield.(workstations, :id)),
            Name =          getfield.(workstations, :name),
            Type = String.(getfield.(workstations, :type))))
        CSV.write(joinpath(out_dir, "configurations.csv"), DataFrame(
            ID             = String.(getfield.(configurations, :id)),
            Workstation    = String.(getfield.(configurations, :workstation)),
            Component      = String.(getfield.(configurations, :component)),
            ProcessingTime =          getfield.(configurations, :processing_time),
            SetupTime      =          getfield.(configurations, :setup_time),
            SetupCost      =          getfield.(configurations, :setup_cost),
            OperatingCost  =          getfield.(configurations, :operating_cost)))
        CSV.write(joinpath(out_dir, "layout.csv"), DataFrame(
            Origin      = String.(getfield.(layout_edges, :origin)),
            Destination = String.(getfield.(layout_edges, :destination)),
            Capacity    =          getfield.(layout_edges, :capacity),
            Cost        =          getfield.(layout_edges, :cost)))
    end

    return (components=components, bom_edges=bom_edges,
            workstations=workstations, configurations=configurations,
            layout_edges=layout_edges, producible=producible,
            out_dir=out_dir)
end

# Script entry point.
# `PROGRAM_FILE == @__FILE__` is the canonical check, but on Windows the two
# paths can differ in case and slash direction (`\` vs `/`). Normalize before
# comparing so the entry point fires whether launched from WSL or Windows.
function main_script()
    isempty(PROGRAM_FILE) && return false
    norm(p) = lowercase(normpath(abspath(p)))
    norm(PROGRAM_FILE) == norm(@__FILE__)
    result = generate_simple_assembly(joinpath(@__DIR__, "config.yaml"))
    println("Components:    ", length(result.components))
    println("BOM edges:     ", length(result.bom_edges))
    println("Workstations:  ", length(result.workstations))
    println("Configurations:", length(result.configurations))
    println("Layout edges:  ", length(result.layout_edges))
    println("Exported →     ", result.out_dir)
end

main_script()
    

