"""Attribute the existing rest-state explicit stability screen to node motion.

This instruments the production screening matrix rather than reimplementing
its constraints. Pressure tires, prestress and nonlinear stops remain excluded.
"""
import argparse,json,sys
from pathlib import Path
import numpy as np
from scipy.sparse import linalg
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from vehicle_revisions import load_baseline
from frame_harness.build import node_table
from rigid_bracing import budget_connections


def audit(receipt,elastic_only=False):
    _,manifest,files,_=load_baseline(receipt)
    part=next(iter(json.loads(next(v for k,v in files.items() if k.endswith('.jbeam'))).values()))
    if elastic_only:
        for section in ('beams','hydros','torsionbars'):
            for row in part.get(section,[])[1:]:
                options=row if isinstance(row,dict) else row[-1]
                if isinstance(options,dict):
                    options['damp' if section=='torsionbars' else 'beamDamp']=0.
                    options['dampCutoffHz']=0.
    nodes=node_table(part);names=list(nodes);original=linalg.eigsh;seen=[]
    def capture(matrix,**kwargs):
        result=original(matrix,**kwargs);seen.append((float(result[0][-1]),matrix.copy()));return result
    linalg.eigsh=capture
    try:budget=budget_connections(part,nodes,[],limit=1e6)
    finally:linalg.eigsh=original
    _,matrix=max(seen,key=lambda x:x[0]);values,vectors=original(matrix,k=6,which='LA',tol=1e-10,v0=np.random.default_rng(0).normal(size=matrix.shape[0]))
    modes=[]
    for value,vector in zip(values[::-1],vectors[:,::-1].T):
        energy=np.sum(vector.reshape(-1,3)**2,axis=1);indices=np.argsort(energy)[-18:][::-1]
        modes.append(dict(step_eigenvalue=float(value),nodes=[dict(name=names[i],fraction=float(energy[i]),mass_kg=nodes[names[i]]['options']['nodeWeight'],
            owners=[manifest['component_roles'].get(o,o) for o,n in manifest['mass_allocations'].items() if names[i] in n]) for i in indices]))
    return dict(scope=__doc__,elastic_only=elastic_only,receipt=str(receipt),screen=budget,modes=modes)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('receipt',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--elastic-only',action='store_true');a=p.parse_args()
    result=audit(a.receipt,a.elastic_only);a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result['modes'][0],indent=2))
