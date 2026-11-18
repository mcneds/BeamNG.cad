"""Bounded rolling-bounce comparison; spectra describe motion, not causal FRFs.

Use physics-rate positions registered to the whole chassis. Wheel-order peaks
are evidence of association, not proof that a tire, drivetrain or damper caused
the motion. Raw getBeamStress is not assumed to include viscous damper force.
"""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
from scipy.signal import welch,find_peaks
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.frequency_registration import fits

def summary(t,x):
    t=np.asarray(t);x=np.asarray(x)
    if len(t)<100 or x.shape!=t.shape or not np.isfinite(x).all() or not np.isfinite(t).all():
        raise ValueError('Invalid or short signal')
    dt=np.diff(t);step=float(np.median(dt))
    if step<=0 or max(abs(dt-step))>step*.001:raise ValueError('Irregular physics timestamps')
    frequency,power=welch(x,fs=1/step,nperseg=min(4000,len(t)),detrend='linear')
    peaks=find_peaks(power)[0];peaks=sorted(peaks,key=lambda i:power[i],reverse=True)[:5]
    return dict(mean=float(x.mean()),rms_ac=float(x.std()),peak_to_peak=float(np.ptp(x)),
        peaks_hz=[float(frequency[i]) for i in peaks],
        bands_rms={f'{lo}-{hi}Hz':float(np.sqrt(np.sum(power[(frequency>=lo)&(frequency<hi)])*(frequency[1]-frequency[0])))
                   for lo,hi in ((0,5),(5,15),(15,50),(50,1000))})

