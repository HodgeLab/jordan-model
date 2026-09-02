# An Open Synthetic Test System for the Jordanian Transmission Grid

Repository for the paper *"An Open Synthetic Test System for the
Jordanian Transmission Grid"* (submitted, IEEE Transactions on Power Systems).
Calibration year **2018**. Every number in the paper regenerates from the
public inputs and scripts here.

## Preliminaries

A synthetic, validated transmission test system for the Jordanian national
grid — 81 solved nodes (68 substations, 13 split 400/132 kV), a plant-level
2018 thermal and renewable fleet with per-site hourly profiles, calibrated
hourly load, and a full validation suite. The topology is reconstructed from
a published PMU-placement diagram and restored to its 2018-energized state
using dated NEPCO records. This is a synthetic test case, **not** the
operational NEPCO model; see the paper's scope statement before use.

## Layout

```
data/      inputs (hand-built / extracted): topology edges, RE fleet,
           bus-substation identity key, coordinates, named line lengths
src/       the pipeline, in run order: profiles, bias derivation, load,
           annual PCM, network build + N-1, structural metrics, losses,
           ex-post congestion check, cross-solver, scenario, figures
outputs/   released artifacts: jordan_net.json, jordan_net_greencorridor.json,
           case_jordan.mat (corrected MATPOWER export), generated hourly
           series (shipped so no API keys are needed), dispatch and
           energy-mix tables, named N-1 contingency list
archive/   Development versions - kept for history, do NOT
           reproduce the paper
```

## Reproduction

```bash
bash run_pipeline.sh                       # profiles -> load -> PCM -> network -> N-1 -> metrics
python src/loss_decomposition.py outputs/jordan_net.json outputs/load_2018_hourly.csv outputs/annual_dispatch.csv
python src/cross_solve.py export           # + MATLAB step (see docstring), then: compare
python src/check_congestion.py             # ex-post hourly network feasibility
python src/scenario_green_corridor.py
```


Regenerating the weather-driven profiles from scratch is optional (the
generated CSVs are in the repo) and requires an NSRDB API key and a
Renewables.ninja token in `src/re_profiles_2018.py`.

## Validation protocol

Parameters are set from cited sources or labeled assumptions **before** any
comparison with the 2018 record. Algorithm-correctness fixes are permitted
with a single rerun and then frozen. No parameter is ever adjusted against
the validation year. Two disclosed calibrations exist (the Risha
fuel-deliverability cap and the load temperature coefficient), both to
calibration anchors, never to validation targets.

## Requirements

Python 3.9+, `pandapower`, `pandas`, `numpy`, `networkx`, `matplotlib`,
`pvlib`, `scipy`. The cross-solver step additionally needs MATLAB or Octave
with MATPOWER.

## License and citation

Code is released under the MIT License; the data files under CC BY 4.0.
If you use this test system, please cite the paper (citation to be updated
on publication).
