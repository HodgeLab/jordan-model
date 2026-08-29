#!/usr/bin/env python3
"""
re_profiles_2018.py — per-plant 2018 RE profiles from the fleet inventory, UNCALIBRATED.
Replaces solar_nsrdb.py + wind_profile.py. RUN ON YOUR MACHINE (needs both API keys).

Key changes vs the old scripts:
  1. Reads re_fleet_2018.csv (per-plant capacity, COD date, coordinates, host bus).
  2. COD-aware availability: each plant contributes 0 before its COD and ramps in from
     its COD date — this is the capacity-vintage fix. A plant commissioned 2018-04-26
     contributes nothing in Q1 and full capacity thereafter.
  3. NO anchor calibration. The old `total * (836/...)` and `total * (705/...)` lines are
     GONE. Totals are printed as a BLIND comparison against the NEPCO purchase anchors
     (solar 836.2 GWh, wind 705.4 GWh, Table 11). If they disagree, the inventory or the
     conversion is wrong — fix the input, never rescale the output.
  4. Rooftop/net-metering is intentionally ABSENT: Table 11 records NEPCO purchases,
     which net-metered rooftop never enters, and the load series is anchored to the same
     purchase totals, so rooftop is already netted out of demand. Utility-scale only here.
  5. Timestamp alignment: NSRDB MSG stamps on the half-hour; output is snapped to the
     top of the hour so solar/wind/load merge without a phantom 30-min lag.
  6. Output is per-host-bus (wide CSV) + a fleet total column, ready for the
     redistributed network model. Plants with blank host_bus go to column 'UNMAPPED'
     so nothing is silently dropped.

Env vars: NSRDB_API_KEY, NSRDB_EMAIL, RN_TOKEN   (do NOT hardcode keys — the old ones
were committed and must be regenerated before the repo goes public).

Outputs: solar_2018_hourly_bybus.csv, wind_2018_hourly_bybus.csv,
         solar_2018_hourly.csv / wind_2018_hourly.csv (fleet totals, drop-in for annual_pcm.py),
         temp_2018_hourly.csv, re_fleet_2018_report.txt
"""
import io, os, sys, time
import numpy as np, pandas as pd, requests, pvlib

YEAR      = 2018
FLEET_CSV = "re_fleet_2018.csv"
ANCHORS   = {"solar": 836.2, "wind": 705.4}   # NEPCO 2018 Table 11 purchases, GWh

NSRDB_KEY   = os.environ.get("NSRDB_API_KEY")  or sys.exit("set NSRDB_API_KEY")
NSRDB_EMAIL = os.environ.get("NSRDB_EMAIL")    or sys.exit("set NSRDB_EMAIL")
RN_TOKEN    = os.environ.get("RN_TOKEN")       or sys.exit("set RN_TOKEN")

NSRDB_EP = "https://developer.nlr.gov/api/nsrdb/v2/solar/nsrdb-msg-v1-0-0-download.csv"
RN_EP    = "https://www.renewables.ninja/api/data/wind"

MOUNT, SYS_LOSS, DC_AC = "single-axis", 0.14, 1.2
TURBINE, HUB_M = "Vestas V112 3000", 84   # per-plant override columns can be added later

HOURS = pd.date_range(f"{YEAR}-01-01", periods=8760, freq="h", tz="UTC")

# ---------------------------------------------------------------- availability
def availability(cod, index):
    """1.0 from COD onward, 0.0 before; fractional in the COD month is handled
    naturally because this is hourly."""
    cod = pd.Timestamp(cod, tz="UTC")
    return pd.Series((index >= cod).astype(float), index=index)

# ---------------------------------------------------------------- solar
_nsrdb_cache = {}
def fetch_nsrdb(lat, lon):
    key = (round(lat, 2), round(lon, 2))
    if key in _nsrdb_cache:
        return _nsrdb_cache[key]
    params = dict(api_key=NSRDB_KEY, wkt=f"POINT({lon} {lat})", names=str(YEAR),
                  interval="60", utc="true", email=NSRDB_EMAIL, full_name="_",
                  affiliation="_", mailing_list="false", reason="Academic",
                  attributes="ghi,dni,dhi,air_temperature,wind_speed")
    r = requests.get(NSRDB_EP, params=params, timeout=180); r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), skiprows=2)
    idx = pd.to_datetime(df[["Year", "Month", "Day", "Hour", "Minute"]]).dt.tz_localize("UTC")
    out = pd.DataFrame({"ghi": df["GHI"].to_numpy(float),
                        "dni": df["DNI"].to_numpy(float),
                        "dhi": df["DHI"].to_numpy(float),
                        "temp_air": df["Temperature"].to_numpy(float),
                        "wind_speed": df["Wind Speed"].to_numpy(float)},
                       index=pd.DatetimeIndex(idx))
    if len(out) > 9000:
        out = out.resample("h").mean()
    # snap :30 stamps to the top of the hour (label = start of averaging interval)
    out.index = out.index.floor("h")
    out = out.reindex(HOURS).interpolate(limit=2)
    _nsrdb_cache[key] = out
    return out

