"""Search existing housing nodes for a stronger torque triangle; no graph edits."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import numpy as np


def inertia(nodes,names):
    xyz=np.array([nodes[n]['position'] for n in names],float)
    mass=np.array([nodes[n]['mass_kg'] for n in names],float)
    xyz-=mass@xyz/mass.sum()
    tensor=sum(m*(np.dot(p,p)*np.eye(3)-np.outer(p,p)) for m,p in zip(mass,xyz))
    try:value=1/np.linalg.solve(tensor,[1.,0,0])[0]
    except np.linalg.LinAlgError:return 0.
    return float(value) if np.isfinite(value) and value>0 else 0.


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();manifest=json.loads(a.manifest.read_text());nodes=manifest['nodes'];results={}
    for corner,wheel in manifest['wheels'].items():
        owner=wheel.get('drive_reaction_owner')
        if not owner:continue
        names=sorted(n for n,v in nodes.items() if v['component']==owner)
        current=[wheel['reaction_nodes'][k] for k in ('torqueCoupling','torqueArm','torqueArm2')]
        best=(0.,None)
        for first,last in itertools.combinations(names,2):
            axis=np.array(nodes[last]['position'])-nodes[first]['position'];length=np.linalg.norm(axis)
            if length<1e-12 or abs(axis[0])/length<=.95:continue
            for third in names:
                if third in (first,last):continue
                arm=np.linalg.norm(np.cross(axis,np.array(nodes[third]['position'])-nodes[first]['position']))/length
                if arm<.01:continue
                triangle=[first,third,last];value=inertia(nodes,triangle)
                if value>best[0]:best=(value,triangle)
        current_i=inertia(nodes,current)
        results[corner]=dict(owner=owner,current_nodes=current,current_inertia_kg_m2=current_i,
            best_existing_nodes=best[1],best_inertia_kg_m2=best[0],ratio=best[0]/current_i,
            component_mass_kg=sum(nodes[n]['mass_kg'] for n in names),
            current_node_masses_kg=[nodes[n]['mass_kg'] for n in current],
            scope='Free three-node transverse recoil metric; assembled rigidity and native torque routing are not inferred')
    result=dict(manifest=str(a.manifest),manifest_sha256=hashlib.sha256(a.manifest.read_bytes()).hexdigest(),
        qualified=False,geometry_changed=False,results=results)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
