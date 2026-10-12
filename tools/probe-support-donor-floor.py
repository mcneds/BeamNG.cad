"""Screen lower donor floors with fixed coefficients; never export a candidate.

Reallocate recovered pre-ballast point masses while retaining each component's
discrete moments, then reapply loaded floors and the existing spectral additions.
Wheel rings are fixed. This tests whether simply lowering the donor threshold is
an available mass saving with the current coefficients. It is not regeneration,
a global optimum or physical calibration. Native tire/stop dynamics are omitted.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from scipy.sparse.linalg import eigsh

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from angular_screen import matrices,symmetric_step_operator
from frame_harness.build import node_table
from support_mass_fit import redistribute
spec=importlib.util.spec_from_file_location('mass_feasibility',Path(__file__).with_name('audit-mass-feasibility.py'))
mf=importlib.util.module_from_spec(spec);spec.loader.exec_module(mf)


def audit(path,donors):
    raw=path.read_bytes(); m=json.loads(raw); allocation,_,rings=mf.recover(m)
    receipt=path.parent/'static_frame_build.json'; record=json.loads(receipt.read_bytes())
    files=[f for f in record['component_files'] if f.endswith('.jbeam')]
    if len(files)!=1:raise ValueError('One assembled JBeam required')
    jpath=path.parent/files[0]; jraw=jpath.read_bytes()
    if hashlib.sha256(jraw).hexdigest()!=record['component_files'][files[0]]:raise ValueError('Changed JBeam')
    parts=json.loads(jraw)
    if len(parts)!=1:raise ValueError('One part required')
    part=next(iter(parts.values())); nodes=node_table(part); names=list(nodes)
    for n,v in nodes.items():
        mf.close(v['options']['nodeWeight'],m['nodes'][n]['mass_kg'],n+' packaged mass')
        if not np.allclose(v['position'],m['nodes'][n]['position'],atol=1e-12,rtol=0):raise ValueError('Position mismatch')
    if set(nodes)!=set(m['nodes']):raise ValueError('Node set mismatch')
    k,c=matrices(part,nodes); operator=symmetric_step_operator(k,c)
    old=np.array([nodes[n]['options']['nodeWeight'] for n in names]); start=np.random.default_rng(0).normal(size=operator.shape[0])
    def screen(masses):
        inv=np.repeat(np.sqrt(old/masses),3)
        scaled=operator.multiply(inv[:,None]).multiply(inv[None,:]).tocsr()
        v,q=eigsh(scaled,k=1,which='LA',tol=1e-9,v0=start)
        shares=np.sum(q[:,0].reshape(-1,3)**2,axis=1); ix=np.argsort(shares)[-8:][::-1]
        return dict(step_eigenvalue=float(v[0]),dominant_nodes=[dict(name=names[i],share=float(shares[i]),mass_kg=float(masses[i])) for i in ix])
    ledger=m['numerical_mass']; targets={n:r['target_kg'] for n,r in ledger['nodes'].items()}
    increments={r['name']:r['added_kg'] for r in ledger.get('spectral_mass_increments',[])}
    result=dict(scope=__doc__,manifest_sha256=hashlib.sha256(raw).hexdigest(),jbeam_sha256=hashlib.sha256(jraw).hexdigest(),
        manifest=str(path.resolve()),baseline=screen(old),trials=[],qualified=False,export_proposed=False,
        implementation_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),Path(__file__).with_name('audit-mass-feasibility.py'),ROOT/'beamng.cad/FramePipeline/support_mass_fit.py')})
    for donor in donors:
        g=SimpleNamespace(nodes={n:dict(position=m['nodes'][n]['position'],options={'nodeWeight':sum(a.get(n,0.) for a in allocation.values())}) for n in names},
            mass_allocations=copy.deepcopy(allocation),rigid_member_allocations={o:{'owner':o} for o in ledger.get('redistribution',{}).get('frozen_split_owners',[])})
        info=redistribute(g,targets,donor)
        masses=np.array([max(g.nodes[n]['options']['nodeWeight'],targets.get(n,0.))+increments.get(n,0.) for n in names])
        trial=dict(donor_floor_kg=donor,redistribution=info,mass_kg=float(sum(masses)+rings),
            numerical_mass_kg=float(sum(masses)+rings-m['cad_dry_mass_kg']),
            floor_violations=[n for n,t in targets.items() if masses[names.index(n)]<t-1e-8],**screen(masses))
        trial['passes_current_rest_screen']=trial['step_eigenvalue']<=m['connection_budget']['step_limit']+1e-7
        result['trials'].append(trial)
        print(f"Donor {donor}: {trial['mass_kg']:.6f} kg; step {trial['step_eigenvalue']:.6f}; passes {trial['passes_current_rest_screen']}",flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('--donors',type=float,nargs='+',default=[.25,.1,.02]);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():p.error('Use a fresh output path')
    r=audit(a.manifest,a.donors);a.output.write_text(json.dumps(r,indent=2,allow_nan=False)+'\n')