def solar_plant_mw(met, lat, cap_mw, mount=None):
    loc = pvlib.location.Location(lat, 0.0, tz="UTC")  # lon only affects solar pos below
    sp  = pvlib.solarposition.get_solarposition(met.index, lat, met.attrs.get("lon", 36.0))
    zen, azi = sp["apparent_zenith"], sp["azimuth"]
    mount = (mount or MOUNT)
    if mount == "single-axis":
        tr   = pvlib.tracking.singleaxis(zen, azi, gcr=0.35)
        tilt = tr["surface_tilt"].fillna(0.0)
        az   = tr["surface_azimuth"].fillna(180.0)
    else:
        tilt = pd.Series(float(abs(lat)), index=met.index)
        az   = pd.Series(180.0, index=met.index)
    poa  = pvlib.irradiance.get_total_irradiance(tilt, az, zen, azi,
                                                 met["dni"], met["ghi"], met["dhi"])
    pg   = poa["poa_global"].fillna(0.0)
    cell = pvlib.temperature.pvsyst_cell(pg, met["temp_air"], met["wind_speed"])
    dc_pu = pvlib.pvsystem.pvwatts_dc(pg, cell, pdc0=1.0, gamma_pdc=-0.004).fillna(0.0)
    ac_pu = (dc_pu * (1 - SYS_LOSS)).clip(upper=1.0 / DC_AC)
    out = (ac_pu * cap_mw * DC_AC).clip(lower=0.0)
    print(f"   DEBUG poa mean/max {pg.mean():.0f}/{pg.max():.0f} W/m2 | dc_pu max {dc_pu.max():.2f} | ac max {out.max():.1f} MW")
    assert pg.max() > 100, "POA is ~zero: fetch/parse broke - do not proceed"
    return out

# ---------------------------------------------------------------- wind
def fetch_rn_cf(lat, lon):
    args = dict(lat=lat, lon=lon, date_from=f"{YEAR}-01-01", date_to=f"{YEAR}-12-31",
                capacity=1.0, height=HUB_M, turbine=TURBINE, format="csv",
                local_time="false", raw="false")
    r = requests.get(RN_EP, params=args, timeout=180,
                     headers={"Authorization": "Token " + RN_TOKEN})
    if r.status_code == 429:
        sys.exit("Renewables.ninja rate limit (HTTP 429): wait ~1h and re-run.")
    r.raise_for_status()
    pos = r.text.find("time,")
    cf  = pd.read_csv(io.StringIO(r.text[pos:]), index_col=0,
                      parse_dates=True)["electricity"].astype(float)
    if cf.index.tz is None:
        cf.index = cf.index.tz_localize("UTC")
    return cf.reindex(HOURS).fillna(0.0)

# ---------------------------------------------------------------- main
fleet = pd.read_csv(FLEET_CSV)
fleet = fleet[fleet["include_2018"] == 1].copy()
fleet["host_bus_candidate"] = fleet["host_bus_candidate"].fillna("UNMAPPED").replace("", "UNMAPPED")

report, bus_cols = [], {"solar": {}, "wind": {}}
temp_ref = None

for _, p in fleet.iterrows():
    tech, cap = p["tech"], float(p["cap_mw_ac"])
    if tech == "solar":
        met = fetch_nsrdb(p["lat"], p["lon"])
        met.attrs["lon"] = p["lon"]
        if temp_ref is None:
            temp_ref = met["temp_air"]
        mw = solar_plant_mw(met, p["lat"], cap, p.get("mount"))
    elif tech == "wind":
        mw = fetch_rn_cf(p["lat"], p["lon"]) * cap
        time.sleep(12)                      # RN free-tier pacing
    else:
        continue
    start = p.get("export_start_date")
    start = p["cod_date"] if (pd.isna(start) or start == "") else start
    mw = mw * availability(start, HOURS)
    bias = p.get("bias_factor")
    if bias is not None and not pd.isna(bias) and str(bias) != "":
        mw = mw * float(bias)   # reanalysis bias correction (cross-year, see wind_bias_2016_17.py)
    mw = mw.clip(upper=cap)     # physical saturation: no plant exceeds nameplate
                                # (the scalar correction saturates at high-wind hours - DISCLOSE)
    bus = str(p["host_bus_candidate"])
    bus_cols[tech][bus] = bus_cols[tech].get(bus, 0.0) + mw
    gwh = mw.sum() / 1000
    eff = mw.mean() / cap if cap else 0
    report.append(f"{p['plant_site_name']:<45s} {tech:5s} {cap:6.1f} MW  COD {p['cod_date']}  "
                  f"-> {gwh:6.1f} GWh  (annualized CF incl. COD ramp {100*eff:.0f}%)")
    print(report[-1])

for tech in ("solar", "wind"):
    wide = pd.DataFrame(bus_cols[tech], index=HOURS)
    wide[f"{tech}_MW"] = wide.sum(axis=1)
    wide.to_csv(f"{tech}_2018_hourly_bybus.csv")
    wide[[f"{tech}_MW"]].to_csv(f"{tech}_2018_hourly.csv")   # drop-in for annual_pcm.py
    tot = wide[f"{tech}_MW"].sum() / 1000
    line = (f"\n{tech.upper()} fleet: {tot:.0f} GWh  |  NEPCO anchor {ANCHORS[tech]:.1f} GWh  "
            f"|  deviation {100*(tot-ANCHORS[tech])/ANCHORS[tech]:+.1f}%  (BLIND — do not rescale)")
    report.append(line); print(line)

if temp_ref is not None:
    temp_ref.rename("temp_air").to_csv("temp_2018_hourly.csv")

open("re_fleet_2018_report.txt", "w").write("\n".join(report))
print("\nwrote *_bybus.csv, fleet totals, temp_2018_hourly.csv, re_fleet_2018_report.txt")
print("If deviation > ~10%: fix the INVENTORY (capacities/CODs) or conversion params — never rescale.")