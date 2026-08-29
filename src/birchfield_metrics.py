#!/usr/bin/env python3
"""
birchfield_metrics.py — structural validation table for the Jordan synthetic grid,
following Birchfield et al., "Grid Structural Characteristics as Validation Criteria
for Synthetic Networks" (IEEE TPWRS, 2017) [ref 6 of the manuscript].

Run on your machine against the SOLVED pandapower network (81-node, incl. the 13
dual-voltage substation splits and transformer branches):

    python birchfield_metrics.py jordan_net.json

Produces birchfield_table.csv (metric | model value | reference range | source | pass)
and prints the summary. Reference ranges marked TODO must be filled with the exact
numbers from Birchfield Table/Figs — do not cite ranges we haven't verified.

Circuit-km anchors (EDIT if your sourced figures differ):
    400 kV published circuit-km : 1164
    132 kV published circuit-km : 3600
"""
import sys, math, json
import numpy as np, pandas as pd
import pandapower as pp
import networkx as nx

# NEPCO 2018 annual report: 400 kV = 1164 km-circuit (incl. ~130 strung for the 2019
# Green-Corridor energization -> 2018-energized model targets ~1034), 132 kV = 3636 km.
KM_ANCHORS = {400.0: 1164.0, 132.0: 3636.0}

def load_net(path):
    return pp.from_json(path)

def topology_metrics(net):
    # Topology statistics are per CORRIDOR: parallel circuits between the same
    # bus pair collapse to one edge (Birchfield convention). Circuit counts and
    # circuit-km elsewhere still use the full line table.
    G = nx.Graph()
    for _, ln in net.line.iterrows():
        G.add_edge(int(ln.from_bus), int(ln.to_bus), kind="line")
    for _, tr in net.trafo.iterrows():
        G.add_edge(int(tr.hv_bus), int(tr.lv_bus), kind="trafo")
    Gs = G
    N, E = G.number_of_nodes(), G.number_of_edges()
    deg = pd.Series(dict(G.degree()))
    giant = Gs.subgraph(max(nx.connected_components(Gs), key=len))
    n_tr = len(net.trafo.groupby(["hv_bus","lv_bus"]))  # transformer corridors
    rows = [
        ("buses (solved nodes)", N, "—", "model", ""),
        ("branches (lines+trafos)", E, "—", "model", ""),
        ("avg node degree", round(2*E/N, 2), "2.2–3.0 (TODO exact)", "Birchfield 2017", ""),
        ("max node degree", int(deg.max()), "single-digit typical", "Birchfield 2017", ""),
        ("degree-1 bus share %", round(100*(deg == 1).mean(), 1), "TODO", "Birchfield 2017", ""),
        ("transformer branch share %", round(100*n_tr/E, 1), "TODO", "Birchfield 2017", ""),
        ("connected components", nx.number_connected_components(Gs), "1", "requirement", ""),
        ("graph diameter", nx.diameter(giant), f"~sqrt(N)={math.sqrt(N):.1f} scale", "Birchfield 2017", ""),
        ("avg shortest path", round(nx.average_shortest_path_length(giant), 2), "TODO", "Birchfield 2017", ""),
        ("avg clustering coeff", round(nx.average_clustering(Gs), 3), "~0.05–0.15 (TODO exact)", "Birchfield 2017", ""),
    ]
    return rows, deg

def electrical_metrics(net):
    rows = []
    ln = net.line.copy()
    ln["vn"] = net.bus.loc[ln.from_bus, "vn_kv"].values
    for vn, grp in ln.groupby("vn"):
        zb = vn**2 / net.sn_mva if hasattr(net, "sn_mva") else vn**2 / 100.0
        x_pu = grp.x_ohm_per_km * grp.length_km / zb
        xr = (grp.x_ohm_per_km / grp.r_ohm_per_km).replace([np.inf], np.nan)
        rows += [
            (f"{vn:.0f} kV lines: count", len(grp), "—", "model", ""),
            (f"{vn:.0f} kV X per line (pu, min–max)",
             f"{x_pu.min():.4f}–{x_pu.max():.4f}", "TODO per class", "Birchfield 2017", ""),
            (f"{vn:.0f} kV X/R (min–max)",
             f"{xr.min():.1f}–{xr.max():.1f}",
             "≈2–5 (132 kV), ≈8–15 (400 kV) TODO exact", "Birchfield 2017", ""),
        ]
        # circuit-km reconciliation: length x parallel circuits
        ckm = float((grp.length_km * grp.parallel).sum()) if "parallel" in grp else float(grp.length_km.sum())
        anchor = KM_ANCHORS.get(float(vn))
        if anchor:
            rows.append((f"{vn:.0f} kV circuit-km (model vs published)",
                         f"{ckm:.0f} vs {anchor:.0f} ({100*(ckm-anchor)/anchor:+.0f}%)",
                         "within ±20% credible", "NEPCO/JICA figures", ""))
    # generation & load per bus
    gbus = set(net.gen.bus) | set(net.sgen.bus) if len(net.sgen) else set(net.gen.bus)
    rows.append(("share of buses with generation %", round(100*len(gbus)/len(net.bus), 1),
                 "TODO", "Birchfield 2017", ""))
    ld = net.load.groupby("bus").p_mw.sum()
    rows += [
        ("load buses / total buses %", round(100*len(ld)/len(net.bus), 1), "TODO", "Birchfield 2017", ""),
        ("max single-bus load share %", round(100*ld.max()/ld.sum(), 1), "TODO", "Birchfield 2017", ""),
        ("median bus load (MW)", round(ld.median(), 1), "—", "model", ""),
    ]
    tr = net.trafo
    if len(tr):
        rows.append(("trafo vk% range", f"{tr.vk_percent.min():.1f}–{tr.vk_percent.max():.1f}",
                     "10–15% typical 400/132", "engineering practice", ""))
    return rows

def main(path):
    net = load_net(path)
    rows, deg = topology_metrics(net)
    rows += electrical_metrics(net)
    df = pd.DataFrame(rows, columns=["metric", "model", "reference_range", "source", "pass"])
    df.to_csv("birchfield_table.csv", index=False)
    print(df.to_string(index=False))
    print("\ndegree histogram:", dict(deg.value_counts().sort_index()))
    print("\nwrote birchfield_table.csv — fill TODO ranges from Birchfield (2017) before"
          " inserting in the manuscript; mark pass/fail per row.")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "jordan_net.json")