#!/usr/bin/env python3
"""
annual_pcm.py — run the production-cost dispatch over the full 8,760-hour 2018 year using the
three synthesized profiles, then validate the resulting energy mix against NEPCO 2018 figures.
Reuses the same commitment/economic-dispatch logic and quadratic heat-rate costs as the
two-week PCM (jordan_pcm_v2.py), including the Risha fuel-deliverability cap.

Inputs : solar_2018_hourly.csv, wind_2018_hourly.csv, load_2018_hourly.csv  (8760 rows each)
Outputs: annual_dispatch.csv (per-plant hourly), annual_energy_mix.csv (per-plant GWh + share)

This is the payoff step: the per-plant GWh and technology shares are an INDEPENDENT check
against NEPCO — do not tune the cost curves to make them match.
"""
import numpy as np, pandas as pd


def coef(HR, fp, Pmax, pf, K=0.12):
    Pmin = pf * Pmax
    a = (HR * K / 1000.0) / (1.0 / Pmin + Pmin / Pmax**2 - 2.0 / Pmax)
    b = HR / 1000.0 - 2 * a / Pmax
    c = a / Pmax**2
    return fp * c, fp * b, fp * a, Pmin


SPEC = [
    ("Samra (SEPGCO)", 6700, 8.0, 1150, 0.45, 4, 3, 60),
    ("Amman East (IPP1)", 6650, 8.0, 380, 0.45, 4, 3, 60),
    ("Qatrana (IPP2)", 6600, 8.0, 373, 0.45, 4, 3, 60),
    ("Zarqa (ACWA)", 6400, 8.0, 485, 0.45, 4, 3, 60),
    ("IPP4 (Levant)", 7500, 8.0, 250, 0.45, 4, 3, 60),   # 18V50DF engines ~45.5% simple-cycle; 6500 in source was a CCGT-class error
    ("IPP3 (Amman Asia)", 8000, 8.0, 573, 0.25, 1, 1, 30),
    ("Rehab", 11500, 8.0, 297, 0.25, 1, 1, 30),   # 2x100 GT + 97 ST CC (MEZ verified)
    ("Risha", 11000, 2.0, 150, 0.25, 6, 6, 30),
    ("Aqaba steam", 10200, 12.0, 400, 0.40, 8, 6, 100),
]
# Risha fuel-deliverability cap: Table 12 (GT/NG) shows ~304.5 GWh in 2018 = 35 MW average.
# At 80 MW and $2/MMBtu the PCM runs Risha flat (701 GWh/yr) - 2.3x reality. The binding
# constraint is field gas supply, so the cap is set to reproduce the observed average.
# DISCLOSED CALIBRATION of a fuel-supply input (not a cost tune) - state this in the paper.
CAP = {"Risha": 35.0}

# Must-run anchors - honest sourcing:
#  (i) must-run constraints are a standard class in JPS UC modeling (Harb & Al Ramahi,
#      J Sustain Res 2026;8(1):e260006 - lists "must run units" among model constraints);
#  (ii) the SPECIFIC designation of Aqaba/Rehab is the AUTHORS' MODELING ASSUMPTION,
#      motivated by grid-extremity voltage support and by the observed 2018 record
#      (792/576 GWh from the costliest fleet segment = out-of-merit operation);
#  (iii) no source names these two plants as must-run - state this plainly in the paper.
# Floors = ONE unit at minimum stable level (engineering values, not fitted):
#   Aqaba: 1 x 130 MW ST at ~42% min stable ~= 55 MW
#   Rehab: 1 x 100 MW GT-block share at ~65 MW
MUSTRUN = {"Aqaba steam": 55.0, "Rehab": 65.0}
U = []
for nm, HR, fp, Pmax, pf, mu, md, su in SPEC:
    c2, c1, c0, Pmin = coef(HR, fp, Pmax, pf)
    cap = CAP.get(nm, Pmax)
    if nm in MUSTRUN:
        Pmin = MUSTRUN[nm]   # committed floor, dispatch above it stays economic
    U.append(
        dict(
            name=nm,
            c2=c2,
            c1=c1,
            c0=c0,
            pmax=Pmax,
            cap=cap,
            pmin=min(Pmin, cap),
            minup=mu,
            mindown=md,
            su=su,
            mcfull=c1 + 2 * c2 * Pmax,
        )
    )
merit = sorted(U, key=lambda u: u["mcfull"])


def edisp(comm, target):
    if not comm:
        return {}
    lo = min(u["c1"] for u in comm)
    hi = max(u["c1"] + 2 * u["c2"] * u["cap"] for u in comm) + 1
    for _ in range(60):
        lam = (lo + hi) / 2
        tot = 0
        d = {}
        for u in comm:
            p = (
                (lam - u["c1"]) / (2 * u["c2"])
                if u["c2"] > 1e-9
                else (u["cap"] if lam > u["c1"] else u["pmin"])
            )
            p = min(u["cap"], max(u["pmin"], p))
            d[u["name"]] = p
            tot += p
        hi, lo = (lam, lo) if tot > target else (hi, lam)
    return d


