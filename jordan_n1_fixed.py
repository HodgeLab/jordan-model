import csv, numpy as np, pandapower as pp, pandapower.topology as top, networkx as nx

BASEMVA = 100.0
BACKBONE = {3, 11, 18, 29, 30, 32, 40, 43, 44, 49, 57, 61, 62}
TWIN = lambda b: b + 200
L400 = {
    (3, 18): 30,
    (18, 11): 30,
    (11, 32): 20,
    (29, 32): 25,
    (29, 30): 30,
    (40, 43): 20,
    (43, 44): 15,
    (43, 49): 25,
    (44, 49): 25,
    (49, 57): 90,
    (57, 61): 150,
    (61, 62): 30,
}
len400 = lambda a, b: L400.get((a, b)) or L400.get((b, a)) or 40
LEN132 = {"north": 15.0, "central": 25.0, "south": 45.0}
SC = {132: (0.075, 0.40, 8.9, 145), 400: (0.025, 0.30, 12.75, 1000)}
edges = []
for row in csv.DictReader(open("jordan_pmu_edges_reconstructed.csv")):
    if row["from_bus"].startswith("#"):
        continue
    a, b = row["from_bus"], row["to_bus"]
    if not a.startswith("TIE") and not b.startswith("TIE"):
        edges.append((int(a), int(b), row["region"]))
buses132 = sorted({x for e in edges for x in e[:2]})
LOAD0 = {
    1: 106,
    5: 60,
    6: 133,
    8: 56,
    9: 25,
    10: 59,
    13: 80,
    14: 76,
    15: 131,
    16: 50,
    17: 172,
    18: 90,
    19: 30,
    20: 8,
    23: 13,
    24: 4,
    25: 53,
    26: 109,
    27: 106,
    28: 93,
    29: 28,
    31: 51,
    33: 98,
    34: 51,
    35: 44,
    36: 136,
    38: 40,
    39: 3,
    40: 60,
    41: 102,
    42: 141,
    43: 12,
    44: 86,
    45: 40,
    46: 52,
    47: 52,
    48: 83,
    50: 18,
    51: 21,
    52: 43,
    54: 27,
    55: 4,
    56: 52,
    58: 29,
    59: 20,
    60: 35,
    62: 62,
    63: 15,
    64: 27,
    65: 29,
    68: 13,
}
scale = 3205.0 / sum(LOAD0.values())
LOAD = {k: round(v * scale, 1) for k, v in LOAD0.items()}
PF = 0.88
QF = ((1 - PF**2) ** 0.5) / PF
SHUNT = {b: round(LOAD[b] * QF * 0.75, 1) for b in LOAD if LOAD[b] > 15}
GEN = {
    TWIN(11): [1150, "slack", 18],
    TWIN(30): [380, "PV", 20],
    TWIN(57): [373, "PV", 21],
    TWIN(29): [485, "PV", 22],
    TWIN(40): [573, "PV", 38],
    TWIN(49): [250, "PV", 30],
    TWIN(61): [400, "PV", 45],
    12: [200, "PV", 50],
    21: [150, "PV", 40],
}
REN = {66: [280, 0], 64: [400, 0]}
JERICHO = {47: 10}
net = pp.create_empty_network(sn_mva=BASEMVA)
b2i = {}
for b in buses132:
    b2i[b] = pp.create_bus(net, vn_kv=132)
for b in sorted(BACKBONE):
    b2i[TWIN(b)] = pp.create_bus(net, vn_kv=400)


def add_corridor(fa, fb, kv, L):
    r, x, c, rate = SC[kv]
    im = rate / (np.sqrt(3) * kv)
    for _ in range(2):
        pp.create_line_from_parameters(
            net,
            b2i[fa],
            b2i[fb],
            length_km=L,
            r_ohm_per_km=r,
            x_ohm_per_km=x,
            c_nf_per_km=c,
            max_i_ka=im,
        )


for a, b, region in edges:
    if a in BACKBONE and b in BACKBONE:
        add_corridor(TWIN(a), TWIN(b), 400, len400(a, b))
    else:
        add_corridor(a, b, 132, LEN132[region])
