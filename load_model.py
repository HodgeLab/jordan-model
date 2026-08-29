#!/usr/bin/env python3
"""
load_model.py — synthesize a time-synchronous 8,760-hour 2018 demand series.
Uses the SAME-YEAR temperature (from the NSRDB pull, or any 2018 reanalysis), a diurnal
shape, and a calendar (weekday/weekend + Ramadan + holidays), calibrated so the series
reproduces the NEPCO 2018 anchors. RUN ON YOUR MACHINE.

Output: load_2018_hourly.csv  (8760 rows: datetime, load_MW)

Approach (documented assumption, to refine if you have a sourced JO load–temperature model):
  load = base_diurnal(hour, day_type) * (1 + cooling*CDH + heating*HDH) * calendar_factor
then linearly rescaled so peak = PEAK_MW and energy ≈ ANNUAL_GWH (load factor ≈ LF).

VERIFY: exact Ramadan dates, the holiday list, and the temperature file path/column.
"""
import numpy as np, pandas as pd

YEAR = 2018
PEAK_MW = 3205.0
ANNUAL_GWH = 18913.0   # NEPCO 2018 total purchases (Table 11)
LF = 0.674             # = 18913 GWh / (3205 MW x 8760 h), NEPCO-derived, replaces the 0.65 guess
T_COMFORT = 21.0  # deg C, neutral temperature
K_COOL = 0.018  # fractional load rise per cooling degree-hour  (TUNE to anchors)
K_HEAT = 0.012  # fractional load rise per heating degree-hour  (TUNE to anchors)
RAMADAN = ("2018-05-16", "2018-06-14")  # VERIFY
HOLIDAYS = [
    "2018-01-01",
    "2018-05-01",
    "2018-05-25",
    "2018-06-15",
    "2018-06-16",
    "2018-08-21",
    "2018-08-22",
    "2018-09-11",
    "2018-11-30",
    "2018-12-10",
    "2018-12-25",
]  # VERIFY/extend

# diurnal shape (24 values, relative) — residential-heavy: morning + strong evening peak
WEEKDAY = np.array(
    [
        0.62,
        0.58,
        0.55,
        0.54,
        0.55,
        0.60,
        0.70,
        0.80,
        0.85,
        0.86,
        0.86,
        0.87,
        0.88,
        0.87,
        0.86,
        0.86,
        0.88,
        0.93,
        1.00,
        0.99,
        0.95,
        0.86,
        0.76,
        0.68,
    ]
)
WEEKEND = WEEKDAY * 0.93
RAMADAN_SHAPE = np.roll(WEEKDAY, 2) * 1.02  # activity shifts later (post-iftar evening)


def load_temperature():
    """Return a 2018 hourly air-temperature Series (UTC). Replace with your NSRDB/ERA5 file."""
    try:
        s = pd.read_csv("temp_2018_hourly.csv", index_col=0, parse_dates=True)[
            "temp_air"
        ]
        return s
    except FileNotFoundError:
        # placeholder seasonal+diurnal synthetic temperature so the script runs end-to-end;
        # REPLACE with the real same-year temperature used for solar/wind (time-synchrony!).
        idx = pd.date_range(f"{YEAR}-01-01", periods=8760, freq="h", tz="UTC")
        doy = idx.dayofyear.values
        hr = idx.hour.values
        seasonal = 18 - 12 * np.cos(
            2 * np.pi * (doy - 200) / 365
        )  # ~6C winter, ~30C summer mean
        diurnal = 6 * np.sin(2 * np.pi * (hr - 9) / 24)
        return pd.Series(seasonal + diurnal, index=idx, name="temp_air")


def build(k_cool=None):
    temp = load_temperature()
    idx = temp.index
    ram0, ram1 = pd.Timestamp(RAMADAN[0], tz="UTC"), pd.Timestamp(RAMADAN[1], tz="UTC")
    hol = set(pd.to_datetime(HOLIDAYS).date)
    base = np.empty(len(idx))
    for i, t in enumerate(idx):
        in_ram = ram0 <= t <= ram1
        if t.weekday() >= 5 or t.date() in hol:  # Fri/Sat weekend in JO, or holiday
            shape = WEEKEND
        elif in_ram:
            shape = RAMADAN_SHAPE
        else:
            shape = WEEKDAY
        base[i] = shape[t.hour]
    cdh = np.maximum(temp.values - T_COMFORT, 0)
    hdh = np.maximum(T_COMFORT - temp.values, 0)
    kc = K_COOL if k_cool is None else k_cool
    raw = base * (1 + kc * cdh + K_HEAT * hdh)
    # rescale to hit the peak; check load factor
    load = raw / raw.max() * PEAK_MW
    lf = load.mean() / load.max()
    return load, lf, idx


def calibrate():
    """Bisect K_COOL so the load factor hits the NEPCO-derived LF (=> energy ~= ANNUAL_GWH,
    since peak is pinned). Calibrated INPUT by design - dispatch mix stays the validation."""
    lo, hi = 0.005, 0.08
    for _ in range(40):
        mid = (lo + hi) / 2
        _, lf, _ = build(mid)
        if lf > LF:
            lo = mid     # too flat -> sharpen summer peaks
        else:
            hi = mid
    load, lf, idx = build((lo + hi) / 2)
    print(f"calibrated K_COOL = {(lo+hi)/2:.4f}")
    return load, lf, idx


def finish(load, lf, idx):
    print(
        f"load factor {lf:.3f} (NEPCO target {LF})  peak {load.max():.0f} min {load.min():.0f} MW"
    )
    if ANNUAL_GWH > 0:
        e = load.sum()/1000
        print(f"annual energy {e:.0f} GWh (target {ANNUAL_GWH:.0f}, {100*(e-ANNUAL_GWH)/ANNUAL_GWH:+.1f}%)")
    pd.DataFrame({"load_MW": load}, index=idx).to_csv("load_2018_hourly.csv")
    print("wrote load_2018_hourly.csv  (peak, LF, and energy anchored to NEPCO 2018)")


if __name__ == "__main__":
    finish(*calibrate())