#!/usr/bin/env python3
"""
check_congestion.py — ex-post hourly DC power flow over the frozen full-year PCM
dispatch. Verifies whether the energy-balance (copper-plate) assumption is
self-consistent at 2018 loading: if no hour produces a branch overload, network
constraints would never have bound and the unconstrained PCM dispatch is exact.

Run in jordan-model after the freeze pass (~1-3 min, 8,760 DC solves):
    python check_congestion.py
"""
import numpy as np, pandas as pd, pandapower as pp

net = pp.from_json("jordan_net.json")
load  = pd.read_csv("load_2018_hourly.csv",  index_col=0).iloc[:, 0].values[:8760]
disp  = pd.read_csv("annual_dispatch.csv").iloc[:8760]
w     = pd.read_csv("wind_2018_hourly_bybus.csv",  index_col=0).iloc[:8760]
s     = pd.read_csv("solar_2018_hourly_bybus.csv", index_col=0).iloc[:8760]

named = net.gen.name.notna().all() and (net.gen.name != "").all()
assert named, "run on the v3 net (named generators)"
base = float(net.load.p_mw.sum())

def sgen_series(sg_name, frames):
    """hourly MW for a named sgen: match its host bus column in the by-bus frames"""
    bus = float(net.sgen.loc[net.sgen.name == sg_name, "bus"].iloc[0])
    # by-bus columns are the PMU host labels used in re_fleet; map bus->pmu = idx+1
    col = str(bus + 1) if str(bus + 1) in frames.columns else f"{bus+1:.1f}"
    return frames[col].values if col in frames.columns else None

# pre-map sgens: distribute the by-bus profile columns onto the sgens at those buses
sgen_prof = {}
for si, sg in net.sgen.iterrows():
    nm = (sg["name"] or "")
    frames = s if nm.startswith("solar") else (w if nm.startswith("wind") else None)
    if frames is None:
        sgen_prof[si] = np.zeros(8760)   # Egypt
        continue
    col = f"{int(sg.bus)+1}.0"
    col = col if col in frames.columns else str(int(sg.bus)+1)
    if col in frames.columns:
        # share the bus profile among sgens at the same bus by nameplate
        peers = net.sgen[(net.sgen.bus == sg.bus) &
                         (net.sgen.name.fillna("").str.startswith(nm.split()[0]))]
        share = sg.max_p_mw / peers.max_p_mw.sum()
        sgen_prof[si] = frames[col].values * share
    else:
        sgen_prof[si] = np.zeros(8760)

mx = np.zeros(8760); overload_hours = []
for h in range(8760):
    net.load["scaling"] = load[h] / base
    for gi, g in net.gen.iterrows():
        net.gen.at[gi, "p_mw"] = float(disp.at[h, g["name"]]) if g["name"] in disp.columns else 0.0
    for si in net.sgen.index:
        net.sgen.at[si, "p_mw"] = float(sgen_prof[si][h])
    pp.rundcpp(net)
    m = max(net.res_line.loading_percent.abs().max(),
            net.res_trafo.loading_percent.abs().max() if len(net.res_trafo) else 0.0)
    mx[h] = m
    if m > 100.0:
        overload_hours.append((h, round(m, 1)))
    if h % 1000 == 0:
        print(f"  h={h}  running max loading {mx[:h+1].max():.0f}%")

print(f"\nhours solved: 8760 | max loading over the year: {mx.max():.1f}% "
      f"(hour {int(mx.argmax())})")
print(f"hours with any branch > 100%: {len(overload_hours)}")
if overload_hours:
    print("first offenders:", overload_hours[:10])
    print("-> network constraints WOULD bind; the copper-plate statement must be qualified.")
else:
    print("-> ZERO overload hours: the unconstrained PCM dispatch is network-feasible for")
    print("   every hour of 2018. Quote this in Sec. IV-F.")