add_corridor(TWIN(30), TWIN(49), 400, 50)
for b in sorted(BACKBONE):
    for _ in range(2):
        pp.create_transformer_from_parameters(
            net,
            b2i[TWIN(b)],
            b2i[b],
            sn_mva=400,
            vn_hv_kv=400,
            vn_lv_kv=132,
            vk_percent=12,
            vkr_percent=0.4,
            pfe_kw=0,
            i0_percent=0,
        )
for b, p in LOAD.items():
    pp.create_load(net, b2i[b], p_mw=p, q_mvar=round(p * QF, 2))
for b, p in JERICHO.items():
    pp.create_load(net, b2i[b], p_mw=p, q_mvar=0)
for b, q in SHUNT.items():
    pp.create_shunt(net, b2i[b], q_mvar=-q, p_mw=0)
gmap = {}
for bus, (pmax, kind, cost) in GEN.items():
    gi = pp.create_gen(
        net,
        b2i[bus],
        p_mw=300,
        vm_pu=1.03 if kind == "slack" else 1.02,
        min_p_mw=0,
        max_p_mw=pmax,
        slack=(kind == "slack"),
        controllable=True,
    )
    pp.create_poly_cost(net, gi, "gen", cp1_eur_per_mw=cost, cp0_eur=0)
    gmap[gi] = cost
for bus, (pmax, cost) in REN.items():
    si = pp.create_sgen(
        net, b2i[bus], p_mw=200, q_mvar=0, min_p_mw=0, max_p_mw=pmax, controllable=True
    )
    pp.create_poly_cost(net, si, "sgen", cp1_eur_per_mw=0, cp0_eur=0)
si = pp.create_sgen(
    net,
    b2i[TWIN(61)],
    p_mw=0,
    q_mvar=0,
    min_p_mw=0,
    max_p_mw=120,
    controllable=True,
    name="Egypt",
)
pp.create_poly_cost(net, si, "sgen", cp1_eur_per_mw=117, cp0_eur=0)
net.line["max_loading_percent"] = 100
net.trafo["max_loading_percent"] = 100
net.bus["min_vm_pu"] = 0.95
net.bus["max_vm_pu"] = 1.05
net.gen["min_q_mvar"] = -200
net.gen["max_q_mvar"] = 300
net.sgen["min_q_mvar"] = -100
net.sgen["max_q_mvar"] = 100
# --- economic base via DC-OPF, then FIX dispatch for N-1 ---
pp.rundcopp(net)
_opfcost = net.res_cost
for gi in net.gen.index:
    net.gen.at[gi, "p_mw"] = net.res_gen.p_mw.at[gi]
for si in net.sgen.index:
    net.sgen.at[si, "p_mw"] = net.res_sgen.p_mw.at[si]
pp.rundcpp(net)
basemax = net.res_line.loading_percent.abs().max()
print(
    "Economic base (DC-OPF dispatch): max line loading %.0f%% | OPF cost %.0f $/h"
    % (basemax, _opfcost)
)
nb = len(net.bus)
slbus = net.gen.bus[net.gen.slack].values[0]
secure = 0
thermal = []
island = 0
ncont = 0


def conn():
    g = top.create_nxgraph(net, respect_switches=True)
    return len(nx.node_connected_component(g, slbus))


for tbl_name in ["line", "trafo"]:
    tbl = getattr(net, tbl_name)
    for i in list(tbl.index):
        tbl.at[i, "in_service"] = False
        ncont += 1
        if conn() < nb:
            island += 1
            tbl.at[i, "in_service"] = True
            continue
        pp.rundcpp(net)
        mx = net.res_line.loading_percent.abs().max()
        if tbl_name == "trafo" or len(net.res_trafo):
            mx = max(mx, net.res_trafo.loading_percent.abs().max())
        if mx > 100:
            thermal.append((tbl_name, i, mx))
        else:
            secure += 1
        tbl.at[i, "in_service"] = True
print("\nN-1 CONTINGENCY (single circuit / single transformer, economic base):")
print("  Total contingencies   : %d" % ncont)
print("  N-1 SECURE            : %d  (%.0f%%)" % (secure, 100 * secure / ncont))
print(
    "  Thermal overload      : %d  (%.0f%%)"
    % (len(thermal), 100 * len(thermal) / ncont)
)
print("  Islanding (radial)    : %d  (%.0f%%)" % (island, 100 * island / ncont))
if thermal:
    print(
        "  worst:",
        [(t, i, round(m)) for t, i, m in sorted(thermal, key=lambda x: -x[2])[:6]],
    )
