# jordan-model — An Open Synthetic Test System for the Jordanian Transmission Grid

Repository for the paper *"An Open Synthetic Test System for the
Jordanian Transmission Grid"* (submitted, IEEE Transactions on Power Systems).
Calibration year: **2018**. Every number in the paper regenerates from the
public inputs and scripts in this repository.

## What this is

A synthetic, validated transmission test system for the Jordanian national
grid: 81 solved nodes (68 substations, 13 of them split 400/132 kV), a
plant-level 2018 generation and renewable fleet with per-site hourly
profiles, calibrated hourly load, and a full validation suite. The topology
is reconstructed from a published PMU-placement diagram and restored to its
2018-energized state using dated NEPCO records. This is a synthetic test
case, **not** the operational NEPCO model; see the paper's scope statement
before use.

## Released artifacts

| File | Content |
|---|---|
| `jordan_net.json` | The 2018 base case (pandapower) |
| `jordan_net_greencorridor.json` | Post-2019 Green-Corridor scenario variant (unvalidated by design) |
| `case_jordan.mat` | MATPOWER export, cross-verified to machine precision (converter corrections applied) |
| `jordan_number_name_key_pass3.csv` | Bus–substation identity key with per-bus evidence and confidence tiers |
| `jordan_bus_coordinates_draft.csv` | Draft substation coordinates (verification in progress) |
| `re_fleet_2018.csv` | Plant-level renewable fleet: capacities, CODs, host buses, correction factors |
| `jordan_pmu_edges_reconstructed.csv` | Topology edge list reconstructed from the source diagram |
| `*_2018_hourly*.csv` | Generated load / solar / wind series (shipped so no API keys are needed) |

## Reproduction

```bash
bash run_pipeline.sh          # full chain: profiles -> load -> PCM -> network -> N-1 -> metrics
python loss_decomposition.py jordan_net.json load_2018_hourly.csv annual_dispatch.csv
python cross_solve.py export  # + MATLAB step in the docstring, then: python cross_solve.py compare
python check_congestion.py    # ex-post hourly network feasibility of the PCM dispatch
python scenario_green_corridor.py
```

Fingerprint gates (printed by the pipeline; if any fails, something upstream
changed): solar **819 GWh** / wind **560 GWh**; PCM total **18,923 GWh** with
Risha **307**; N−1 **94 %** secure; 400 kV **1,114 km-circuit**; annual series
losses **0.70 %**; scenario **38.62 MW** peak losses.

Profile regeneration from scratch (optional; shipped CSVs make this
unnecessary) requires an NSRDB API key and Renewables.ninja token in
`re_profiles_2018.py`.

## Validation protocol

Parameters are set from cited sources or labeled assumptions **before**
comparison with the 2018 record; algorithm-correctness fixes are permitted
with a single rerun and then frozen; no parameter is ever adjusted against
the validation year. Two disclosed calibrations exist (the Risha
fuel-deliverability cap; the load temperature coefficient), both to
calibration anchors, never to validation targets.

## Requirements

Python 3.9+, `pandapower`, `pandas`, `numpy`, `networkx`, `matplotlib`,
`pvlib`, `scipy`. The cross-solver step additionally needs MATLAB or Octave
with MATPOWER.

## License

Code: MIT. Data files: CC-BY-4.0. If you use this test system, please cite
the paper (citation to be updated on publication).

## Archive

`archive/` contains development versions (v1 network build, early
PCM). They do not reproduce the paper and are kept for history only.