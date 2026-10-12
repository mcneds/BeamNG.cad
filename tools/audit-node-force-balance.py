"""Cross-check native node force against measured velocity increments.

No model parameters are fitted. The coupon-identified force lag (-1 sample) is
checked with explicit gravity conventions; other lags are diagnostic controls.
Passing is a force-accounting check, not suspension or vehicle qualification.
"""
import argparse,hashlib,json
from pathlib import Path
import numpy as np


def audit(run):
    read=lambda n:json.loads((run/n).read_bytes())
    meta=read('frequency.json');vm=read('frequency_velocities.json');probe=read('probe.json');compiled=read('compiled.json');job=read('job.json')
    if not meta['complete'] or not vm['complete'] or not probe['sources_unchanged'] or probe.get('error'):raise ValueError('Incomplete or changed-source capture')
    if meta['job_id']!=vm['job_id'] or vm['job_id']!=job['id']:raise ValueError('Mismatched recordings')
    names=meta['load_nodes']
    if names!=vm['nodes']:raise ValueError('Force and velocity node order differs')
    loads=np.loadtxt(run/'frequency_loads.csv',delimiter=',',skiprows=1);vel=np.loadtxt(run/'frequency_velocities.csv',delimiter=',',skiprows=1)
    n=meta['samples'];count=len(names);dt=np.diff(vel[:,0]);start=1+2*len(meta['load_beams'])
    if loads.shape!=(n,start+3*count) or vel.shape!=(n,1+3*count) or not np.isfinite(loads).all() or not np.isfinite(vel).all():raise ValueError('Invalid force/velocity arrays')
    if not np.array_equal(loads[:,0],vel[:,0]) or not np.allclose(dt,.0005,atol=2e-9,rtol=0):raise ValueError('Invalid physics timestamps')
    v=vel[:,1:].reshape(n,count,3);f=loads[:,start:].reshape(n,count,3)
    mass=np.array([compiled['actual_nodes'][name]['mass_kg'] for name in names])
    if np.min(mass)<=0:raise ValueError('Invalid compiled mass')
    index=np.arange(2,n-2);ma=mass[None,:,None]*(v[index]-v[index-1])/dt[index-1,None,None]
    gravity=np.array([0.,0.,float(job['gravity'])]);variants=[]
    for lag in (-1,0,1):
        for added in (0,1,-1):
            predicted=f[index+lag]+added*mass[None,:,None]*gravity
            error=ma-predicted
            pernode=np.sqrt(np.mean(np.sum(error*error,axis=2),axis=0))
            denominator=np.sqrt(np.mean(np.sum(ma*ma,axis=2),axis=0))
            variants.append(dict(force_lag_samples=lag,gravity_added=added,relative_rms=float(np.linalg.norm(error)/max(np.linalg.norm(ma),1e-12)),
                nodes=[dict(name=name,mass_kg=float(mass[i]),error_rms_n=float(pernode[i]),relative_rms=float(pernode[i]/max(denominator[i],1e-12))) for i,name in enumerate(names)]))
    expected=min((v for v in variants if v['force_lag_samples']==-1),key=lambda v:v['relative_rms'])
    best=min(variants,key=lambda v:v['relative_rms'])
    return dict(scope=__doc__,samples=n,nodes=count,expected_lag_best=expected,best_observed=best,
        status='force_balance_consistent' if expected['relative_rms']<.01 else 'force_balance_unresolved',
        comparisons=[{k:v for k,v in x.items() if k!='nodes'} for x in variants],
        evidence_sha256={name:hashlib.sha256((run/name).read_bytes()).hexdigest() for name in ('frequency.json','frequency_velocities.json','frequency_velocities.csv','frequency_loads.csv','compiled.json','job.json','probe.json')})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args();r=audit(a.run)
    (a.run/'node_force_balance.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({k:v for k,v in r.items() if k not in ('expected_lag_best','best_observed','evidence_sha256')},indent=2))
