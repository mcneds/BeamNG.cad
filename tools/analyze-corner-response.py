"""Control-subtracted suspended yaw response, not a vehicle qualification.

The finite multisine response includes startup transients. It is not asserted to
be a steady-state FRF. The free-decay spectrum and half-amplitude comparison
identify a repeatable native response without fitting vehicle properties.
"""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
from scipy.signal import welch,find_peaks
from scipy.signal import detrend

def load(run):
    read=lambda name:json.loads((run/name).read_bytes())
    job,probe,completion,meta,excitation,compiled=[read(n+'.json') for n in ('job','probe','completion','frequency','excitation','compiled')]
    if (probe.get('error') or probe.get('resource_abort') or not probe['sources_unchanged'] or
        completion['status']!='completed' or probe['completion']['status']!='completed' or
        any(row.get('job_id')!=job['id'] for row in (completion,meta,excitation)) or
        not meta['complete'] or not excitation['complete']):raise ValueError('Incomplete or changed-source response')
    if job['scenario']!='corner_response' or job['gravity']!=0 or compiled['fixed_nodes']!=len(job['manifest']['chassis_nodes']):raise ValueError('Fixture mismatch')
    m=read('build_manifest.json')
    if hashlib.sha256((run/'build_manifest.json').read_bytes()).hexdigest()!=probe['manifest_sha256']:
        # write_json normalizes whitespace, so compare the source-bound content.
        source=next((Path(f) for f,h in probe['implementation'].items() if Path(f).name=='manifest.json' and h==probe['manifest_sha256']),None)
        if source is None or hashlib.sha256(source.read_bytes()).hexdigest()!=probe['manifest_sha256'] or json.loads(source.read_bytes())!=m:raise ValueError('Manifest identity differs')
    data=np.loadtxt(run/'frequency.csv',delimiter=',',skiprows=1);force=np.loadtxt(run/'excitation.csv',delimiter=',',skiprows=1)
    if data.shape!=(meta['samples'],2+3*len(meta['nodes'])) or force.shape!=(excitation['samples'],5) or not np.isfinite(data).all() or not np.isfinite(force).all():raise ValueError('Truncated or nonfinite response')
    dt=float(np.median(np.diff(data[:,0])))
    if abs(dt-.0005)>1e-8 or max(abs(np.diff(data[:,0])-dt))>1e-8:raise ValueError('Missing physics steps')
    indices=np.rint((data[:,0]-force[0,0])/dt).astype(int)
    if min(indices)<0 or max(indices)>=len(force) or not np.allclose(force[indices,0],data[:,0],rtol=0,atol=1e-9):raise ValueError('Asynchronous excitation')
    xyz=data[:,2:].reshape(len(data),-1,3);corner=job['excitation']['corner'];names=meta['nodes'];axes=m['wheels'][corner]['nodes']
    delta=xyz[:,names.index(axes['axis_out'])]-xyz[:,names.index(axes['axis_in'])]
    torque=np.cross(delta,force[indices,2:])[:,2]
    if not np.allclose(torque,force[indices,1],rtol=1e-7,atol=1e-9):raise ValueError('Applied couple differs from recorded moment')
    yaw=np.unwrap(np.arctan2(delta[:,1],delta[:,0]))
    return dict(run=run,job=job,probe=probe,time=data[:,0],yaw=yaw,force=force[indices,1],xyz=xyz,names=names)

def residual(yaw,control):
    return np.arctan2(np.sin(yaw-control),np.cos(yaw-control))

def linearity(full,half):
    full=np.asarray(full,float);half=np.asarray(half,float)
    if full.shape!=half.shape or not np.isfinite(full).all() or not np.isfinite(half).all() or np.linalg.norm(full)<1e-10:raise ValueError('Invalid linearity data')
    return dict(relative_rms_difference=float(np.linalg.norm(full-2*half)/np.linalg.norm(full)),
                half_to_full_rms_ratio=float(np.linalg.norm(half)/np.linalg.norm(full)))

def shape_agreement(rows,modes_path,frequency_hz):
    """Unweighted MAC on captured coordinates; shape agreement is not causality."""
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dependencies/cad-calibration/Test Harness'))
    from frame_harness.vehicle_motion import rigid_fit
    modes=json.loads(modes_path.read_bytes());base,full=rows[:2];m=base['job']['manifest'];corner=base['job']['excitation']['corner']
    if base['probe']['manifest_sha256'] not in modes['source_sha256'].values():raise ValueError('Mode-shape build differs')
    datum=[n for n in base['names'] if n in m['chassis_nodes']]
    rot,_=rigid_fit([m['nodes'][n]['position'] for n in datum],[base['xyz'][0,base['names'].index(n)] for n in datum])
    selected=[n for n in modes['corners'][corner]['nodes'] if n in base['names']];idx=[base['names'].index(n) for n in selected]
    t=base['time'];end=base['job']['excitation']['start_s']+base['job']['excitation']['duration_s']
    mask=t>=end;time=t[mask];delta=((full['xyz'][mask][:,idx]-base['xyz'][mask][:,idx])@rot.T).reshape(len(time),-1)
    # A full-window complex Fourier projection retains relative node phases.
    shape=(np.hanning(len(time))*np.exp(-2j*np.pi*frequency_hz*time))@detrend(delta,axis=0,type='linear')
    if np.linalg.norm(shape)<1e-12:raise ValueError('No measured mode shape')
    results=[]
    for mode in modes['corners'][corner]['modes']['rigid_wheel']:
        vector=np.array([mode['nodes'][n] for n in selected]).ravel()
        mac=float(abs(np.vdot(vector,shape))**2/(np.vdot(vector,vector).real*np.vdot(shape,shape).real))
        results.append(dict(model_hz=mode['hz'],unweighted_MAC=mac))
    return dict(recorded_frequency_hz=frequency_hz,nodes=selected,scope='Complex shape agreement on captured suspension coordinates; excludes uncaptured shaft center and generated wheel nodes',
        matches=sorted(results,key=lambda v:v['unweighted_MAC'],reverse=True),mode_file=str(modes_path),mode_file_sha256=hashlib.sha256(modes_path.read_bytes()).hexdigest())

