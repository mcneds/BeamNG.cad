"""Plan fixed-coefficient numerical ballast redistribution; never edit a package.

Only audited numerical mass may be removed. Each recorded loaded-node target
and redistributed CAD contribution is a lower bound. Non-front/chassis nodes
are frozen, total mass cannot increase, and added mass has a per-node cap.
"""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from vehicle_revisions import load_baseline
from angular_screen import matrices,symmetric_step_operator
from frame_harness.build import node_table
from mass_motion import motion_cost
from ballast_optimization import minimize


def plan(receipt,iterations=200,penalty=20.,limit=3.2):
    _,manifest,contents,identity=load_baseline(receipt)
    paths=[p for p in contents if p.endswith('.jbeam')]
    if len(paths)!=1:raise ValueError('One assembled JBeam required')
    raw=contents[paths[0]];parts=json.loads(raw)
    if len(parts)!=1:raise ValueError('One assembled part required')
    part=next(iter(parts.values()));nodes=node_table(part);names=list(nodes)
    eligible=set(manifest['chassis_nodes'])
    for owner,role in manifest['component_roles'].items():
        if role and role.startswith(('fl_','fr_')) and role.endswith(('_wishbone','_upright')):
            eligible.update(manifest['mass_allocations'][owner])
    motion,details=motion_cost(manifest,sorted(eligible))
    mass=np.array([nodes[n]['options']['nodeWeight'] for n in names]);lower=mass.copy();upper=mass.copy();audit={}
    numerical=manifest['numerical_mass']['nodes']
    for i,n in enumerate(names):
        if n not in eligible:continue
        if n in numerical:
            record=numerical[n];physical=record['redistributed_cad_mass_kg'];added=record['added_mass_kg']
            if abs(record['simulated_mass_kg']-mass[i])>1e-7 or abs(physical+added-mass[i])>1e-7 or added<0:
                raise ValueError('Numerical ballast provenance inconsistent: '+n)
            lower[i]=max(physical,record['target_kg'])
            if lower[i]>mass[i]+1e-8:raise ValueError('Baseline below recorded support target')
            audit[n]=dict(cad_floor_kg=physical,loaded_target_kg=record['target_kg'],removable_ballast_kg=float(mass[i]-lower[i]))
        upper[i]=max(mass[i],min(4*mass[i],mass[i]+10))
    k,c=matrices(part,nodes);operator=symmetric_step_operator(k,c)
    costs=np.array([1+penalty*motion.get(n,0.) for n in names])
    def progress(row):
        if row['iteration']%10==0:print(json.dumps(row),flush=True)
    if not np.isfinite(limit) or not 3.2<=limit<=3.6:
        raise ValueError('Timestep limit must be in [3.2, 3.6]')
    result=minimize(operator,mass,lower,upper,costs,limit=limit,iterations=iterations,progress=progress)
    after=np.array(result.pop('masses'))
    if load_baseline(receipt)[3]!=identity:raise ValueError('Baseline changed during planning')
    result.update(scope=__doc__,status='offline_plan_only',baseline_receipt=str(receipt),
        baseline_jbeam_sha256=hashlib.sha256(raw).hexdigest(),baseline_manifest_sha256=hashlib.sha256((receipt.parent/'manifest.json').read_bytes()).hexdigest(),
        implementation_sha256={n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in {
            'planner':Path(__file__),'optimizer':ROOT/'beamng.cad/FramePipeline/ballast_optimization.py',
            'motion':ROOT/'beamng.cad/FramePipeline/mass_motion.py','screen':ROOT/'beamng.cad/FramePipeline/angular_screen.py'}.items()},
        motion_penalty=penalty,motion_sensitivity=details,ballast_provenance=audit,step_limit=limit,
        reference_mass_kg=float(mass.sum()),planned_mass_kg=float(after.sum()),
        kinetic_mass_change_kg=float(sum((after[i]-mass[i])*motion.get(n,0.) for i,n in enumerate(names))),
        nodes=[dict(name=n,before_kg=float(mass[i]),after_kg=float(after[i]),lower_bound_kg=float(lower[i]),upper_bound_kg=float(upper[i]))
               for i,n in enumerate(names) if abs(after[i]-mass[i])>1e-8],
        limitation='Rest-state symmetric screen only. No graph, physical law, package, CAD input or native qualification changed.')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('receipt',type=Path);p.add_argument('--iterations',type=int,default=200);p.add_argument('--output',type=Path,required=True);p.add_argument('--limit',type=float,default=3.2,help='Explicit rest-state screen limit, recorded in the plan; default remains 3.2');a=p.parse_args()
    if not 1<=a.iterations<=2000:p.error('Iterations must be between 1 and 2000')
    if a.output.exists():p.error('Use a fresh output path')
    if not np.isfinite(a.limit) or not 3.2<=a.limit<=3.6:p.error('Limit must be in [3.2, 3.6]')
    result=plan(a.receipt,a.iterations,limit=a.limit);a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['status','reference_mass_kg','planned_mass_kg','kinetic_mass_change_kg','optimality_gap','final_step_eigenvalue']}))