def analyze(run):
    files=['probe.json','job.json','completion.json','build_manifest.json','frequency.json','frequency.csv','frequency_chassis.csv','vehicle.csv','frequency_wheels.json','frequency_wheels.csv']
    read=lambda name:json.loads((run/name).read_bytes())
    probe,job,completion,m,meta=[read(n) for n in files[:5]]
    if not probe.get('sources_unchanged') or probe.get('error') or probe.get('resource_abort') or completion.get('status')!='completed' or not meta.get('complete'):
        raise ValueError('Incomplete or changed recording')
    if len({job['id'],completion['job_id'],meta['job_id'],probe['completion']['job_id']})!=1:raise ValueError('Mixed job identities')
    if m!=job['manifest']:raise ValueError('Manifest differs from recorded job')
    a=np.loadtxt(run/'frequency.csv',delimiter=',',skiprows=1);s=np.loadtxt(run/'frequency_chassis.csv',delimiter=',',skiprows=1)
    t=a[:,0]
    if len(t)!=meta['samples'] or a.shape[1]!=2+3*len(meta['nodes']) or not np.isfinite(a).all() or not np.array_equal(s[:,0],t):
        raise ValueError('Truncated or misaligned positions/registration')
    if not meta['config'].get('full_chassis_registration') or len(t)<100 or meta['dt_min']<=0 or meta['dt_max']>.001:
        raise ValueError('Physics-rate full chassis capture required')
    names=job['motion_reference']['chassis']
    rotation,translation=fits([m['nodes'][n]['position'] for n in names],[m['nodes'][n]['mass_kg'] for n in names],s[:,1:])
    local=np.einsum('tni,tji->tnj',a[:,2:].reshape(len(a),-1,3)-translation[:,None,:],rotation)
    r=np.genfromtxt(run/'vehicle.csv',delimiter=',',names=True)
    if len(r)!=completion['samples'] or np.any(np.diff(r['t'])<=0) or max(np.diff(r['t']))>.051 or not np.isfinite(np.array(r.tolist())).all() or max(r['broken'])>0:
        raise ValueError('Incomplete, nonfinite or damaged vehicle recording')
    mask=(r['t']>=t[0]-.001)&(r['t']<=t[-1]+.001)
    if mask.sum()<10:raise ValueError('Missing control telemetry in window')
    if np.median(r['speed'][mask])>1 and np.mean(np.any(np.diff(a[:,2:],axis=0)!=0,axis=1))<.8:
        raise ValueError('Moving positions are held snapshots rather than physics-rate updates')
    config=job.get('steady_speed',{})
    window_kind=('stationary_neutral' if probe.get('neutral_settle') else 'uncontrolled_creep') if job['scenario']=='settle' else 'speed_hold'
    if config:
        release=config.get('coast_after_s',float('inf'))
        if t[0]<release<=t[-1]:raise ValueError('Capture straddles coast transition')
        if t[0]>=release:
            window_kind='throttle_release_coast'
            if max(abs(r['throttle'][mask]))>1e-6 or max(abs(r['brake'][mask]))>1e-6:raise ValueError('Coast contains pedal input')
        elif max(abs(r['speed'][mask]-config['target_m_s']))>.25:
            raise ValueError('Vehicle did not hold the requested speed')
    wm=read('frequency_wheels.json');w=np.genfromtxt(run/'frequency_wheels.csv',delimiter=',',names=True)
    if not wm['complete'] or wm['job_id']!=job['id'] or wm['samples']!=len(t) or not np.array_equal(w['physics_s'],t) or not np.isfinite(np.array(w.tolist())).all():
        raise ValueError('Invalid wheel capture')
    corners={};history={}
    for corner,mapping in job['motion_reference']['corners'].items():
        if not all(n in meta['nodes'] for n in mapping['axis']):continue
        indices=[meta['nodes'].index(n) for n in mapping['axis']]
        hub=local[:,indices].mean(axis=1);travel=hub[:,2]*1000
        angular=w[corner+'_angularVelocity'];rate=float(np.mean(abs(angular))/(2*np.pi))
        rays=m['wheels'][corner]['tire_contract']['tread_nodes']/2
        corners[corner]=dict(hub_height_mm=summary(t,travel),wheel_rotation_hz=rate,ray_pass_hz=rate*rays,
            torque_nm=summary(t,w[corner+'_propulsionTorque']))
        history[corner]=(travel-travel.mean()).tolist()
    report=dict(scope=__doc__,status='diagnostic_only',run=str(run),samples=len(t),physics_rate_hz=1/float(np.median(np.diff(t))),
        manifest_sha256=probe['manifest_sha256'],physics_sha256=m.get('physics_sha256'),scenario=job['scenario'],
        control=job.get('steady_speed',probe.get('control_override',{})),window_kind=window_kind,
        speed_mph=np.percentile(r['speed'][mask],[5,50,95]).tolist(),corners=corners,
        throttle_range=[float(r['throttle'][mask].min()),float(r['throttle'][mask].max())],
        brake_range=[float(r['brake'][mask].min()),float(r['brake'][mask].max())],
        evidence_sha256={n:hashlib.sha256((run/n).read_bytes()).hexdigest() for n in files})
    report['speed_mph']=[v/0.44704 for v in report['speed_mph']]
    return report,t,history

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('runs',type=Path,nargs='+');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    rows=[analyze(r) for r in a.runs]
    a.output.write_text(json.dumps([r for r,_,_ in rows],indent=2)+'\n',encoding='utf-8')
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(10,6),layout='constrained')
    for report,t,history in rows:
        for c,axis in zip(('FL','FR'),axes):axis.plot(t-t[0],history[c],label=Path(report['run']).name,linewidth=.7)
    for c,axis in zip(('FL','FR'),axes):axis.set(xlabel='Time in capture (s)',ylabel=c+' hub motion (mm)');axis.legend();axis.grid(alpha=.2)
    fig.savefig(a.output.with_suffix('.png'),dpi=140);plt.close(fig)
    print(json.dumps([dict(run=Path(r['run']).name,speed_mph=r['speed_mph'],corners=r['corners']) for r,_,_ in rows],indent=2))

if __name__=='__main__':main()
