"""Read-only absolute compliance bounds with rigid modes and fixture reactions."""
import argparse,json,sys
from pathlib import Path
import numpy as np
from scipy.linalg import cho_factor,cho_solve
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.build import node_table
from frame_harness.calibration import load_part
from frame_harness.generation import scenario
p=argparse.ArgumentParser();p.add_argument('study',type=Path);a=p.parse_args()
r=json.loads((a.study/'solidworks-assigned/report.json').read_text());config=json.loads((a.study/'reference.json').read_text())
nodes=node_table(load_part(a.study/'solidworks-assigned/mochi.jbeam'));names=list(nodes)
m=np.array([nodes[n]['mass'] for n in names]);xyz=np.array([nodes[n]['position'] for n in names]);xyz-=m@xyz/m.sum()
rigid=np.zeros((3*len(m),6))
for i,v in enumerate(xyz):
    rigid[3*i:3*i+3,:3]=np.eye(3)
    rigid[3*i:3*i+3,3:]=np.cross(np.eye(3),v).T
sqrt=np.sqrt(np.repeat(m,3));q=np.linalg.qr(sqrt[:,None]*rigid)[0]
k=(np.eye(len(sqrt))-q@q.T)*sqrt[:,None]*sqrt[None,:]*(2*np.pi*config['frequency_limit_hz'])**2
records=[];cache={}
for name,response in r['responses'].items():
    s=scenario(config,name);free=tuple(3*i+j for i,n in enumerate(names) if n not in s.fixed_nodes for j in range(3))
    force=np.zeros(len(sqrt))
    for n,v in s.resolved_load_vectors().items():force[3*names.index(n):3*names.index(n)+3]=v
    if free not in cache:cache[free]=cho_factor(k[np.ix_(free,free)])
    f=force[list(free)];bound=float(f@cho_solve(cache[free],f))
    target=r['local_mount_reference'].get(name,{}).get('compliance_ceiling_m_n',response['reference']['compliance_m_n'])
    records.append(dict(name=name,absolute_bound=bound,target=target,bound_ratio=bound/target,actual_ratio=response['compliance_m_n']/target))
print(json.dumps(sorted(records,key=lambda v:v['bound_ratio'],reverse=True)[:25],indent=2))
