"""Identify native damping recurrence from synchronized force/velocity samples."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
from scipy.signal import lfilter


def analyze(run):
    job=json.loads((run/'job.json').read_bytes());done=json.loads((run/'completion.json').read_bytes());compiled=json.loads((run/'compiled_coupon.json').read_bytes())
    if done.get('status')!='completed' or done['job_id']!=job['id'] or compiled['job_id']!=job['id']:raise ValueError('Incomplete or mismatched coupon')
    data=np.loadtxt(run/'damping.csv',delimiter=',',skiprows=1)
    if data.shape!=(done['samples'],2+5*len(job['coupons'])) or not np.isfinite(data).all():raise ValueError('Incomplete/nonfinite coupon data')
    t=data[:,0];dt=float(np.median(np.diff(t)))
    if not .00049<dt<.00051 or max(abs(np.diff(t)-dt))>1e-6:raise ValueError('Physics-step samples required')
    if t[-1]<job['duration']-.001 or t[-1]<3:raise ValueError('Recording duration incomplete')
    out=[]
    for i,c in enumerate(job['coupons']):
        length,rate,elastic,damping,force=data[:,2+i*5:7+i*5].T
        start=int(np.searchsorted(t,1.));end=len(t)-1;models=[]
        for lag in range(4):
            y=damping[start:end];v=rate[start-lag:end-lag]
            if c['cutoff_hz']==0:
                gain=float(v@y/(v@v));prediction=gain*v;model=dict(lag=lag,gain=gain,pole=0.)
            else:
                design=np.column_stack((damping[start-1:end-1],v));coeff=np.linalg.lstsq(design,y,rcond=None)[0]
                prediction=design@coeff;model=dict(lag=lag,pole=float(coeff[0]),input_coefficient=float(coeff[1]),gain=float(coeff[1]/(1-coeff[0])))
            model['relative_rms_error']=float(np.linalg.norm(y-prediction)/np.linalg.norm(y));models.append(model)
        best=min(models,key=lambda v:v['relative_rms_error']);frequencies={}
        keep=t>=2.;time=t[keep];basis=np.column_stack([f(time) for hz in (5,14,40,100,250) for f in (lambda x,h=hz:np.sin(2*np.pi*h*x),lambda x,h=hz:np.cos(2*np.pi*h*x))])
        v=np.linalg.lstsq(basis,rate[keep],rcond=None)[0].reshape(-1,2);f=np.linalg.lstsq(basis,damping[keep],rcond=None)[0].reshape(-1,2)
        for hz,a,b in zip((5,14,40,100,250),v,f):
            transfer=complex(b[0],b[1])/complex(a[0],a[1]);frequencies[str(hz)]=dict(gain_ns_m=float(abs(transfer)),phase_deg=float(np.degrees(np.angle(transfer))))
        spring_error=float(np.linalg.norm(elastic-c['spring']*(length-.5))/max(np.linalg.norm(elastic),1e-12))
        pole=1/(1+2*np.pi*c['cutoff_hz']*dt) if c['cutoff_hz'] else 0.
        filtered=lfilter([1-pole],[1,-pole],rate)
        effective=min(c['damping'],min(c['mass'],c.get('anchor_mass',c['mass']))/dt)
        predicted=effective*np.sign(rate)*np.minimum(abs(rate),abs(filtered))
        actual_force=data[:,1]-elastic-force
        force_error=float(np.linalg.norm(actual_force[keep]-predicted[keep])/np.linalg.norm(actual_force[keep]))
        # getBeamStressDamp reports the pre-clamp filtered impulse magnitude on
        # normal filtered beams; bounded beams report the applied damping force.
        getter_prediction=(effective*np.sign(rate)*np.minimum(abs(rate),dt*abs(filtered))
            if c['kind']=='|NORMAL' and c['cutoff_hz'] else predicted)
        getter_error=float(np.linalg.norm(damping[keep]-getter_prediction[keep])/np.linalg.norm(damping[keep]))
        valid=force_error<.005 and getter_error<.005 and spring_error<.005
        out.append(dict(coupon=c,unclamped_linear_fit=best,all_lags=models,measured_multisine_ratio=frequencies,elastic_relative_error=spring_error,
            clamped_filter=dict(pole=pole,effective_damping_ns_m=effective,damping_cap='min(endpoint masses)/dt',recurrence='q[t] = pole*q[t-1] + (1-pole)*v[t]',force='c_eff*sign(v)*min(abs(v),abs(q))',
                force_balance_relative_rms_error=force_error,getter_relative_rms_error=getter_error,
                getter_units='c_eff*sign(v)*min(abs(v),dt*abs(q)); mixed diagnostic scaling' if c['kind']=='|NORMAL' and c['cutoff_hz'] else 'applied damping force'),
            recurrence_validated=bool(valid)))
    return dict(scope=__doc__,status='identified' if all(c['recurrence_validated'] for c in out) else 'model_not_validated',samples=len(t),dt=dt,coupons=out,
        caveats='Small one-dimensional coupons only. An assembled augmented-state stability model and native vehicle verification are still required.',
        evidence_sha256={f:hashlib.sha256((run/f).read_bytes()).hexdigest() for f in ('job.json','completion.json','compiled_coupon.json','damping.csv','recorder.lua')})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args();r=analyze(a.run)
    (a.run/'damping_analysis.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({'status':r['status'],'coupons':[{k:c[k] for k in ('coupon','clamped_filter','elastic_relative_error','recurrence_validated')} for c in r['coupons']]},indent=2))
