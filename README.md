# Synthetic Factory Data Generator

## Foundation

This project builds on the work of 
[Lopes et al. (2024)](https://doi.org/10.1080/0951192X.2024.2322981), 
who proposed a two-component framework for synthetic manufacturing 
data generation:

- **MN-RM** (Manufacturing Network Random Model): a random graph 
generation algorithm that represents production lines as networks 
of machines and production steps.
- **CLEMATIS** (Complex Manufacturing Throughput Simulation): a 
simulation strategy that generates machine state data and event 
logs from those networks.

The original implementation can be found 
[here](https://github.com/Victorf-lopes/clematis/blob/main/src/clematis/model_generator_ns.py#L25).

## This Project

This project extends the CLEMATIS framework in two key ways. First, 
it moves from a topology-driven to a **product-driven** approach, 
where the factory layout and machine configurations are derived from 
the requirements of a defined product or product family. Second, it 
introduces **heterogeneous machine parameters** drawn from realistic 
probability distributions, replacing the assumption that all machines 
in the network are identical.

The goal is to produce synthetic factory data that is more 
representative of the diversity of real manufacturing systems, 
and more useful for researchers benchmarking optimization and 
simulation models.


## Development

### Possible additions to the model
Generation
- Add intermediate topology (in between parallel and series)
- Add a 'broken machine' function / failure rate / downtime
- Add the fact that new machines are more efficient
- Buffer capacity
- Failure rates

Simulation
- How the 