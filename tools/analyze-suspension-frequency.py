"""Bounded physics-step spectra of CAD motion residuals; diagnostic, not qualification.

No frequency response function is claimed: ordinary driving is not a measured
force-input experiment. Isolated member modes omit tires and external constraints.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
from scipy.interpolate import CubicSpline
from scipy.signal import welch, find_peaks, coherence

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'dependencies/cad-calibration/Test Harness'),str(ROOT/'beamng.cad/FramePipeline')]
from frame_harness.vehicle_motion import rigid_fit, Predictor, angles, angle_error
from rigid_bracing import gradient


def spectrum(time, values):
    time=np.asarray(time);values=np.asarray(values)
    if len(time)<100 or not np.isfinite(time).all() or not np.isfinite(values).all():
        raise ValueError('Missing/nonfinite frequency samples')
    dt=np.diff(time);step=float(np.median(dt))
    if step<=0 or np.max(abs(dt-step))>step*.001:raise ValueError('Nonuniform or missing physics steps')
    frequency,power=welch(values,fs=1/step,nperseg=min(4000,len(time)),detrend='linear')
    peaks,_=find_peaks(power);peaks=sorted(peaks,key=lambda i:power[i],reverse=True)[:5]
    width=float(frequency[1]-frequency[0])
    return dict(sample_rate_hz=1/step,resolution_hz=width,mean=float(values.mean()),
        rms=float(np.sqrt(np.mean(values**2))),ac_rms=float(values.std()),peak=float(max(abs(values))),
        peak_time_s=float(time[np.argmax(abs(values))]),
        peaks=[dict(hz=float(frequency[i]),density=float(power[i])) for i in peaks],
        bands_rms={f'{low}-{high}Hz':float(np.sqrt(power[(frequency>=low)&(frequency<high)].sum()*width))
                   for low,high in ((0,10),(10,50),(50,200),(200,500),(500,1000))},
        frequency_hz=frequency.tolist(),density=power.tolist())


def hinge_coordinates(points):
    a,b,p=np.moveaxis(np.asarray(points),-2,0)
    axis=b-a;length=np.linalg.norm(axis,axis=-1);axis=axis/length[...,None]
    axial=np.sum((p-a)*axis,axis=-1)
    radius=np.linalg.norm(p-a-axial[...,None]*axis,axis=-1)
    return np.stack([axial,radius,length],axis=-1)


def averaged_coherence(left,right,rate,peak):
    # A single Welch segment produces unity even for unrelated signals.
    size=min(4000,len(left)//2);overlap=size//2
    if size<50 or len(left)!=len(right):raise ValueError('Insufficient coherence samples')
    frequencies,value=coherence(left,right,fs=rate,nperseg=size,noverlap=overlap)
    index=int(np.argmin(abs(frequencies-peak)))
    return dict(toe_peak_hz=peak,coherence_at_peak=float(value[index]),
                evaluated_hz=float(frequencies[index]),segment_samples=size,
                overlapping_segments=1+(len(left)-size)//(size-overlap))


def validate_speed_window(job,meta,vehicle):
    sys.path.insert(0,str(ROOT/'tools'))
    from steady_speed_control import settings
    config=job.get('steady_speed',{})
    if config!=settings(config.get('target_m_s',float('nan')),config.get('coast_after_s')):
        raise ValueError('Changed steady-speed control settings')
    t=vehicle['t'];start=meta['config']['start_s'];end=start+meta['config']['duration_s']
    if end>=config.get('coast_after_s',float('inf')):raise ValueError('Coasting is not a controlled speed hold')
    if len(t)<2 or not all(np.isfinite(vehicle[k]).all() for k in ('t','speed','broken')) or np.any(np.diff(t)<=0):
        raise ValueError('Invalid speed telemetry')
    if t[0]>start or t[-1]<end-.051 or np.max(np.diff(t))>.051:
        raise ValueError('Incomplete speed telemetry')
    active=(t>=start)&(t<=end)
    if not active.any() or max(abs(vehicle['speed'][active]-job['steady_speed']['target_m_s']))>.25 or max(vehicle['broken'])>0:
        raise ValueError('Frequency window is not an intact speed hold')


def validate_fresh_positions(time,positions):
    changed=np.any(np.diff(positions,axis=0)!=0,axis=tuple(range(1,positions.ndim)))
    updates=np.flatnonzero(changed)
    # A moving vehicle cannot have every recorded node exactly unchanged for
    # long runs of physics callbacks. Do not FFT a held graphics-rate snapshot.
    if len(updates)<len(time)*.8:
        cadence=float(np.median(np.diff(time[updates]))) if len(updates)>1 else None
        raise ValueError(f'Node positions are stale/held: {len(updates)} updates for {len(time)} samples; median update interval {cadence} s')


def validate_targets(time,data,metadata,job_id):
    if (metadata.get('job_id')!=job_id or not metadata.get('complete') or
            metadata.get('samples')!=len(time) or data.shape!=(len(time),5)):
        raise ValueError('Incomplete or mismatched physics-rate actuator targets')
    if [r['corner'] for r in metadata.get('actuators',[])]!=['FL','FR']:
        raise ValueError('Actuator target order differs')
    if not np.isfinite(data).all() or not np.array_equal(data[:,0],time) or np.any(data[:,1:]<=0):
        raise ValueError('Nonfinite, asynchronous or nonpositive actuator targets')
    return {'FL':data[:,1],'FR':data[:,3]}


def solve_recorded_path(predictor,corner,travel,extensions,keys):
    mechanism=predictor.mechanisms[corner];poses=[];worst=0.
    for i,(h,e) in enumerate(zip(travel,extensions)):
        pose=predictor.solve(corner,float(h),float(e))
        residual=np.r_[mechanism.constraints(predictor.previous[corner],float(e)),
                       pose['hub'][2]-mechanism.p['hub'][2]-h]
        error=float(np.max(abs(residual)))
        if not np.isfinite(error) or error>1e-7:raise ValueError('Physics-rate CAD reference did not converge within 0.1 micrometre')
        worst=max(worst,error);poses.append([pose[k] for k in keys])
        if i%2000==0:print(f'CAD reference {corner}: {i}/{len(travel)} samples',flush=True)
    return np.asarray(poses),worst


def member_modes(manifest,compiled):
    result={};actual=compiled['actual_nodes']
    for owner,role in manifest['component_roles'].items():
        if not role or not role.endswith('_wishbone'):continue
        names=list(manifest['mass_allocations'][owner]);index={n:i for i,n in enumerate(names)}
        if any(set(row[:2]+[row[-1]['id3:']])<=set(names) for row in manifest.get('angular_arms',{}).get('beams',[])):
            # These force tangents are nonsymmetric; eigh would invent an
            # energy model. Full discrete screening is archived by generation.
            result[role]=[];continue
        cids={actual[n]['cid']:n for n in names};mass=np.repeat([actual[n]['mass_kg'] for n in names],3)
        xyz=np.array([manifest['nodes'][n]['position'] for n in names]);K=np.zeros((len(mass),len(mass)));C=K.copy()
        for beam in compiled['beams']:
            if beam['a'] not in cids or beam['b'] not in cids:continue
            a,b=index[cids[beam['a']]],index[cids[beam['b']]];v=xyz[b]-xyz[a];v/=np.linalg.norm(v)
            col=np.zeros((len(names),3));col[a]=-v;col[b]=v;g=col.ravel()/np.sqrt(mass)
            K+=beam['spring']*np.outer(g,g);C+=beam['damp']*np.outer(g,g)
        for row in compiled['torsionbars']:
            if not set(row[:4])<=set(names):continue
            ids=[index[n] for n in row[:4]];col=np.zeros((len(names),3));col[ids]=gradient(xyz[ids]);g=col.ravel()/np.sqrt(mass)
            K+=row[4]['spring']*np.outer(g,g);C+=row[4]['damp']*np.outer(g,g)
        eigen,vectors=np.linalg.eigh(K);positive=np.flatnonzero(eigen>1.)
        result[role]=[dict(hz=float(np.sqrt(eigen[i])/(2*np.pi)),
            modal_damping_ratio=float(vectors[:,i]@C@vectors[:,i]/(2*np.sqrt(eigen[i])))) for i in positive]
    return result


def analyze(run):
    filenames=['frequency.csv','frequency.json','job.json','probe.json','build_manifest.json','compiled.json','motion_diagnostics.json']
    meta,job,probe,m,compiled,motion=[json.loads((run/n).read_bytes()) for n in filenames[1:]]
    if not meta['complete'] or not probe['sources_unchanged'] or probe.get('error') or probe.get('resource_abort'):
        raise ValueError('Incomplete or changed-source recording')
    if meta['job_id']!=job['id'] or probe.get('completion',{}).get('status')!='completed':raise ValueError('Incomplete job or identity mismatch')
    if job['scenario'] not in ('settle','reverse','acceleration','left_turn','right_turn','suspension_rate','steady_speed'):raise ValueError('Unsupported frequency driving scenario')
    if job['scenario']=='steady_speed':
        vehicle=np.genfromtxt(run/'vehicle.csv',delimiter=',',names=True)
        validate_speed_window(job,meta,vehicle)
        filenames.append('vehicle.csv')
    if job['scenario']=='suspension_rate' and (job['gravity']!=0 or compiled['fixed_nodes']!=len(m['chassis_nodes'])):
        raise ValueError('Suspension-rate fixture differs from its pinned zero-gravity contract')
    names=meta['nodes'];data=np.loadtxt(run/'frequency.csv',delimiter=',',skiprows=1)
    if len(data)!=meta['samples'] or data.shape[1]!=2+3*len(names):raise ValueError('Truncated frequency positions')
    time=data[:,0];spectrum(time,data[:,2]) # rejects gaps, jitter and nonfinite values
    high_targets=None;target_audit=None
    if meta['config'].get('actuator_targets'):
        filenames.extend(['frequency_targets.csv','frequency_targets.json'])
        target_data=np.loadtxt(run/'frequency_targets.csv',delimiter=',',skiprows=1)
        with (run/'frequency_targets.csv').open() as f:
            if f.readline().strip()!='physics_s,FL_target_m,FL_native_rest_m,FR_target_m,FR_native_rest_m':
                raise ValueError('Actuator target CSV columns differ')
        target_meta=json.loads((run/'frequency_targets.json').read_bytes())
        high_targets=validate_targets(time,target_data,target_meta,job['id'])
        target_audit={c:dict(max_target_native_rest_difference_m=float(np.max(abs(target_data[:,i]-target_data[:,i+1]))))
                      for c,i in (('FL',1),('FR',3))}
    elif job['scenario'] in ('left_turn','right_turn'):
        raise ValueError('Steering onset requires synchronized physics-rate actuator targets')
    if not np.isfinite(data).all():raise ValueError('Nonfinite node positions')
    if abs(time[0]-meta['config']['start_s'])>.001 or abs(time[-1]-sum([meta['config']['start_s'],meta['config']['duration_s']]))>.001:
        raise ValueError('Frequency window is incomplete')
    index={n:i for i,n in enumerate(names)};world=data[:,2:].reshape(len(data),len(names),3)
    validate_fresh_positions(time,world)
    chassis=meta['config']['chassis_nodes'];ci=[index[n] for n in chassis]
    rest=np.array([m['nodes'][n]['position'] for n in names]);weights=np.array([m['nodes'][n]['mass_kg'] for n in chassis])
    local=np.empty_like(world)
    registration='bounded_chassis_subset'
    if meta['config'].get('full_chassis_registration'):
        from frame_harness.frequency_registration import fits
        filenames.append('frequency_chassis.csv')
        stats=np.loadtxt(run/'frequency_chassis.csv',delimiter=',',skiprows=1)
        if stats.shape!=(len(time),13) or not np.array_equal(stats[:,0],time):raise ValueError('Incomplete or asynchronous chassis statistics')
        full=job['motion_reference']['chassis']
        rotations,translations=fits([m['nodes'][n]['position'] for n in full],[m['nodes'][n]['mass_kg'] for n in full],stats[:,1:])
        local=np.einsum('tni,tji->tnj',world-translations[:,None,:],rotations)
        registration='full_mass_weighted_chassis'
    else:
        for i,points in enumerate(world):
            rotation,translation=rigid_fit(rest[ci],points[ci],weights);local[i]=(points-translation)@rotation.T
    channels={};interpolation={};extensions={};predictor=Predictor(m)
    active=[s for s in motion['samples'] if data[0,1]-.1<=s['t']<=data[-1,1]+.1]
    if len(active)<10:raise ValueError('Missing steering controls')
    if high_targets is None and any(abs(s['steering_command'])>.00001 for s in active):raise ValueError('Nonzero steering requires physics-rate targets')
    for corner in ('FL','FR'):
        mapping=job['motion_reference']['corners'][corner];points=mapping['points'];mechanism=predictor.mechanisms[corner];p=mechanism.p
        if mechanism.translating_rack:raise ValueError('Rack frequency prediction needs recorded high-rate actuator targets')
        targets=(high_targets[corner] if high_targets is not None else np.array([s['actuator_rest_lengths'][corner] for s in active]))
        extension=float(targets.mean()-np.linalg.norm(p['tie_outer']-p['tie_inner']))
        if high_targets is None and np.ptp(targets)>1e-7:raise ValueError('Moving steering actuator requires physics-rate targets')
        extensions[corner]=(targets-np.linalg.norm(p['tie_outer']-p['tie_inner']) if high_targets is not None else np.full(len(time),extension))
        channels[corner+'_tie_length_error_mm']=(np.linalg.norm(local[:,index[points['tie_outer']]]-local[:,index[points['tie_inner']]],axis=1)-(targets if high_targets is not None else targets.mean()))*1000
        ia,ib=[index[n] for n in mapping['axis']];a,b=local[:,ia],local[:,ib];axis=b-a
        original=rest[[ia,ib]];d=original[1]-original[0];fraction=(p['hub']-original.mean(0))@d/(d@d)
        hub=(a+b)/2+fraction*axis;travel=hub[:,2]-p['hub'][2]
        grid=np.linspace(travel.min()-1e-5,travel.max()+1e-5,101)
        keys=['hub','hub_axis','upper_ball','lower_ball','tie_outer']
        if high_targets is not None:
            # Solve the mechanism at every recorded target/travel pair. No
            # interpolation across a steering command or target discontinuity.
            expected,worst=solve_recorded_path(predictor,corner,travel,extensions[corner],keys)
            interpolation[corner]=dict(method='exact_per_physics_sample',samples=len(time),
                max_constraint_residual_m=worst,
                travel_range_m=[float(travel.min()),float(travel.max())],actuator_extension_m=None,
                actuator_extension_range_m=[float(extensions[corner].min()),float(extensions[corner].max())])
        else:
            poses=[predictor.solve(corner,float(h),extension) for h in grid]
            spline=CubicSpline(grid,np.array([[pose[k] for k in keys] for pose in poses]),axis=0)
            error=0.
            for h in (grid[:-1:4]+grid[1::4])/2:
                exact=predictor.solve(corner,float(h),extension)
                error=max(error,float(np.max(np.linalg.norm(spline(h)-[exact[k] for k in keys],axis=1))))
            if error>1e-6:raise ValueError('Ideal CAD interpolation exceeds one micrometre')
            interpolation[corner]=dict(max_checked_error_m=error,travel_range_m=[float(travel.min()),float(travel.max())],actuator_extension_m=extension)
            expected=spline(travel)
        expected_axis=expected[:,1]-expected[:,0]
        expected_axis*=1 if p['hub_axis'][0]>p['hub'][0] else -1
        def angle_rows(v):return np.degrees(np.column_stack([np.arctan2(v[:,2],np.linalg.norm(v[:,:2],axis=1)),np.arctan2(v[:,1],v[:,0])]))
        errors=angle_error(angle_rows(axis),angle_rows(expected_axis))
        for i,label in enumerate(('camber','toe')):channels[corner+'_'+label+'_error_deg']=errors[:,i]
        for j,key in enumerate(keys):
            if key=='hub_axis':continue
            observed=hub if key=='hub' else local[:,index[points[key]]]
            for ax,label in enumerate('xyz'):channels[corner+'_'+key+'_'+label+'_error_mm']=(observed[:,ax]-expected[:,j,ax])*1000
        for arm in ('upper','lower'):
            ids=[index[points[arm+'_'+suffix]] for suffix in ('inner_front','inner_rear','ball')]
            residual=(hinge_coordinates(local[:,ids])-hinge_coordinates(rest[ids]))*1000
            for j,label in enumerate(('axial','radial','span')):channels[corner+'_'+arm+'_'+label+'_error_mm']=residual[:,j]
    summaries={name:spectrum(time,values) for name,values in channels.items()}
    threshold_observations={}
    for corner in ('FL','FR'):
        values=channels[corner+'_toe_error_deg'];above=abs(values)>2.;indices=np.flatnonzero(above)
        runs=np.split(indices,np.flatnonzero(np.diff(indices)>1)+1) if len(indices) else []
        threshold_observations[corner]=dict(limit_deg=2.,samples_over_limit=int(above.sum()),
            sampled_time_over_limit_s=float(above.sum()*np.median(np.diff(time))),
            longest_sampled_interval_s=float(max((len(r) for r in runs),default=0)*np.median(np.diff(time))),
            intervals_s=[[float(time[r[0]]),float(time[r[-1]])] for r in runs],
            scope='Physics-sample threshold counts, not interpolated crossing times. Acceptance is unchanged.')
    peak_context={}
    for corner in ('FL','FR'):
        i=int(np.argmax(abs(channels[corner+'_toe_error_deg'])))
        peak_context[corner]=dict(time_s=float(time[i]),actuator_extension_m=float(extensions[corner][i]),channels={k:float(v[i]) for k,v in channels.items() if k.startswith(corner+'_')})
    time_windows=[]
    for start in np.arange(time[0],time[-1],.5):
        select=(time>=start)&(time<start+.5)
        time_windows.append(dict(start_s=float(start),end_s=float(time[select][-1]),
            channels={name:dict(mean=float(values[select].mean()),ac_rms=float(values[select].std()),peak=float(max(abs(values[select])))) for name,values in channels.items()}))
    relationships={};rate=1/float(np.median(np.diff(time)))
    for corner in ('FL','FR'):
        toe=corner+'_toe_error_deg';peak=summaries[toe]['peaks'][0]['hz']
        relationships[corner]={}
        for arm in ('upper','lower'):
            name=corner+'_'+arm+'_axial_error_mm'
            relationships[corner][arm]=averaged_coherence(channels[toe],channels[name],rate,peak)
    report=dict(scope=__doc__,run=str(run),samples=len(time),duration_s=float(time[-1]-time[0]),
        qualification_status='diagnostic_only',registration=registration,evidence_sha256={n:hashlib.sha256((run/n).read_bytes()).hexdigest() for n in filenames},
        ideal_interpolation=interpolation,actuator_target_audit=target_audit,threshold_observations=threshold_observations,
        analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),isolated_member_modes=member_modes(m,compiled),
        toe_arm_coherence=relationships,coherence_scope='Descriptive association over at least three overlapping segments; not proof of causality',
        time_windows=time_windows,peak_toe_context=peak_context,channels=summaries,
        display_history=dict(time_s=time[::4].tolist(),channels={k:v[::4].tolist() for k,v in channels.items()
            if k.endswith(('toe_error_deg','upper_axial_error_mm'))}),
        display_history_scope='Decimated position-error display only; spectra and peak statistics use every sample')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args()
    try:report=analyze(a.run)
    except ValueError as exc:
        (a.run/'frequency_analysis.json').write_text(json.dumps(dict(status='invalid_measurement',reason=str(exc)),indent=2),encoding='utf-8')
        (a.run/'frequency_analysis.png').unlink(missing_ok=True)
        raise
    (a.run/'frequency_analysis.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(11,8),layout='constrained')
    for corner in ('FL','FR'):
        for ax,name in zip(axes,(corner+'_toe_error_deg',corner+'_upper_axial_error_mm')):
            s=report['channels'][name];ax.semilogy(s['frequency_hz'][1:],s['density'][1:],label=name)
    for ax in axes:ax.set_xscale('log');ax.set_xlim(.5,1000);ax.set_xlabel('Frequency (Hz)');ax.legend();ax.grid(alpha=.25)
    axes[0].set_ylabel('Toe residual PSD (deg²/Hz)');axes[1].set_ylabel('Arm axial residual PSD (mm²/Hz)')
    fig.suptitle('CAD motion residual spectra — diagnostic, no measured force input')
    fig.savefig(a.run/'frequency_analysis.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(2,1,figsize=(11,7),layout='constrained');history=report['display_history']
    for corner in ('FL','FR'):
        for ax,name in zip(axes,(corner+'_toe_error_deg',corner+'_upper_axial_error_mm')):
            ax.plot(history['time_s'],history['channels'][name],label=corner)
    for ax in axes:ax.set_xlabel('Physics time (s)');ax.legend();ax.grid(alpha=.25)
    axes[0].set_ylabel('Toe residual (deg)');axes[1].set_ylabel('Arm axial residual (mm)')
    fig.suptitle('Deviation from unchanged CAD motion')
    fig.savefig(a.run/'frequency_history.png',dpi=150);plt.close(fig)
    print(json.dumps({k:{x:v[x] for x in ('mean','ac_rms','peak','peaks','bands_rms')} for k,v in report['channels'].items() if 'toe_error' in k},indent=2))
