"""Check wheel support revisions against immutable packaged inputs."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path


def load(folder):
    receipt=json.loads((folder/'static_frame_build.json').read_bytes())
    manifest=json.loads((folder/'manifest.json').read_bytes())
    for name,expected in receipt['component_files'].items():
        if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=expected:raise ValueError('Changed asset: '+name)
    names=[n for n in receipt['component_files'] if n.endswith('.jbeam')]
    if len(names)!=1:raise ValueError('One assembled JBeam required')
    return receipt,manifest,json.loads((folder/names[0]).read_bytes())


def audit(baseline,candidate):
    ar,am,ap=load(baseline);br,bm,bp=load(candidate)
    if len(ap)!=1 or set(ap)!=set(bp):raise ValueError('Part identities changed')
    old=next(iter(ap.values()));new=copy.deepcopy(next(iter(bp.values())));changes={}
    if len(old['pressureWheels'])!=len(new['pressureWheels']):raise ValueError('Wheel count changed')
    for x,y in zip(old['pressureWheels'][1:],new['pressureWheels'][1:]):
        if x[:-1]!=y[:-1] or set(x[-1])!=set(y[-1]):raise ValueError('Wheel topology changed')
        changes[x[0]]={k:[x[-1][k],y[-1][k]] for k in x[-1] if x[-1][k]!=y[-1][k]}
        if not set(changes[x[0]])<={'hubWidth','nodeWeight','hubNodeWeight'}:raise ValueError('Tire coefficients or contact dimensions changed')
        y[-1]=copy.deepcopy(x[-1])
    cases=[('clutch_coupling',old['clutch'],new['clutch'],'native_inertia_kg_m2','lockSpring','lockDampRatio'),
        ('parking_lock',old['gearbox'],new['gearbox'],'native_output_inertia_kg_m2','parkLockSpring','parkLockDampRatio'),
        ('carrier_coupling',next(r[4] for r in old['powertrain'][1:] if r[1]=='rearCarrierTakeoff'),
         next(r[4] for r in new['powertrain'][1:] if r[1]=='rearCarrierTakeoff'),'secondary_inertia_kg_m2','lockSpring','lockDampRatio')]
    for key,x,y,inertia,sk,rk in cases:
        a,b=am['device_contract'][key],bm['device_contract'][key]
        if a['damping_nm_s_rad']!=b['damping_nm_s_rad'] or x[sk]!=y[sk]:raise ValueError('Coupling force law changed')
        if not math.isclose(y[rk]*math.sqrt(y[sk]*b[inertia]),b['damping_nm_s_rad'],rel_tol=1e-12):raise ValueError('Incorrect native damping conversion')
        y[rk]=x[rk]
    if old!=new:raise ValueError('Unplanned JBeam changes')
    assets=lambda r:{n:h for n,h in r['component_files'].items() if not n.endswith('.jbeam')}
    if assets(ar)!=assets(br):raise ValueError('Other assets changed')
    if am['nodes']!=bm['nodes']:raise ValueError('Explicit node geometry or mass changed')
    saved=bm['wheel_support_reuse']['replaced_ballast_kg']
    if not math.isclose(am['expected_dry_mass_kg']-bm['expected_dry_mass_kg'],saved,abs_tol=1e-7):raise ValueError('Mass reduction differs from replaced ballast')
    for corner,w in bm['wheels'].items():
        for key in ('spring_n_m','damper_ns_m','spring_preload_n','coilover_spring','brake_torque_nm','hardpoint_nodes','reaction_nodes'):
            if am['wheels'][corner].get(key)!=w.get(key):raise ValueError('Physical wheel setting changed: '+key)
    return dict(status='passed',baseline=str(baseline),candidate=str(candidate),
        all_explicit_nodes_and_suspension_constraints_unchanged=True,non_jbeam_assets_unchanged=True,
        changed_wheel_options=changes,coupling_normalization=bm['wheel_support_reuse']['coupling_normalization'],
        baseline_mass_kg=am['expected_dry_mass_kg'],candidate_mass_kg=bm['expected_dry_mass_kg'],
        minimum_loaded_kg=min(bm['nodes'][n]['mass_kg'] for n in bm['numerical_mass']['nodes']),
        hashes={str(p):hashlib.sha256((p/'static_frame_build.json').read_bytes()).hexdigest() for p in (baseline,candidate)},
        scope='Preserved suspension/brake/tire coefficients and intended coupling laws; internal rim width and native hub inertia change. Native validation required.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline',type=Path);p.add_argument('candidate',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=audit(a.baseline,a.candidate);a.output.write_text(json.dumps(result,indent=2)+'\n')
    print('Wheel reuse input audit passed: '+str(a.output))
