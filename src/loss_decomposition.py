#!/usr/bin/env python3
"""
loss_decomposition.py — energy-weighted annual transmission losses for the model,
compared apples-to-apples against NEPCO's 1.97% (purchases 18,912.7 - sales 18,539.2
= 373.5 GWh, Table 11/14 of the 2018 annual report).

Scope of the benchmark (per NEPCO metering, corroborated by the JICA loss study):
everything between generation meters and offtake meters on the HV network -
series I2R losses, transformer losses (incl. no-load core losses, and the 132/33 kV
transformers at the disco intake), and station consumption.

Method:
  1. Bin the 8,760-h load duration curve into N load levels with duration weights.
  2. Run AC power flow at each level (uniform load scaling, slack balancing) and
     record series losses. Energy-weight -> modeled annual series-loss %.
  3. Add estimated components the model zeroes or omits, each parameterized and
     cited in the printed attribution table.

Usage: python loss_decomposition.py jordan_net.json load_2018_hourly.csv [annual_dispatch.csv]
If annual_dispatch.csv is given, each load bin uses the PCM's average per-plant dispatch
(dispatch-consistent mode - the headline number). Otherwise loads and generation are
scaled uniformly. Solar/wind CSVs are read from the working directory in dispatch mode.
"""
import sys
import numpy as np, pandas as pd
import pandapower as pp

N_LEVELS   = 20
BENCH_GWH  = 373.5
BENCH_PCT  = 1.97
E_ANNUAL   = 18913.0     # GWh, NEPCO purchases

# --- parameterized estimates for components absent from the model (EDIT + SOURCE) ---
# 400/132 no-load core loss per transformer unit, kW (typical 0.02-0.05% of rating;
# model has 26 x 400 MVA units with pfe zeroed):
PFE_400_132_KW = 160.0
# 132/33 kV transformation layer (loads sit at 132 kV in the model, but the NEPCO
# benchmark meters at the 33 kV disco intake): copper+core, % of energy throughput.
# TODO: source from the JICA loss study breakdown; 0.25-0.45% is the plausible band.
PCT_132_33 = (0.25, 0.45)
# station/auxiliary consumption metered inside the boundary, % (TODO: source)
PCT_STATION = (0.05, 0.15)

CAPMAP = {1150.0:'Samra (SEPGCO)',380.0:'Amman East (IPP1)',373.0:'Qatrana (IPP2)',
          485.0:'Zarqa (ACWA)',573.0:'IPP3 (Amman Asia)',250.0:'IPP4 (Levant)',
          400.0:'Aqaba steam',200.0:'Rehab',297.0:'Rehab',150.0:'Risha',80.0:'Risha'}

