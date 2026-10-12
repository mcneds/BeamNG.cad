"""Read-only audit of local CAD yield targets against a sealed frame graph."""
import argparse,json,sys
from pathlib import Path
import numpy as np
from scipy.linalg import cho_factor,cho_solve
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from frame_harness.calibration import load_part,fit_yield_capacities
from frame_harness.build import node_table,beam_table
from frame_harness.projection import axial_columns
from frame_harness.torsion import table,columns as angular_columns
from frame_harness.generation import scenario

p=argparse.ArgumentParser();p.add_argument('study',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
r=json.loads((a.study/'solidworks-assigned/report.json').read_text());config=json.loads((a.study/'reference.json').read_text())
part=load_part(a.study/'solidworks-assigned/mochi.jbeam');nodes=node_table(part);names=list(nodes);beams=beam_table(part);bars=table(part)
xyz=np.array([nodes[n]['position'] for n in names])
columns,_,_=axial_columns(xyz,[[names.index(b['a']),names.index(b['b'])] for b in beams])
if bars:columns=np.column_stack((columns,angular_columns(xyz,[[names.index(n) for n in b['nodes']] for b in bars])))
springs=np.r_[[b['spring'] for b in beams],[b['options']['spring'] for b in bars]]
capacity=np.r_[[b['deform'] for b in beams],[b['options']['deform'] for b in bars]]
groups={};forces={};targets={name:v['reference'] for name,v in r['responses'].items()}
for name in targets:
 s=scenario(config,name);free=tuple(3*i+j for i,n in enumerate(names) if n not in s.fixed_nodes for j in range(3));f=np.zeros(3*len(names))
 for n,v in s.resolved_load_vectors().items():f[3*names.index(n):3*names.index(n)+3]=v
 groups.setdefault(free,[]).append((name,f[list(free)]))
for free,cases in groups.items():
 A=columns[list(free)];u=cho_solve(cho_factor((A*springs)@A.T),np.column_stack([f for _,f in cases]));q=springs[:,None]*(A.T@u)
 for i,(name,_) in enumerate(cases):forces[name]=q[:,i]
trial,fit=fit_yield_capacities(capacity,forces,targets)
responses={name:dict(cad_yield_n=t['first_yield_force_n'],current_yield_n=float(1/np.max(abs(forces[name])/capacity)),envelope_yield_n=float(1/np.max(abs(forces[name])/trial))) for name,t in targets.items()}
result=dict(scope='Read-only capacity envelope probe; no artifacts modified',fit=fit,responses=responses)
a.output.write_text(json.dumps(result,indent=2)+'\n')
print('GLOBAL',json.dumps({k:responses[k] for k in ('flex','torsion')}))
for k,v in sorted(responses.items(),key=lambda kv:kv[1]['current_yield_n']/kv[1]['cad_yield_n'])[:12]:print(k,v)
print('No separating onset',sum(v is None for v in fit['active_beam_indices'].values()),'of',len(targets))
