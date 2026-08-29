#!/usr/bin/env python3
"""
gen_annual_figures.py — produce fig_energy_mix.png and fig_annual_stack.png
from the FINAL frozen PCM outputs (annual_energy_mix.csv, annual_dispatch.csv,
solar/wind CSVs). Run in the jordan-model folder after the freeze pass.
"""
import pandas as pd, numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

mix = pd.read_csv("annual_energy_mix.csv", index_col=0)
# --- Fig 1: model vs NEPCO grouped bars -------------------------------
order = [p for p in ["Samra (SEPGCO)","Amman East (IPP1)","Qatrana (IPP2)",
        "Zarqa (ACWA)","IPP4 (Levant)","IPP3 (Amman Asia)","Rehab","Risha",
        "Aqaba steam","Solar","Wind"] if p in mix.index]
m = mix.loc[order]
x = np.arange(len(order)); w = 0.38
fig, ax = plt.subplots(figsize=(7.2, 3.4))
ax.bar(x - w/2, m["model_GWh"], w, label="Model", color="#33507a")
ax.bar(x + w/2, m["NEPCO_GWh"], w, label="NEPCO 2018", color="#c8a23a")
ax.set_xticks(x); ax.set_xticklabels([o.split(" (")[0] for o in order],
                                     rotation=40, ha="right", fontsize=8)
ax.set_ylabel("Annual energy (GWh)"); ax.legend(frameon=False)
ax.spines[["top","right"]].set_visible(False)
fig.tight_layout(); fig.savefig("fig_energy_mix.png", dpi=300)
print("wrote fig_energy_mix.png")

# --- Fig 2: monthly stacked dispatch ----------------------------------
d = pd.read_csv("annual_dispatch.csv")
d.index = pd.date_range("2018-01-01", periods=len(d), freq="h")
sol = pd.read_csv("solar_2018_hourly.csv", index_col=0).iloc[:, 0].values[:len(d)]
wnd = pd.read_csv("wind_2018_hourly.csv",  index_col=0).iloc[:, 0].values[:len(d)]
d["Solar"], d["Wind"] = sol, wnd
monthly = d.resample("MS").sum() / 1000.0     # GWh
cols = [c for c in ["Solar","Wind","Risha","Zarqa (ACWA)","Qatrana (IPP2)",
        "Amman East (IPP1)","Samra (SEPGCO)","IPP4 (Levant)","IPP3 (Amman Asia)",
        "Rehab","Aqaba steam"] if c in monthly.columns]
fig, ax = plt.subplots(figsize=(7.2, 3.6))
ax.stackplot(monthly.index, [monthly[c] for c in cols],
             labels=[c.split(" (")[0] for c in cols], alpha=0.92)
ax.set_ylabel("Monthly generation (GWh)")
ax.legend(fontsize=7, ncol=4, frameon=False, loc="upper left")
ax.spines[["top","right"]].set_visible(False)
ax.margins(x=0)
fig.tight_layout(); fig.savefig("fig_annual_stack.png", dpi=300)
print("wrote fig_annual_stack.png")