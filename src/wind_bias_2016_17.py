#!/usr/bin/env python3
"""
wind_bias_2016_17.py — derive per-site reanalysis bias-correction factors for the wind
fleet by solving against NEPCO's 2016 and 2017 observed purchases, leaving 2018 BLIND.

Method: Renewables.ninja (MERRA-2) underestimates escarpment sites like Tafila.
In 2016-2017 the fleet was only Tafila (117 MW, full years) + Ma'an (80 MW, from
~Mar 2016) + Hofa (1.4 MW, negligible). NEPCO Table 11:
    2016 wind purchases = 390.7 GWh
    2017 wind purchases = 447.5 GWh
Two equations, two unknowns (f_Tafila, f_Maan):
    f_T * E_T(yr) + f_M * E_M(yr) = observed(yr) - hofa_est      for yr in {2016, 2017}
where E_site(yr) is the UNCORRECTED RN energy for that site-year.

The factors are then written for use in re_fleet_2018.csv (bias_factor column).
Rajef gets f_Tafila (nearest analogous escarpment site) - a disclosed limitation.
2018 is never touched here, so the 2018 energy-mix validation remains blind.

RATE LIMIT: 4 RN calls (2 sites x 2 years). Free tier ~6/hour - run this in a
fresh hour if you fetched wind recently.

Env var: RN_TOKEN
"""
import io, os, sys, time
import numpy as np, pandas as pd, requests

RN_TOKEN = os.environ.get("RN_TOKEN") or sys.exit("set RN_TOKEN")
RN_EP    = "https://www.renewables.ninja/api/data/wind"
TURBINE, HUB_M = "Vestas V112 3000", 84

SITES = {"Tafila": (30.83, 35.60, 117.0),
         "Maan":   (30.17, 35.78,  80.0)}
MAAN_START = {"2016": "2016-03-01"}          # Ma'an partial in 2016
OBSERVED   = {"2016": 390.7, "2017": 447.5}  # NEPCO Table 11, GWh
HOFA_GWH   = {"2016": 2.3, "2017": 2.3}      # small, from 1.4 MW at ~19% CF

def fetch(lat, lon, year):
    args = dict(lat=lat, lon=lon, date_from=f"{year}-01-01", date_to=f"{year}-12-31",
                capacity=1.0, height=HUB_M, turbine=TURBINE, format="csv",
                local_time="false", raw="false")
    r = requests.get(RN_EP, params=args, timeout=180,
                     headers={"Authorization": "Token " + RN_TOKEN})
    if r.status_code == 429:
        sys.exit("HTTP 429 rate-limited: wait an hour and re-run.")
    r.raise_for_status()
    pos = r.text.find("time,")
    cf = pd.read_csv(io.StringIO(r.text[pos:]), index_col=0, parse_dates=True)["electricity"]
    return cf.astype(float)

E = {}   # E[(site, year)] = uncorrected GWh
for site, (lat, lon, cap) in SITES.items():
    for year in ("2016", "2017"):
        cf = fetch(lat, lon, year)
        if site == "Maan" and year in MAAN_START:
            cf = cf[cf.index >= MAAN_START[year]]
        gwh = float(cf.sum() * cap / 1000.0)
        E[(site, year)] = gwh
        print(f"{site} {year}: uncorrected RN energy {gwh:.1f} GWh (CF {100*cf.mean():.1f}%)")
        time.sleep(12)

# solve the 2x2 system
A = np.array([[E[("Tafila", "2016")], E[("Maan", "2016")]],
              [E[("Tafila", "2017")], E[("Maan", "2017")]]])
b = np.array([OBSERVED["2016"] - HOFA_GWH["2016"],
              OBSERVED["2017"] - HOFA_GWH["2017"]])
fT, fM = np.linalg.solve(A, b)
print(f"\nbias factors:  Tafila {fT:.3f}   Maan {fM:.3f}")
resid = A @ np.array([fT, fM]) - b
print(f"residuals (should be ~0 by construction): {resid.round(2)}")

if not (0.7 <= fT <= 3.0 and 0.7 <= fM <= 3.0):
    print("WARNING: factor outside plausible range - inspect before using.")

print("\nPaste into re_fleet_2018.csv bias_factor column:")
print(f"  Tafila Wind Farm : {fT:.3f}")
print(f"  Maan Wind Farm   : {fM:.3f}")
print(f"  Al Rajef Wind    : {fT:.3f}   (Tafila's factor - nearest escarpment analogue, DISCLOSE)")
print(f"  Hofa Pilot       : 1.0")
print("\nSanity: exact 2-eq/2-unknown solve reproduces 2016-17 by construction;")
print("the REAL test is whether 2018 then lands near 705.4 GWh blind.")