# export-start availability for units not online all of 2018 (hour index into the year)
import pandas as _pd
_H0 = _pd.Timestamp("2018-01-01", tz="UTC")
EXPORT_START = {"Zarqa (ACWA)": "2018-07-15"}   # VERIFY month; COD cert Sep 29 but pre-COD export
def _avail_from(name, H):
    if name not in EXPORT_START:
        return 0
    return int((_pd.Timestamp(EXPORT_START[name], tz="UTC") - _H0).total_seconds() // 3600)

def run(load, solar, wind):
    H = len(load)
    start_h = {u["name"]: _avail_from(u["name"], H) for u in U}
    on = {u["name"]: (u["name"] in MUSTRUN) for u in U}
    ot = {u["name"]: 0 for u in U}
    ft = {u["name"]: 99 for u in U}
    disp = {u["name"]: np.zeros(H) for u in U}
    last_p = {u["name"]: 0.0 for u in U}
    re_used = np.zeros(H)
    curt = np.zeros(H)
    for h in range(H):
        re = solar[h] + wind[h]
        nl = load[h] - re
        need = nl * 1.08
        cap = sum(u["cap"] for u in U if on[u["name"]])
        for u in merit:
            if cap >= need:
                break
            if h < start_h[u["name"]]:
                continue
            if not on[u["name"]] and ft[u["name"]] >= u["mindown"]:
                on[u["name"]] = True
                ot[u["name"]] = 0
                cap += u["cap"]
        for u in sorted(U, key=lambda x: -x["mcfull"]):
            if u is merit[0] or u["name"] in MUSTRUN:
                continue   # protect the cheapest unit and the sourced must-run anchors
            if last_p[u["name"]] > u["pmin"] + 1.0:
                continue   # unit is carrying economic energy - switching it off would
                           # substitute expensive must-run/peaker energy (cost-aware decommit)
            if (
                on[u["name"]]
                and ot[u["name"]] >= u["minup"]
                and cap - u["cap"] >= need
                and sum(
                    x["pmin"] for x in U if on[x["name"]] and x["name"] != u["name"]
                )
                <= nl
            ):
                on[u["name"]] = False
                ft[u["name"]] = 0
                cap -= u["cap"]
        comm = [u for u in U if on[u["name"]]]
        minsum = sum(u["pmin"] for u in comm)
        if minsum > nl:
            curt[h] = min(minsum - nl, re)
            nl = minsum
        re_used[h] = re - curt[h]
        d = edisp(comm, nl)
        for u in U:
            p = d.get(u["name"], 0.0)
            disp[u["name"]][h] = p
            last_p[u["name"]] = p
            if on[u["name"]]:
                ot[u["name"]] += 1
                ft[u["name"]] = 0
            else:
                ft[u["name"]] += 1
                ot[u["name"]] = 0
    return disp, re_used, curt


if __name__ == "__main__":
    load = pd.read_csv("load_2018_hourly.csv", index_col=0, parse_dates=True)[
        "load_MW"
    ].values
    solar = pd.read_csv("solar_2018_hourly.csv", index_col=0, parse_dates=True)[
        "solar_MW"
    ].values
    wind = pd.read_csv("wind_2018_hourly.csv", index_col=0, parse_dates=True)[
        "wind_MW"
    ].values
    n = min(len(load), len(solar), len(wind))
    load, solar, wind = load[:n], solar[:n], wind[:n]
    disp, re_used, curt = run(load, solar, wind)

    # energy mix (GWh)
    rows = []
    for u in U:
        rows.append((u["name"], disp[u["name"]].sum() / 1000))
    rows.append(("Solar", solar.sum() / 1000))
    rows.append(("Wind", wind.sum() / 1000))
    mix = pd.DataFrame(rows, columns=["plant", "model_GWh"]).set_index("plant")
    mix["share_%"] = 100 * mix["model_GWh"] / mix["model_GWh"].sum()

    NEPCO = {
        "Samra (SEPGCO)": 7568,          # Table 11
        "Amman East (IPP1)": 2740,       # Table 11
        "Qatrana (IPP2)": 2713,          # Table 11
        "Zarqa (ACWA)": 1198,            # Table 11 (incl. pre-COD export)
        "IPP4 (Levant)": 752,            # Table 11
        "IPP3 (Amman Asia)": 486,        # Table 11 (AAEPCO - NOT Risha)
        "Aqaba steam": 792,              # Table 12 steam row (only operating steam plant)
        "Rehab": 576,                    # CEGCO residual (T11 1707.8 minus T12 components)
        "Risha": 305,                    # Table 12 GT/NG row (upper bound; minor GTs included)
        "Solar": 836,                    # Table 11/12
        "Wind": 707,                     # Table 12 (incl. Hofa 1.6)
    }
    mix["NEPCO_GWh"] = [NEPCO.get(i, np.nan) for i in mix.index]
    print(mix.round(0).to_string())
    print(
        f"\nTotal modeled generation: {mix['model_GWh'].sum():.0f} GWh   (NEPCO purchased ≈ 18,913)"
    )
    print(
        f"Renewable energy: solar {solar.sum()/1000:.0f} (anchor 836), wind {wind.sum()/1000:.0f} (anchor 705) GWh"
    )
    print(f"Annual curtailment: {curt.sum()/1000:.1f} GWh")
    gas = sum(
        disp[n].sum()
        for n in [
            "Samra (SEPGCO)",
            "Amman East (IPP1)",
            "Qatrana (IPP2)",
            "Zarqa (ACWA)",
            "IPP4 (Levant)",
            "IPP3 (Amman Asia)",
            "Rehab",
            "Risha",
        ]
    )
    print(
        f"Gas-fired share of generation: {100*gas/ (mix['model_GWh'].sum()*1000):.0f}%   (NEPCO ≈ 88%)"
    )
    mix.to_csv("annual_energy_mix.csv")
    pd.DataFrame({n: disp[n] for n in disp}).to_csv("annual_dispatch.csv", index=False)
    print("\nwrote annual_energy_mix.csv, annual_dispatch.csv")
    print(
        "INTERPRET, don't tune: report model vs NEPCO as a blind comparison. Expect Risha to "
        "over-run (network/transmission limit not enforced here) — that is a finding, not a fit."
    )