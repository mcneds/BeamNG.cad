"""Seek a small mass increment for a prescribed numerical stiffness change.

Cutting-plane relaxation of the rest-state symmetric timestep inequality. This
is a diagnostic plan, not an exported vehicle or native stability certificate.
No original coefficient decreases, physical spring edits or graph edits occur.
The cutting-plane objective is a lower bound; feasible padding is an upper
bound and must not be described as the minimum required mass.
"""
import argparse,copy,hashlib,json,sys
from pathlib import Path
import numpy as np
from scipy.optimize import linprog
from scipy.sparse.linalg import eigsh
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from angular_screen import matrices,symmetric_step_operator
from frame_harness.build import node_table
from rigidity_mass_plan import constraint_factor


def plan(receipt,factor=2.,limit=3.2,maximum_factor=3.,selection='front',motion_penalty=0.,added_budget=None,feasible_reference=None,iterations=None,upper_factor=None,upright_factor=None,motion_reference=None,motion_travel_offsets=None):
    record=json.loads(receipt.read_bytes());manifest=json.loads((receipt.parent/'manifest.json').read_bytes())
    path=next(n for n in record['component_files'] if n.endswith('.jbeam'));raw=(receipt.parent/path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=record['component_files'][path]:raise ValueError('Baseline changed')
    part=next(iter(json.loads(raw).values()));shadow=copy.deepcopy(part);nodes=node_table(part);names=list(nodes)
    frame=set(manifest['chassis_nodes']);locators={n for corner in ('FL','FR') for n in manifest['wheels'][corner]['hardpoint_nodes'].values() if n in frame}
    groups=[frame] if selection in ('front','frame','upper_frame','front_locators') else []
    for owner,role in manifest['component_roles'].items():
        if not role or not role.startswith(('fl_','fr_')):continue
        if (selection in ('front','front_locators') and role.endswith(('_wishbone','_upright'))) or (selection=='upper_frame' and role.endswith('_upper_wishbone')) or (selection=='upper' and role.endswith('_upper_wishbone')):
            if owner not in manifest['rigid_refits']:raise ValueError('Numerical rigid fit required')
            groups.append(set(manifest['mass_allocations'][owner]))
    if selection in ('front','frame','upper_frame','front_locators') and manifest.get('frame_reference',{}).get('mode')!='rigid_reference':raise ValueError('Explicit numerical frame required')
    protected={frozenset(pair) for group in part.get('cadConstraintGroups',{}).values() for pairs in group.values() for pair in pairs}
    changed=[]
    for section in ('beams','torsionbars'):
        for index,row in enumerate(shadow.get(section,[])[1:],1):
            if not isinstance(row,list):continue
            count=4 if section=='torsionbars' else 2
            if not any(set(row[:count])<=group for group in groups):continue
            if selection=='front_locators' and set(row[:count])<=frame and not set(row[:count])&locators:continue
            if section=='beams' and (row[-1].get('beamType','|NORMAL')!='|NORMAL' or frozenset(row[:2]) in protected):raise ValueError('Selected physical spring')
            key='spring' if section=='torsionbars' else 'beamSpring';before=row[-1][key]
            row[-1][key]*=constraint_factor(manifest,row[:count],section,factor,upper_factor,upright_factor)
            changed.append(dict(section=section,index=index,key=key,before=before,after=row[-1][key]))
    if selection in ('front','front_locators'):
        for index,row in enumerate(shadow['hydros'][1:],1):
            if isinstance(row,list) and row[-1].get('inputSource')=='steering_input':
                before=row[-1]['beamSpring'];row[-1]['beamSpring']*=factor
                changed.append(dict(section='hydros',index=index,key='beamSpring',before=before,after=row[-1]['beamSpring']))
                groups.append(set(row[:2]))
    eligible={n for change in changed for n in shadow[change['section']][change['index']][:(4 if change['section']=='torsionbars' else 2)]}
    indices=np.array([i for i,n in enumerate(names) if n in eligible]);mass=np.array([nodes[n]['options']['nodeWeight'] for n in names])
    motion={};motion_report=None
    if motion_travel_offsets is not None and not motion_reference:raise ValueError('Motion travel envelope requires a coupled CAD reference')
    if motion_reference and not motion_penalty:raise ValueError('Coupled reference requires a positive motion penalty')
    if motion_penalty:
        from mass_motion import motion_cost,coupled_motion_cost
        motion,motion_report=(coupled_motion_cost(manifest,[names[i] for i in indices],motion_reference,travel_offsets=motion_travel_offsets)
            if motion_reference else motion_cost(manifest,[names[i] for i in indices]))
    costs=mass[indices]*np.array([1+motion_penalty*motion.get(names[i],0.) for i in indices])
    k,c=matrices(shadow,nodes);a=symmetric_step_operator(k,c)
    x=np.zeros(len(indices));weights=np.ones(len(names));cuts=[];rhs=[];history=[];start=np.random.default_rng(0).normal(size=a.shape[0])
    if added_budget is not None:cuts.append(mass[indices]);rhs.append(added_budget)
    for iteration in range(iterations or (200 if motion_penalty else 100)):
        inv=np.repeat(1/np.sqrt(weights),3);operator=a.multiply(inv[:,None]).multiply(inv[None,:]).tocsr()
        values,vectors=eigsh(operator,k=12,which='LA',tol=1e-9,v0=start)
        peak=float(values[-1]);added=float(mass[indices]@x)
        if iteration%10==0 or peak<=limit+1e-7:print(f'Iteration {iteration}: step {peak:.8f}; added {added:.6f} kg',flush=True)
        history.append(dict(iteration=iteration,step_eigenvalue=peak,added_kg=added))
        if peak<=limit+1e-7:break
        for value,vector in zip(values,vectors.T):
            if value<=limit+1e-8:continue
            unscaled=vector*inv;participation=np.sum(unscaled.reshape(-1,3)**2,axis=1)
            needed=float(unscaled@(a@unscaled)-limit*sum(participation))
            cuts.append(-limit*participation[indices]);rhs.append(-needed)
        fit=linprog(costs,A_ub=np.array(cuts),b_ub=np.array(rhs),bounds=[(0,maximum_factor-1)]*len(indices),method='highs')
        if not fit.success:raise ValueError('Mass plan infeasible under the requested cap: '+fit.message)
        x=fit.x;weights[indices]=1+x
    lower_bound=float(costs@(weights[indices]-1))
    def largest(w):
        inv=np.repeat(1/np.sqrt(w),3);operator=a.multiply(inv[:,None]).multiply(inv[None,:]).tocsr()
        return float(eigsh(operator,k=1,which='LA',tol=1e-9,v0=start,return_eigenvectors=False)[0])
    peak=largest(weights)
    if peak>limit+1e-7:
        original_weights=weights.copy()
        def padded(value):
            trial=original_weights.copy();trial[indices]=np.minimum(maximum_factor,trial[indices]*(1+value));return trial
        low=0.;high=maximum_factor
        if largest(padded(high))<=limit+1e-7:
            for _ in range(24):
                mid=(low+high)/2
                if largest(padded(mid))>limit+1e-7:low=mid
                else:high=mid
            weights=padded(high);peak=largest(weights)
    repair=None;added=float(mass@(weights-1))
    if feasible_reference and added_budget is not None and added>added_budget and peak<=limit+1e-7:
        reference_bytes=Path(feasible_reference).read_bytes();reference=json.loads(reference_bytes)
        if reference.get('status')!='offline_plan_only' or reference['baseline_jbeam_sha256']!=hashlib.sha256(raw).hexdigest() or reference['changed_constraints']!=changed:
            raise ValueError('Feasible reference does not describe the same stiffness problem')
        reference_weights=np.ones(len(names));lookup={n:i for i,n in enumerate(names)}
        for row in reference['nodes']:
            i=lookup[row['name']]
            if row['name'] not in eligible or row['before_kg']!=mass[i]:raise ValueError('Reference node mismatch')
            reference_weights[i]=row['after_kg']/mass[i]
        reference_added=float(mass@(reference_weights-1))
        if np.min(reference_weights)<1 or np.max(reference_weights)>maximum_factor or reference_added>=added_budget or largest(reference_weights)>limit+1e-7:
            raise ValueError('Reference fails the current bounds')
        # A <= limit*diag(m) is convex in nodal mass. Both endpoints have
        # independently passed that same bound; interpolate, then check again.
        fraction=(added-added_budget)/(added-reference_added)
        weights=(1-fraction)*weights+fraction*reference_weights;peak=largest(weights);added=float(mass@(weights-1))
        repair=dict(reference=str(feasible_reference),sha256=hashlib.sha256(reference_bytes).hexdigest(),reference_fraction=fraction,scope='Feasible convex blend; not an optimal-mass claim')
    feasible=peak<=limit+1e-7 and (added_budget is None or added<=added_budget+1e-7)
    return dict(scope=__doc__,status='offline_plan_only' if feasible else 'not_converged_no_candidate',final_step_eigenvalue=peak,mass_lower_bound_kg=lower_bound if not motion_penalty else None,objective_lower_bound=lower_bound,motion_penalty=motion_penalty,motion_sensitivity=motion_report,added_budget_kg=added_budget,added_kinetic_mass_kg=sum(mass[i]*(weights[i]-1)*motion.get(names[i],0.) for i in indices) if motion_penalty and not motion_reference else None,added_normalized_inertia_trace=sum(mass[i]*(weights[i]-1)*motion.get(names[i],0.) for i in indices) if motion_reference else None,baseline_receipt=str(receipt),baseline_jbeam_sha256=hashlib.sha256(raw).hexdigest(),
        motion_reference=str(motion_reference) if motion_reference else None,objective_units='kg + penalty_kg * normalized_trace' if motion_reference else 'kg',
        factor=factor,upper_factor=upper_factor,upright_factor=upright_factor,selection=selection,step_limit=limit,maximum_mass_factor=maximum_factor,history=history,changed_constraints=changed,feasible_repair=repair,implementation_sha256={str(p.name):hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),ROOT/'beamng.cad/FramePipeline/rigidity_mass_plan.py',ROOT/'beamng.cad/FramePipeline/mass_motion.py',ROOT/'beamng.cad/FramePipeline/suspension_inertia.py')},
        nodes=[dict(name=names[i],before_kg=float(mass[i]),after_kg=float(mass[i]*weights[i]),added_kg=float(mass[i]*(weights[i]-1))) for i in indices if weights[i]>1+1e-7],
        total_added_kg=added,limitation='Rest-state tangent only; tire generation, prestress, nonlinear stops and native dynamics are excluded. Mass distribution and inertia change and must be reported. No package has been created.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('receipt',type=Path);p.add_argument('--factor',type=float,default=2.);p.add_argument('--limit',type=float,default=3.2);p.add_argument('--maximum-mass-factor',type=float,default=3.);p.add_argument('--selection',choices=['front','frame','upper_frame','upper','front_locators'],default='front');p.add_argument('--motion-penalty',type=float,default=0.);p.add_argument('--added-budget',type=float);p.add_argument('--feasible-reference',type=Path);p.add_argument('--iterations',type=int);p.add_argument('--output',type=Path,required=True);p.add_argument('--upper-factor',type=float,help='Extra rigidity for front upper arms and upper chassis locators');p.add_argument('--upright-factor',type=float,help='Extra rigidity within front upright bodies only');p.add_argument('--motion-reference',type=Path,help='CAD project for coupled travel/steering normalized inertia objective');p.add_argument('--motion-travel-offsets',type=float,nargs='+',help='Explicit evaluation offsets from ride height; does not change physical travel');a=p.parse_args()
    if not 1<a.factor<=3 or not 3.2<=a.limit<=3.6 or not 1<a.maximum_mass_factor<=4:p.error('Invalid experimental bounds')
    if not 0<=a.motion_penalty<=20 or (a.added_budget is not None and not 0<a.added_budget<=50):p.error('Invalid motion penalty or mass allowance')
    if a.iterations is not None and not 1<=a.iterations<=2000:p.error('Iterations must be in [1,2000]')
    if a.upper_factor is not None and not a.factor<=a.upper_factor<=3:p.error('Upper factor must be between base factor and 3')
    if a.upright_factor is not None and not a.factor<=a.upright_factor<=3:p.error('Upright factor must be between base factor and 3')
    r=plan(a.receipt,a.factor,a.limit,a.maximum_mass_factor,a.selection,a.motion_penalty,a.added_budget,a.feasible_reference,a.iterations,a.upper_factor,a.upright_factor,a.motion_reference,a.motion_travel_offsets);a.output.write_text(json.dumps(r,indent=2)+'\n');print('Plan:',r['status'],'; added kg:',r['total_added_kg'])
