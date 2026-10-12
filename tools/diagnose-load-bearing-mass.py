"""Check whether reaction nodes can reach a mass floor without altering CAD moments."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.optimize import linprog


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--minimum',type=float,default=2.)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if not np.isfinite(a.minimum) or a.minimum<=0:p.error('Minimum must be finite and positive')
    manifest=json.loads(a.manifest.read_text());owners={};results={}
    for wheel in manifest['wheels'].values():
        owner=wheel.get('drive_reaction_owner')
        if owner:
            owners.setdefault(owner,set()).update(wheel['reaction_nodes'][k] for k in
                ('torqueCoupling','torqueArm','torqueArm2'))
    for owner,required in owners.items():
        allocation=manifest['mass_allocations'][owner];names=sorted(allocation)
        xyz=np.array([manifest['nodes'][n]['position'] for n in names])
        original=np.array([allocation[n] for n in names])
        center=original@xyz/original.sum();xyz-=center
        scale=np.linalg.norm(np.ptp(xyz,axis=0));xyz/=scale
        x,y,z=xyz.T
        # Ten independent linear mass moments, centered/scaled to avoid the
        # raw-coordinate cancellation that can conceal inertia changes.
        matrix=np.array([np.ones(len(names)),x,y,z,x*x,y*y,z*z,x*y,x*z,y*z])
        target=matrix@original
        bounds=[(a.minimum if n in required else min(original[i],.0001),None) for i,n in enumerate(names)]
        # Feasibility only. An arbitrary LP vertex is not a production mass fit.
        fit=linprog(np.zeros(len(names)),A_eq=matrix,b_eq=target,bounds=bounds,method='highs')
        result=dict(required_nodes=sorted(required),requested_minimum_kg=a.minimum,
            original_required_masses_kg={n:allocation[n] for n in sorted(required)},
            component_mass_kg=float(original.sum()),feasible=bool(fit.success),solver_message=fit.message,
            scope='Existing-node component mass/COM/inertia feasibility only; no graph changes or native stability claim')
        if fit.success:
            error=matrix@fit.x-target
            result.update(maximum_scaled_moment_error=float(np.max(np.abs(error))),
                diagnostic_allocation_kg=dict(zip(names,map(float,fit.x))))
        results[owner]=result
    report=dict(manifest=str(a.manifest),manifest_sha256=hashlib.sha256(a.manifest.read_bytes()).hexdigest(),
        qualified=False,geometry_changed=False,results=results)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
