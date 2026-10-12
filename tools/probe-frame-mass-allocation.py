"""Diagnostic mass allocation experiment, never a package acceptance bypass."""
import argparse
import json
from pathlib import Path
import sys
import time
import numpy as np
from scipy.optimize import linprog,minimize
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.build import node_table,beam_table,write_json
from frame_harness.cad import read_bodies
from frame_harness.calibration import mass_properties,surface_distances,graph_identity
from frame_harness.elastic_fit import objective
from frame_harness.generation import scenario
from frame_harness.projection import axial_columns

p=argparse.ArgumentParser();p.add_argument('generation',type=Path);p.add_argument('seed',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
read=lambda f:json.loads(f.read_text())
part=read(a.generation/'source/mochi_raw.jbeam')['mochi'];seed=read(a.seed)['mochi']
if graph_identity(part)!=graph_identity(seed):raise ValueError('Warm-start graph differs')
audit=read(a.generation/'study/geometry-audit.json');config=read(a.generation/'source/reference.json');targets=audit['reference_targets_assigned']
materials=read(a.generation/'source/material-snapshot.json')['bodies'];density={v['body_id']:v['density_kg_m3'] for v in materials}
mass,center,inertia=mass_properties(audit['bodies'],[density[v['name']] for v in audit['bodies']])
nodes=node_table(part);names=list(nodes);xyz=np.array([nodes[n]['position'] for n in names]);edges=beam_table(part)
columns,_,_=axial_columns(xyz,[[names.index(e['a']),names.index(e['b'])] for e in edges])
distance=np.min([surface_distances(xyz,body) for body in read_bodies(a.generation/'source/cad_source.dae')],axis=0)
scale=np.linalg.norm(np.ptp(xyz,axis=0));x,y,z=((xyz-center)/scale).T
features=np.array([np.ones(len(names)),x,y,z,y*y+z*z,x*x+z*z,x*x+y*y,-x*y,-x*z,-y*z])
target=np.r_[1,np.zeros(3),inertia.diagonal()/(mass*scale**2),inertia[0,1]/(mass*scale**2),inertia[0,2]/(mass*scale**2),inertia[1,2]/(mass*scale**2)]
cases=[]
for key,value in targets.items():
    case=scenario(config,key);free=[3*i+j for i,n in enumerate(names) if n not in case.fixed_nodes for j in range(3)];load=np.zeros(3*len(names))
    for n,v in case.resolved_load_vectors().items():load[names.index(n)*3:names.index(n)*3+3]=v
    cases.append((columns[free],load[free],value['compliance_m_n']))
results=[]
for influence in (3.,8.):
    prior=1+influence*np.exp(-(distance/(scale*.025))**2)
    allocation=linprog(np.r_[np.zeros(len(names)),-1.],A_ub=np.column_stack((-np.eye(len(names)),prior)),b_ub=np.zeros(len(names)),
        A_eq=np.column_stack((features,np.zeros(len(target)))),b_eq=target,bounds=[(0,None)]*(len(names)+1),method='highs')
    if not allocation.success:raise ValueError(allocation.message)
    masses=allocation.x[:-1]*mass;weighted=columns/np.sqrt(np.repeat(masses,3))[:,None];initial=np.array([e['spring'] for e in beam_table(seed)])
    state={};iterations=0;started=time.monotonic()
    def fun(values):
        value,grad,stats=objective(values,initial,weighted,cases,(2*np.pi*350)**2);state.update(stats);return value,grad
    def callback(values):
        global iterations
        iterations+=1
        if iterations%25==0:
            print(influence,iterations,state,flush=True)
            if max(state['projected_relative_errors'])<.04:raise StopIteration
    fit=minimize(fun,np.zeros(len(initial)),jac=True,method='L-BFGS-B',bounds=[(-6,6)]*len(initial),callback=callback,
                 options=dict(maxiter=600,maxcor=50,ftol=1e-10,maxls=30))
    results.append(dict(influence=influence,iterations=int(fit.nit),elapsed=time.monotonic()-started,mass_kg=mass,
        mass_by_node=dict(zip(names,map(float,masses))),stats=state,springs=(initial*np.exp(fit.x)).tolist()))
    write_json(a.output,results)
