#!/usr/bin/env python3
"""
scenario_green_corridor.py — derive the post-2019 Green Corridor variant from the
released 2018 base case (jordan_net.json). Writes jordan_net_greencorridor.json.

Changes vs the 2018 base (each sourced/disclosed):
  1. New Ma'an 400/132 kV substation energized: new 400 kV bus at Ma'an, 2x400 MVA
     transformers (NEPCO Table 21: 2019).
  2. One circuit of the Aqaba-Qatrana 400 kV corridor looped in-out of New Ma'an
     (MEZ: existing line cut and looped); the second circuit remains direct.
     Segment lengths: Aqaba-New Ma'an ~110 km, New Ma'an-Qatrana ~120 km
     (map-estimated split of the 230 km corridor - VERIFY).
  3. Green-Corridor wind additions: Fujeij 89 MW (COD 2019) and Shobak 45 MW
     (COD 2019) as zero-cost sgens on the south-western 132 kV chain.
  APPROXIMATION NOTE: the additional Qatrana-New Ma'an 150 km line of JICA T6.3-1
  is NOT separately modeled pending clarification of whether it is distinct from
  the looped circuit; disclose in the dataset README.
"""
import pandapower as pp

BASE = "jordan_net.json"
OUT  = "jordan_net_greencorridor.json"

# pandapower bus indices in the base case (132 kV: index = PMU bus - 1)
MAAN_132, QATRANA_132, AQABA_132 = 61, 56, 60          # PMU 62, 57, 61
SC400 = dict(r_ohm_per_km=0.025, x_ohm_per_km=0.30, c_nf_per_km=12.75, max_i_ka=1000/(3**0.5*400))

net = pp.from_json(BASE)
# locate the 400 kV twins of Qatrana and Aqaba via their transformers
tw = {int(t.lv_bus): int(t.hv_bus) for _, t in net.trafo.iterrows()}
QAT_400, AQ_400 = tw[QATRANA_132], tw[AQABA_132]

# 1) New Ma'an 400 kV bus + 2x400 MVA transformers
NM_400 = pp.create_bus(net, vn_kv=400, name="NEW_MAAN_400 (Green Corridor)")
for _ in range(2):
    pp.create_transformer_from_parameters(
        net, NM_400, MAAN_132, sn_mva=400, vn_hv_kv=400, vn_lv_kv=132,
        vk_percent=12, vkr_percent=0.4, pfe_kw=0, i0_percent=0,
        name="NewMaan 400/132 (2019)")

# 2) loop ONE circuit of Aqaba-Qatrana through New Ma'an
direct = net.line[(net.line.from_bus == QAT_400) & (net.line.to_bus == AQ_400) |
                  (net.line.from_bus == AQ_400) & (net.line.to_bus == QAT_400)]
assert len(direct) == 2, f"expected 2 direct Aqaba-Qatrana circuits, found {len(direct)}"
net.line.at[direct.index[1], "in_service"] = False   # keep row for provenance
net.line.at[direct.index[1], "name"] = "Aqaba-Qatrana ckt2 (looped into New Maan, 2019)"
pp.create_line_from_parameters(net, AQ_400, NM_400, length_km=110, name="Aqaba-NewMaan 400 (loop)", **SC400)
pp.create_line_from_parameters(net, NM_400, QAT_400, length_km=120, name="NewMaan-Qatrana 400 (loop)", **SC400)

# 3) post-2018 Green-Corridor wind (zero marginal cost, PQ)
for bus, mw, name in [(65, 89.0, "wind Fujeij (2019)"),      # PMU 66 = FUJIJ
                      (65, 45.0, "wind Shobak (2019, host VERIFY)")]:
    si = pp.create_sgen(net, bus, p_mw=0, q_mvar=0, min_p_mw=0, max_p_mw=mw,
                        controllable=True, name=name)
    pp.create_poly_cost(net, si, "sgen", cp1_eur_per_mw=0, cp0_eur=0)
net.sgen["min_q_mvar"] = -100
net.sgen["max_q_mvar"] = 100

pp.to_json(net, OUT)
pp.runpp(net, numba=False)
loss = float(net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum())
print(f"Green Corridor scenario: {len(net.bus)} buses, {int(net.line.in_service.sum())} lines in service, "
      f"{len(net.trafo)} trafos")
print(f"AC PF: converged={net.converged}, losses={loss:.2f} MW, "
      f"vmin={net.res_bus.vm_pu.min():.3f}, vmax={net.res_bus.vm_pu.max():.3f}")
print(f"wrote {OUT}")