def analyze(control,full,half):
    rows=[load(p) for p in (control,full,half)];base=rows[0]
    for row in rows[1:]:
        if row['probe']['manifest_sha256']!=base['probe']['manifest_sha256'] or row['names']!=base['names'] or not np.array_equal(row['time'],base['time']):raise ValueError('Control/build/capture mismatch')
        if (row['job']['excitation']|{'amplitude_nm':0})!=(base['job']['excitation']|{'amplitude_nm':0}):raise ValueError('Excitation controls differ')
        if (row['run']/'diagnostic-recorder.lua').read_bytes()!=(base['run']/'diagnostic-recorder.lua').read_bytes():raise ValueError('Recorder implementations differ')
    if base['job']['excitation']['amplitude_nm']!=0 or rows[1]['job']['excitation']['amplitude_nm']<=0 or rows[2]['job']['excitation']['amplitude_nm']*2!=rows[1]['job']['excitation']['amplitude_nm']:raise ValueError('Require zero, full and half amplitudes')
    t=base['time'];end=base['job']['excitation']['start_s']+base['job']['excitation']['duration_s'];ring=t>=end
    y=[residual(r['yaw'],base['yaw']) for r in rows[1:]];dt=float(np.median(np.diff(t)))
    reports=[]
    for row,delta in zip(rows[1:],y):
        f,power=welch(np.rad2deg(delta[ring]),fs=1/dt,nperseg=int(ring.sum()),detrend='linear')
        peaks=find_peaks(power)[0];peaks=sorted((i for i in peaks if 5<=f[i]<=100),key=lambda i:power[i],reverse=True)[:5]
        reports.append(dict(run=str(row['run']),amplitude_nm=row['job']['excitation']['amplitude_nm'],
            peak_toe_perturbation_deg=float(np.rad2deg(max(abs(delta)))),ringdown_toe_rms_deg=float(np.rad2deg(np.sqrt(np.mean(delta[ring]**2)))),
            peak_applied_yaw_moment_nm=float(max(abs(row['force']))),
            free_decay_peaks=[dict(hz=float(f[i]),density_deg2_per_hz=float(power[i])) for i in peaks],
            ringdown_frequency_resolution_hz=float(f[1]-f[0])))
    checks=linearity(y[0],y[1]);checks['ringdown']=linearity(y[0][ring],y[1][ring])
    sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for row in rows for p in [row['run']/n for n in ('frequency.csv','frequency.json','excitation.csv','excitation.json','compiled.json','completion.json','probe.json','job.json','diagnostic-recorder.lua')]}
    return dict(scope=__doc__,qualified=False,control=str(control),responses=reports,linearity=checks,
        fixed_chassis=True,gravity=0,steering=base['job']['excitation']['steering'],source_sha256=sources),rows,y

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('control',type=Path);p.add_argument('full',type=Path);p.add_argument('half',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--modes',type=Path);a=p.parse_args()
    result,rows,y=analyze(a.control,a.full,a.half)
    if a.modes:result['mode_shape_agreement']=shape_agreement(rows,a.modes,result['responses'][0]['free_decay_peaks'][0]['hz'])
    result['analysis_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(10,7),constrained_layout=True)
    t=rows[0]['time'];end=rows[0]['job']['excitation']['start_s']+rows[0]['job']['excitation']['duration_s']
    axes[0].plot(t,np.rad2deg(y[0]),label=f"{result['responses'][0]['amplitude_nm']:g} Nm per tone");axes[0].plot(t,np.rad2deg(2*y[1]),alpha=.7,label=f"{result['responses'][1]['amplitude_nm']:g} Nm per tone, doubled")
    axes[0].axvline(end,color='gray',ls='--');axes[0].set(ylabel='Control-subtracted toe (deg)',xlabel='Physics time (s)',title=f"Fixed chassis, tires clear, steering {result['steering']:g}; forcing ends at {end:g} s");axes[0].legend()
    for delta,label in zip(y,['Full input','Half input']):
        f,power=welch(np.rad2deg(delta[t>=end]),fs=1/np.median(np.diff(t)),nperseg=int(sum(t>=end)),detrend='linear');axes[1].semilogy(f,power,label=label)
    axes[1].set(xlim=(5,45),xlabel='Free-decay frequency (Hz)',ylabel='Toe PSD (deg²/Hz)');axes[1].legend();fig.savefig(a.output.with_suffix('.png'),dpi=140)
    print(json.dumps({k:v for k,v in result.items() if k!='source_sha256'},indent=2))

if __name__=='__main__':main()
