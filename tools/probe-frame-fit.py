"""Read-only convex feasibility probe of an archived calibration's spring graph."""
import argparse,json,sys
from pathlib import Path
import numpy as np
from scipy.linalg import cho_factor,cho_solve,eigh
from scipy.optimize import minimize
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from frame_harness.calibration import load_part
from frame_harness.build import node_table,beam_table
from frame_harness.projection import axial_columns
from frame_harness.generation import scenario
p=argparse.ArgumentParser();p.add_argument('study',type=Path);p.add_argument('output',type=Path);p.add_argument('--complete',action='store_true');p.add_argument('--angular',action='store_true');a=p.parse_args()
r=json.loads((a.study/'solidworks-assigned/report.json').read_text());config=json.loads((a.study/'reference.json').read_text())
part=load_part(a.study/'solidworks-assigned/mochi.jbeam');nodes=node_table(part);names=list(nodes);edges=beam_table(part)
if a.complete:
    import itertools
    existing={frozenset([b['a'],b['b']]) for b in edges}
    for x,y in itertools.combinations(names,2):
        if frozenset([x,y]) not in existing and np.linalg.norm(np.array(nodes[x]['position'])-nodes[y]['position'])>1e-5:
            edges.append(dict(a=x,b=y,spring=1000.))
mass=np.array([nodes[n]['mass'] for n in names]);ends=np.array([[names.index(b['a']),names.index(b['b'])] for b in edges])
xyz=np.array([nodes[n]['position'] for n in names]);columns,_,_=axial_columns(xyz,ends)
limit=(2*np.pi*config['frequency_limit_hz'])**2
bars=[]
if a.angular:
    import itertools
    from rigid_bracing import gradient
    # Three broad reference planes give independently directed angular columns.
    seeds=[]
    for axis in range(3):
        first=int(np.argmin(xyz[:,axis]));second=int(np.argmax(xyz[:,axis]));line=xyz[second]-xyz[first]
        third=int(np.argmax(np.linalg.norm(np.cross(line,xyz-xyz[first]),axis=1)));seeds.append([first,second,third])
    vectors=[];seen=set();minimum=np.linalg.norm(np.ptp(xyz,axis=0))*.04
    for target in range(len(names)):
        for basis in seeds:
            if target in basis:continue
            candidates=[]
            for x,y,z in itertools.permutations(basis):
                axis=xyz[z]-xyz[y];length=np.linalg.norm(axis)
                arms=[np.linalg.norm(np.cross(xyz[v]-xyz[y],axis))/length for v in (x,target)]
                if min(arms)>minimum:candidates.append((min(arms),[x,y,z,target]))
            if not candidates:continue
            _,ids=max(candidates,key=lambda v:v[0]);key=tuple(ids)
            if key in seen:continue
            seen.add(key);bar=np.zeros((len(names),3));bar[ids]=gradient(xyz[ids]);vectors.append(bar.ravel());bars.append([names[i] for i in ids])
    columns=np.column_stack((columns,np.array(vectors).T))
weighted=columns/np.sqrt(np.repeat(mass,3))[:,None];cases=[];matrices={}
scale=limit/np.sum(weighted**2,axis=0)
for name,response in r['responses'].items():
    s=scenario(config,name);free=np.array([3*i+j for i,n in enumerate(names) if n not in s.fixed_nodes for j in range(3)])
    force=np.zeros(len(mass)*3)
    for n,v in s.resolved_load_vectors().items():force[3*names.index(n):3*names.index(n)+3]=v
    target=r['local_mount_reference'].get(name,{}).get('compliance_ceiling_m_n',response['reference']['compliance_m_n'])
    key=tuple(free)
    if key not in matrices:matrices[key]=columns[free]
    cases.append((matrices[key],force[free],target))
latest={};iteration=0
groups={}
for i,case in enumerate(cases):groups.setdefault(id(case[0]),[]).append((i,case))
def objective(x):
    trial=x*scale;value=0.;gradient=np.zeros(len(x));ratios=np.zeros(len(cases));sensitivity=np.zeros((len(cases),len(x)))
    for group in groups.values():
        indices=[i for i,_ in group];matrix=group[0][1][0]
        forces=np.column_stack([case[1] for _,case in group]);targets=np.array([case[2] for _,case in group])
        u=cho_solve(cho_factor((matrix*trial)@matrix.T,check_finite=False),forces,check_finite=False)
        ratios[indices]=np.sum(forces*u,axis=0)/targets
        sensitivity[indices]=(-scale[:,None]*(matrix.T@u)**2/targets).T
    errors=np.maximum(0,ratios-1);worst=float(errors.max())
    if worst:
        normal=errors/worst;norm=float(np.sum(normal**8)**(1/8))
        value+=(worst*norm)**2;gradient+=(2*worst*normal**7/norm**6)@sensitivity
    lam,v=eigh((weighted*trial)@weighted.T,subset_by_value=(limit,np.inf),check_finite=False)
    excess=lam/limit-1;value+=1000*float(excess@excess)
    if len(lam):gradient+=2000*scale*((weighted.T@v)**2@excess)/limit
    latest.update(ratios=ratios.tolist(),projected_ratios=(ratios*max(1,float(lam[-1]/limit)) if len(lam) else ratios).tolist())
    return value,gradient
def callback(x):
    global iteration
    iteration+=1
    if iteration%25==0:print(iteration,'max ratio',max(latest['projected_ratios']),'globals',latest['projected_ratios'][:2],flush=True)
fit=minimize(objective,np.r_[[b['spring'] for b in edges],np.full(len(bars),100.)]/scale,jac=True,method='L-BFGS-B',bounds=[(1e-10,None)]*len(scale),callback=callback,
             options=dict(maxiter=5000,maxcor=50,ftol=1e-13,maxls=40))
objective(fit.x)
a.output.write_text(json.dumps(dict(success=bool(fit.success),message=str(fit.message),iterations=fit.nit,objective=float(fit.fun),edges=[[b['a'],b['b']] for b in edges],torsionbars=bars,springs=(fit.x*scale).tolist(),**latest),indent=2))
print(fit.message,latest,flush=True)
