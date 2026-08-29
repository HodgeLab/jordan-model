#!/usr/bin/env python3
"""
cross_solve.py — pandapower <-> MATPOWER cross-verification (replaces the SAInt section).

STEP 1 (this script, mode=export):  python cross_solve.py export
  - loads jordan_net.json, runs pandapower AC PF, saves:
      pp_results.csv   (bus vm_pu, va_deg, plus total losses in the header row)
      case_jordan.mat  (MATPOWER case via pandapower's converter)

STEP 2 (MATLAB/Octave, in the same folder):
      mpc = loadcase('case_jordan.mat');
      r = runpf(mpc, mpoption('pf.alg','NR','verbose',0,'out.all',0));
      m = [r.bus(:,1) r.bus(:,8) r.bus(:,9)];               % bus | VM | VA
      writematrix(m, 'mp_results.csv');
      fprintf('MATPOWER losses: %.2f MW\n', sum(real(get_losses(r))));
  (Octave works identically with the MATPOWER package on the path.)

STEP 3 (this script, mode=compare):  python cross_solve.py compare
  - prints max/mean |dVm| (pu), max |dVa| (deg), and the loss difference.
  - Publication target: max |dVm| < 1e-4 pu and loss agreement < 0.1 MW confirm the
    case file is solver-portable. Report the actual numbers, whatever they are.
"""
import sys
import numpy as np, pandas as pd
import pandapower as pp
import pandapower.converter as pc

def export():
    import scipy.io as sio
    net = pp.from_json("jordan_net.json")
    pp.runpp(net, numba=False)
    loss = float(net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum())
    out = pd.DataFrame({"bus": net.bus.index, "vm_pu": net.res_bus.vm_pu,
                        "va_deg": net.res_bus.va_degree})
    out.to_csv("pp_results.csv", index=False)
    mpc = pc.to_mpc(net)["mpc"] if isinstance(pc.to_mpc(net), dict) and "mpc" in pc.to_mpc(net) else pc.to_mpc(net)
    # ---- POST-FIX converter translation (validated against cross-solve diagnostics) ----
    # 1) real generators: MATPOWER VG (gen col 6) must equal the pandapower setpoint;
    # 2) sgen buses must remain PQ (bus type 1) - RE is not a voltage regulator.
    GEN_BUS, VG, BUS_I, BUS_TYPE = 0, 5, 0, 1
    setpts = {int(b): float(v) for b, v in zip(net.gen.bus, net.gen.vm_pu)}
    pv_ref = set(setpts)
    sgen_only = set(int(b) for b in net.sgen.bus) - pv_ref
    fixed_vg = 0
    for r in range(mpc["gen"].shape[0]):
        b = int(mpc["gen"][r, GEN_BUS]) - 1          # mpc numbers = pp index + 1
        if b in setpts and abs(mpc["gen"][r, VG] - setpts[b]) > 1e-9:
            mpc["gen"][r, VG] = setpts[b]; fixed_vg += 1
    fixed_pq = 0
    for r in range(mpc["bus"].shape[0]):
        b = int(mpc["bus"][r, BUS_I]) - 1
        if b in sgen_only and mpc["bus"][r, BUS_TYPE] == 2:   # PV -> PQ
            mpc["bus"][r, BUS_TYPE] = 1; fixed_pq += 1
    sio.savemat("case_jordan.mat", {"mpc": mpc})
    print(f"pandapower AC PF: converged={net.converged}, losses={loss:.2f} MW")
    print(f"converter post-fix: {fixed_vg} gen VG setpoints corrected, "
          f"{fixed_pq} sgen buses restored to PQ")
    print("wrote pp_results.csv, case_jordan.mat -> now run the MATLAB step (see docstring)")

def compare():
    import os
    if not os.path.exists("mp_results.csv"):
        sys.exit("mp_results.csv not found - run the MATLAB/Octave step first (see docstring).")
    ppr = pd.read_csv("pp_results.csv")
    # robust read: auto-detect delimiter, tolerate a header row, coerce to numeric
    mpr = pd.read_csv("mp_results.csv", header=None, sep=None, engine="python")
    mpr = mpr.apply(pd.to_numeric, errors="coerce").dropna(how="any")
    if mpr.shape[1] < 3 or len(mpr) < 10:
        print("mp_results.csv does not look like [bus, VM, VA] rows. First lines:")
        print(open("mp_results.csv").read().splitlines()[:3])
        sys.exit("Regenerate it with the writematrix snippet in the docstring.")
    mpr.columns = ["bus", "vm_pu", "va_deg"] + [f"x{i}" for i in range(mpr.shape[1] - 3)]
    # MATPOWER bus numbers = pandapower index + 1 (converter convention); align on order
    n = min(len(ppr), len(mpr))
    dvm = np.abs(ppr.vm_pu.values[:n] - mpr.vm_pu.values[:n])
    dva = np.abs(ppr.va_deg.values[:n] - mpr.va_deg.values[:n])
    # slack-angle offset: compare angles relative to each solver's slack
    dva = np.abs(dva - dva.min())
    print(f"buses compared: {n}")
    print(f"|dVm|  max {dvm.max():.2e} pu   mean {dvm.mean():.2e} pu")
    print(f"|dVa|  max {dva.max():.2e} deg  mean {dva.mean():.2e} deg (slack-referenced)")
    # ---- localization: where does the disagreement live? ----
    net = pp.from_json("jordan_net.json")
    diag = pd.DataFrame({"bus": ppr.bus.values[:n], "vn_kv": net.bus.vn_kv.values[:n],
                         "pp_vm": ppr.vm_pu.values[:n], "mp_vm": mpr.vm_pu.values[:n],
                         "dvm": dvm})
    diag["has_shunt"] = diag.bus.isin(net.shunt.bus.values)
    diag["has_gen"]   = diag.bus.isin(net.gen.bus.values)
    diag["has_sgen"]  = diag.bus.isin(net.sgen.bus.values)
    top = diag.sort_values("dvm", ascending=False).head(10)
    print("\ntop-10 deviation buses:")
    print(top.to_string(index=False))
    sh = diag[diag.has_shunt].dvm.mean(); nosh = diag[~diag.has_shunt].dvm.mean()
    print(f"\nmean |dVm| at shunt buses {sh:.2e} vs non-shunt {nosh:.2e}"
          f"  -> ratio {sh/max(nosh,1e-12):.1f}x (>>1 implicates shunt conversion)")
    print("\nIf max|dVm| < 1e-4 pu: report as agreement to numerical precision.")
    print("If larger: usual suspects are shunt sign conventions and transformer tap side "
          "in the converter - investigate before reporting, do not average away.")

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "export"
    export() if mode == "export" else compare()