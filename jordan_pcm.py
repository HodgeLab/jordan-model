#!/usr/bin/env python3
"""Jordan reduced Production Cost Model - two representative weeks (168h each).
Max-peak-load week (winter, low solar) and Min-net-load week (spring, high solar).
Profiles synthesized from NEPCO 2018 anchors + COVID-paper daily shapes. UC params = typical-by-tech.
Chronological merit-order commitment w/ min-up/down + startup costs. SYNTHETIC/ILLUSTRATIVE."""
import numpy as np, csv
np.random.seed(7)

# ---------------- UC parameters (typical values by technology) ----------------
# plant: [Pmax, cost$/MWh, tech, Pmin_frac, minup_h, mindown_h, startup_$/MW]
UC={
 'Samra (SEPGCO)':     [1150,18,'CCGT',0.45,4,3,60],
 'Amman East (IPP1)':  [380, 20,'CCGT',0.45,4,3,60],
 'Qatrana (IPP2)':     [373, 21,'CCGT',0.45,4,3,60],
 'Zarqa (ACWA)':       [485, 22,'CCGT',0.45,4,3,60],
 'IPP4 (Levant)':      [250, 30,'CCGT',0.45,4,3,60],
 'IPP3 (Amman Asia)':  [573, 38,'GT',  0.25,1,1,30],
 'Aqaba steam':        [400, 45,'Steam',0.40,8,6,100],
 'Rehab':              [200, 50,'Steam',0.40,8,6,100],
 'Risha':              [150, 40,'GT',  0.25,1,1,30],
}
WIND_CAP=280; SOLAR_CAP=700; EGYPT_CAP=120; EGYPT_COST=117
units=[dict(name=n,pmax=v[0],cost=v[1],tech=v[2],pmin=v[0]*v[3],minup=v[4],mindown=v[5],su=v[6]) for n,v in UC.items()]

# ---------------- profile synthesis ----------------
# normalized 24h load shapes (fraction of that day's peak)
WIN=np.array([.66,.63,.61,.60,.61,.64,.70,.78,.83,.85,.86,.87,.86,.84,.83,.84,.88,.95,1.0,.99,.95,.89,.80,.72]) # winter, 6pm peak
SPR=np.array([.70,.66,.63,.61,.61,.63,.68,.75,.82,.86,.88,.89,.88,.86,.84,.83,.85,.90,.95,1.0,.96,.90,.82,.75]) # shoulder
def week(shape,daypeak,wknd=0.92):
    L=[]
    for d in range(7):
        f=wknd if d>=5 else 1.0
        L.extend(shape*daypeak*f)
    return np.array(L)
def solar_week(cap,cf_mid,sunrise=6,sunset=18):
    s=[]
    for d in range(7):
        for h in range(24):
            if sunrise<=h<=sunset:
                x=(h-(sunrise+sunset)/2)/((sunset-sunrise)/2)
                s.append(max(0,cap*cf_mid*(1-x*x)))
            else: s.append(0.0)
    return np.array(s)
def wind_week(cap,mean_cf):
    base=mean_cf+0.12*np.sin(np.linspace(0,7*2*np.pi,168)+1)  # diurnal-ish, higher at night
    noise=0.06*np.random.randn(168)
    return np.clip((base+noise)*cap,0.05*cap,0.95*cap)

# WEEK A: max peak load (winter) - daily peak 3205, low solar CF
loadA=week(WIN,3205); solarA=solar_week(SOLAR_CAP,0.42,7,17); windA=wind_week(WIND_CAP,0.32)
# WEEK B: min net load (spring) - mild demand peak ~2450, high solar CF
loadB=week(SPR,2450,0.88); solarB=solar_week(SOLAR_CAP,0.68,6,18); windB=wind_week(WIND_CAP,0.40)

def netload(L,S,W): return L-S-W

