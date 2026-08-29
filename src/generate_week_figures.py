#!/usr/bin/env python3
"""
gen_week_figures.py — fig_profiles.png and fig_dispatch.png for the two
representative weeks, SLICED FROM THE FINAL ANNUAL RUN (no separate weekly
PCM, so the figures can never diverge from the validated dispatch).

Run in the jordan-model folder after the freeze pass (needs the final
load_2018_hourly.csv, solar/wind CSVs, annual_dispatch.csv).
Week selection: max-load week and min-net-load week of the year.
"""
import pandas as pd, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

idx = pd.date_range("2018-01-01", periods=8760, freq="h")
load  = pd.read_csv("load_2018_hourly.csv",  index_col=0).iloc[:, 0].values[:8760]
solar = pd.read_csv("solar_2018_hourly.csv", index_col=0).iloc[:, 0].values[:8760]
wind  = pd.read_csv("wind_2018_hourly.csv",  index_col=0).iloc[:, 0].values[:8760]
disp  = pd.read_csv("annual_dispatch.csv").iloc[:8760]
disp.index = idx
net_load = load - solar - wind

def week_slice(center_h):
    start = max(0, min(8760 - 168, (center_h // 24) * 24 - 72))
    return slice(start, start + 168)

w_peak = week_slice(int(np.argmax(load)))
w_min  = week_slice(int(np.argmin(net_load)))

# ---------------- fig_profiles ----------------
fig, axes = plt.subplots(1, 2, figsize=(12, 3.2), sharey=True)
for ax, w, title in ((axes[0], w_peak, "(a) maximum-peak week"),
                     (axes[1], w_min,  "(b) minimum-net-load week")):
    t = idx[w]
    ax.fill_between(t, 0, solar[w], color="#e8c34a", alpha=0.85, label="solar")
    ax.fill_between(t, solar[w], solar[w] + wind[w], color="#7aa6c2", alpha=0.85, label="wind")
    ax.plot(t, load[w], c="k", lw=1.3, label="demand")
    ax.plot(t, net_load[w], c="#c04a3a", lw=1.1, label="net load")
    ax.set_title(title, fontsize=9); ax.margins(x=0)
    ax.spines[["top", "right"]].set_visible(False)
axes[0].set_ylabel("MW"); axes[0].legend(fontsize=7.5, frameon=False, ncol=2)
fig.autofmt_xdate(); fig.tight_layout()
fig.savefig("fig_profiles.png", dpi=300); plt.close(fig)
print("wrote fig_profiles.png  (weeks:", idx[w_peak][0].date(), "/", idx[w_min][0].date(), ")")

# ---------------- fig_dispatch ----------------
cols = [c for c in ["Risha", "Zarqa (ACWA)", "Qatrana (IPP2)", "Amman East (IPP1)",
        "Samra (SEPGCO)", "Rehab", "Aqaba steam", "IPP4 (Levant)",
        "IPP3 (Amman Asia)"] if c in disp.columns]
fig, axes = plt.subplots(1, 2, figsize=(12, 3.6), sharey=True)
for ax, w, title in ((axes[0], w_peak, "(a) maximum-peak week"),
                     (axes[1], w_min,  "(b) minimum-net-load week")):
    t = idx[w]
    stacks = [solar[w], wind[w]] + [disp[c].values[w] for c in cols]
    ax.stackplot(t, stacks, labels=["solar", "wind"] + [c.split(" (")[0] for c in cols],
                 alpha=0.92)
    ax.plot(t, load[w], c="k", lw=1.2)
    ax.set_title(title, fontsize=9); ax.margins(x=0)
    ax.spines[["top", "right"]].set_visible(False)
axes[0].set_ylabel("MW")
axes[0].legend(fontsize=6.5, ncol=4, frameon=False, loc="upper left")
fig.autofmt_xdate(); fig.tight_layout()
fig.savefig("fig_dispatch.png", dpi=300); plt.close(fig)
print("wrote fig_dispatch.png")