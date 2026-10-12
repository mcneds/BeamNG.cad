"""Read-only rigid-template deformation spectrum from sealed CAD allocations."""
import argparse,itertools,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from rigid_bracing import reinforce,gradient
from frame_harness.projection import axial_columns,modal_frequencies
p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);a=p.parse_args();m=json.loads(a.manifest.read_text())
for owner,allocation in m['mass_allocations'].items():
    if not any(t in owner for t in ('wishbone','upright','trailing_arm')):continue
    names=list(allocation);xyz=np.array([m['nodes'][n]['position'] for n in names]);masses=np.array(list(allocation.values()))
    edges=list(itertools.combinations(range(len(names)),2));springs,damp,torsions=reinforce(xyz,edges,masses)
    axial,_,_=axial_columns(xyz,edges);angular=[]
    for ids,k,c in torsions:
        col=np.zeros_like(xyz);col[ids]=gradient(xyz[ids]);angular.append(col.ravel())
    columns=np.column_stack((axial,np.array(angular).T)) if angular else axial
    frequencies=modal_frequencies(columns,masses,np.r_[springs,[t[1] for t in torsions]])
    print(owner,'mass',masses.sum(),'nodes',len(names),'torsions',len(torsions),'mode range',frequencies[6],frequencies[-1],flush=True)