# ---------------- chronological commitment + dispatch ----------------
def run_week(load,solar,wind,label):
    H=len(load); merit=sorted(units,key=lambda u:u['cost'])
    on={u['name']:False for u in units}; ontime={u['name']:0 for u in units}; offtime={u['name']:99 for u in units}
    tot_fuel=0.0; tot_start=0.0; starts={u['name']:0 for u in units}
    energy={u['name']:0.0 for u in units}; curt=0.0; imp=0.0; netl=[]; margprice=[]
    for h in range(H):
        re=solar[h]+wind[h]; nl=load[h]-re; netl.append(nl)
        # commitment target: cheapest units until committed Pmax covers nl*1.08 (reserve)
        need=nl*1.08
        # start units (respect mindown), keep min-up units on
        cap_on=sum(u['pmax'] for u in units if on[u['name']])
        for u in merit:
            if cap_on>=need: break
            if not on[u['name']] and offtime[u['name']]>=u['mindown']:
                on[u['name']]=True; ontime[u['name']]=0; tot_start+=u['su']*u['pmax']; starts[u['name']]+=1
                cap_on+=u['pmax']
        # shut units if surplus (respect min-up), most expensive first
        for u in sorted(units,key=lambda x:-x['cost']):
            if not on[u['name']]: continue
            if ontime[u['name']]<u['minup']: continue
            if cap_on-u['pmax']>=need and sum(x['pmin'] for x in units if on[x['name']] and x['name']!=u['name'])<=nl:
                on[u['name']]=False; offtime[u['name']]=0; cap_on-=u['pmax']
        # economic dispatch of committed units between pmin/pmax
        committed=[u for u in merit if on[u['name']]]
        minsum=sum(u['pmin'] for u in committed)
        # over-generation at minimum -> curtail RE (raise nl) up to available
        if minsum>nl:
            need_curt=minsum-nl
            cc=min(need_curt,re); curt+=cc; nl=load[h]-(re-cc)
            if minsum>nl: nl=minsum  # remainder would be export; clamp
        # dispatch
        rem=nl; disp={}
        for u in committed: disp[u['name']]=u['pmin']; rem-=u['pmin']
        for u in committed:
            add=min(u['pmax']-u['pmin'],max(0,rem)); disp[u['name']]+=add; rem-=add
        mp=committed[-1]['cost'] if committed else 0
        # if still short, import from Egypt then mark unserved
        if rem>1e-6:
            i=min(rem,EGYPT_CAP); imp+=i; rem-=i; tot_fuel+=i*EGYPT_COST; mp=EGYPT_COST
        margprice.append(mp)
        for u in committed:
            energy[u['name']]+=disp[u['name']]; tot_fuel+=disp[u['name']]*u['cost']
        for u in units:
            if on[u['name']]: ontime[u['name']]+=1; offtime[u['name']]=0
            else: offtime[u['name']]+=1; ontime[u['name']]=0
    netl=np.array(netl)
    re_energy=solar.sum()+wind.sum()-curt
    print("\n===== %s ====="%label)
    print("Demand: peak %.0f / min %.0f MW | Net load: peak %.0f / min %.0f MW"%(load.max(),load.min(),netl.max(),netl.min()))
    print("Weekly energy: demand %.0f MWh | renewables used %.0f MWh | curtailed %.0f MWh (%.1f%%)"%(
        load.sum(),re_energy,curt,100*curt/(solar.sum()+wind.sum()+1e-9)))
    print("Total cost: fuel %.0f + startup %.0f = %.0f USD (avg %.1f USD/MWh)"%(tot_fuel,tot_start,tot_fuel+tot_start,(tot_fuel+tot_start)/load.sum()))
    print("Egypt import: %.0f MWh | max net-load ramp: %.0f MW/h"%(imp,np.abs(np.diff(netl)).max()))
    print("%-20s %8s %7s %6s"%("Plant","Energy MWh","CF %","starts"))
    for u in merit:
        e=energy[u['name']]; cf=100*e/(u['pmax']*H)
        if e>1 or starts[u['name']]>0: print("%-20s %8.0f %6.1f %6d"%(u['name'],e,cf,starts[u['name']]))
    return dict(netl=netl,load=load,solar=solar,wind=wind)

rA=run_week(loadA,solarA,windA,"WEEK A: MAX PEAK LOAD (winter)")
rB=run_week(loadB,solarB,windB,"WEEK B: MIN NET LOAD (spring, high solar)")

# save profiles + UC table
with open('jordan_pcm_profiles.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['week','hour','load_MW','solar_MW','wind_MW','netload_MW'])
    for lab,r in [('peak',rA),('minnet',rB)]:
        for h in range(168): w.writerow([lab,h,round(r['load'][h],1),round(r['solar'][h],1),round(r['wind'][h],1),round(r['netl'][h],1)])
with open('jordan_uc_parameters.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['plant','Pmax_MW','cost_$/MWh','tech','Pmin_MW','minup_h','mindown_h','startup_$/MW'])
    for n,v in UC.items(): w.writerow([n,v[0],v[1],v[2],round(v[0]*v[3]),v[4],v[5],v[6]])
print("\nSaved jordan_pcm_profiles.csv and jordan_uc_parameters.csv")