def main(net_path, load_path, disp_path=None):
    net  = pp.from_json(net_path)
    load = pd.read_csv(load_path, index_col=0, parse_dates=True).iloc[:, 0]
    base = float(net.load.p_mw.sum())
    print(f"net base load {base:.0f} MW | LDC: min {load.min():.0f}, mean {load.mean():.0f}, "
          f"peak {load.max():.0f} MW")

    # duration-weighted load levels
    q = np.linspace(0, 1, N_LEVELS + 1)
    edges = np.quantile(load, q)
    levels, weights = [], []
    for i in range(N_LEVELS):
        sel = (load >= edges[i]) & (load <= edges[i + 1] if i == N_LEVELS - 1 else load < edges[i + 1])
        if sel.sum() == 0:
            continue
        levels.append(load[sel].mean())
        weights.append(sel.sum())
    weights = np.array(weights, float)

    disp = solar = wind = None
    if disp_path:
        # v2 nets carry plant names on gens; fall back to capacity mapping for v1
        named = net.gen.name.notna().all() and (net.gen.name != "").all()
        net.gen['plant'] = net.gen.name if named else net.gen.max_p_mw.map(CAPMAP)
        if net.gen['plant'].isna().any():
            raise SystemExit("unmapped generator(s): " + str(net.gen[net.gen['plant'].isna()][['bus','max_p_mw']]))
        disp  = pd.read_csv(disp_path)
        solar = pd.read_csv("solar_2018_hourly.csv", index_col=0).iloc[:, 0].values
        wind  = pd.read_csv("wind_2018_hourly.csv",  index_col=0).iloc[:, 0].values
    gen_p0, sgen_p0 = net.gen.p_mw.copy(), net.sgen.p_mw.copy()
    lv_edges = edges
    rows = []
    for i, (lv, w) in enumerate(zip(levels, weights)):
        net.load["scaling"] = lv / base
        if disp is not None:
            sel = (load.values >= lv_edges[i]) & ((load.values < lv_edges[i+1]) if i < N_LEVELS-1 else (load.values <= lv_edges[i+1]))
            for gi, g in net.gen.iterrows():
                net.gen.at[gi, 'p_mw'] = float(disp.loc[sel, g['plant']].mean())
            # distribute fleet RE across sgens by nameplate share (names start 'solar'/'wind';
            # v1 two-bus layout: treat the two unnamed non-Egypt sgens as solar, wind by bus order)
            names = net.sgen.name.fillna("")
            sol = names.str.startswith("solar"); wnd = names.str.startswith("wind")
            if not sol.any():   # v1 fallback
                non_egypt = net.sgen.index[names != "Egypt"]
                sol = net.sgen.index.isin(non_egypt[:1]); wnd = net.sgen.index.isin(non_egypt[1:2])
            for mask, series in ((sol, solar), (wnd, wind)):
                cap = net.sgen.loc[mask, 'max_p_mw'].sum()
                if cap > 0:
                    net.sgen.loc[mask, 'p_mw'] = float(series[sel].mean()) * net.sgen.loc[mask, 'max_p_mw'] / cap
        else:
            net.gen["p_mw"]  = gen_p0  * lv / base
            net.sgen["p_mw"] = sgen_p0 * lv / base
        try:
            pp.runpp(net, init="flat", numba=False)
        except Exception:
            pp.runpp(net, init="auto", numba=False)
        p_loss = float(net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum())
        rows.append((lv, w, p_loss, 100 * p_loss / lv))
    df = pd.DataFrame(rows, columns=["load_MW", "hours", "loss_MW", "loss_pct"])
    print(df.round(2).to_string(index=False))

    e_load = (df.load_MW * df.hours).sum() / 1000            # GWh served
    e_loss = (df.loss_MW * df.hours).sum() / 1000            # GWh series losses
    pct_series = 100 * e_loss / (e_load + e_loss)
    print(f"\n[1] energy-weighted SERIES losses: {e_loss:.1f} GWh = {pct_series:.2f}%")

    n_tr = len(net.trafo)
    e_pfe = n_tr * PFE_400_132_KW * 8760 / 1e6               # GWh
    pct_pfe = 100 * e_pfe / E_ANNUAL
    print(f"[2] 400/132 no-load (est., {n_tr} units x {PFE_400_132_KW:.0f} kW): "
          f"{e_pfe:.1f} GWh = {pct_pfe:.2f}%")

    lo = pct_series + pct_pfe + PCT_132_33[0] + PCT_STATION[0]
    hi = pct_series + pct_pfe + PCT_132_33[1] + PCT_STATION[1]
    print(f"[3] 132/33 kV layer (est. band): {PCT_132_33[0]:.2f}-{PCT_132_33[1]:.2f}%")
    print(f"[4] station consumption (est. band): {PCT_STATION[0]:.2f}-{PCT_STATION[1]:.2f}%")
    print(f"\nTOTAL comparable losses: {lo:.2f}-{hi:.2f}%  vs NEPCO benchmark {BENCH_PCT}% "
          f"({BENCH_GWH} GWh)")
    print(f"residual vs band midpoint: {BENCH_PCT - (lo+hi)/2:+.2f} pp "
          f"(candidates: line-length underestimate, conductor R assumptions, reactive flows)")
    print("\nManuscript framing: report [1] as the model result, [2]-[4] as the scope"
          " reconciliation to NEPCO's purchases-minus-sales metering boundary; do NOT"
          " claim agreement of the raw snapshot number with 1.97%.")

if __name__ == "__main__":
    a = sys.argv[1:] or ["jordan_net.json", "load_2018_hourly.csv"]
    main(*a[:3])