"""Identify angular versus ordinary spring response from force-driven motion."""
import argparse,hashlib,importlib.util,json
from pathlib import Path
import numpy as np
spec=importlib.util.spec_from_file_location('tangent',Path(__file__).with_name('analyze-lbeam-coupon.py'));tangent=importlib.util.module_from_spec(spec);spec.loader.exec_module(tangent)


def analyze(run):
    job=json.loads((run/'job.json').read_bytes());done=json.loads((run/'completion.json').read_bytes());compiled=json.loads((run/'compiled_coupon.json').read_bytes())
    if done.get('status')!='completed' or done['job_id']!=job['id'] or compiled['job_id']!=job['id']:raise ValueError('Incomplete or mismatched force coupon')
    data=np.loadtxt(run/'coupon.csv',delimiter=',',skiprows=1);t=data[:,0];dt=float(np.median(np.diff(t)))
    if data.shape!=(done['samples'],1+36*len(job['coupons'])) or not np.isfinite(data).all() or not .00049<dt<.00051 or t[-1]<job['duration']-.001:raise ValueError('Invalid force coupon data')
    xyz=np.array(job['points']);D=[]
    for a,b in ((0,1),(1,2),(0,2)):
        v=xyz[b]-xyz[a];v/=np.linalg.norm(v);col=np.zeros((3,3));col[a]=-v;col[b]=v;D.append(col.ravel())
    D=np.array(D).T;unit=D@D.T;Ksingle,_=tangent.tangent(xyz,False,True);Ktriple,_=tangent.tangent(xyz,True)
    results=[];selected=(t>2)&(t<job['duration']-.01);index=np.flatnonzero(selected)
    for i,c in enumerate(job['coupons']):
        a=data[:,1+i*36:1+(i+1)*36].reshape(-1,3,12)
        q=(a[:,:,:3]-a[0,:,:3]).reshape(-1,9);v=a[:,:,3:6].reshape(-1,9);force=a[:,:,6:9].reshape(-1,9);external=a[:,:,9:12].reshape(-1,9)
        damping=c['damping']*unit;normal=(c['spring']*unit).copy();angular=normal.copy()
        if c['kind']=='single_lbeam':
            normal+=10000*np.outer(D[:,2],D[:,2]);angular=Ksingle
        elif c['kind']=='three_lbeams':normal=10010*unit;angular=Ktriple
        elif c['kind']=='replacement_lbeam':
            child=np.outer(D[:,2],D[:,2]);parents=unit-child
            damping=c['damping']*parents
            normal=c['spring']*parents+10000*child
            angular,_=tangent.tangent(xyz,False,False)
        errors={}
        for label,K in [('ordinary_axial',normal),('angular_model',angular)]:
            predicted=-q@K.T-v@damping.T;actual=force-external
            errors[label]=float(np.linalg.norm(actual[selected]-predicted[selected])/np.linalg.norm(actual[selected]))
        acceleration=job['mass_kg']*(v[index]-v[index-1])/dt
        force_lags={str(lag):float(np.linalg.norm(acceleration-force[index+lag])/np.linalg.norm(acceleration)) for lag in (-1,0,1)}
        results.append(dict(coupon=c,force_model_relative_rms=errors,acceleration_force_lags=force_lags,
            peak_displacement_m=float(np.max(np.linalg.norm(q.reshape(-1,3,3),axis=2))),
            breathing_coordinate_rms_m=float(np.sqrt(np.mean(np.square(q[selected]@(xyz-xyz.mean(0)).ravel()/np.linalg.norm(xyz-xyz.mean(0)))))),
            native_force_update_fraction=float(np.mean(np.any(np.diff(force,axis=0)!=0,axis=1)))))
    lag=min(results[0]['acceleration_force_lags'],key=results[0]['acceleration_force_lags'].get)
    for r in results:r['control_selected_force_balance_error']=r['acceleration_force_lags'][lag]
    return dict(scope=__doc__,samples=len(t),dt=dt,force_balance_lag_from_normal_control=int(lag),coupons=results,
        caveats='Linear force comparisons use authored directions; finite-deformation terms are omitted. Acceleration is an independent check of the native force getter. No prescribed-position calls are used.',
        evidence_sha256={n:hashlib.sha256((run/n).read_bytes()).hexdigest() for n in ('job.json','completion.json','compiled_coupon.json','coupon.csv','recorder.lua')})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args();r=analyze(a.run)
    (a.run/'force_analysis.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
