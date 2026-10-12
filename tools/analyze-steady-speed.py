"""Separate CAD bump/roll steer from motion residuals during gated speed holds.

Speed hold is a diagnostic, not a handling or material qualification. Predicted
toe uses observed travel: agreement does not establish which force began a turn.
"""
import argparse,hashlib,importlib.util,json,sys
from pathlib import Path
import numpy as np
from scipy.signal import savgol_filter
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from steady_speed_control import step as controller_step
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle_motion import compare,Predictor,angles,rigid_fit
spec=importlib.util.spec_from_file_location('speed_analysis',ROOT/'tools/analyze-straightline-speed.py')
speed_analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(speed_analysis)

GATES=dict(speed_error_m_s=.25,acceleration_m_s2=.15,minimum_hold_s=5.,earliest_s=30.,edge_trim_s=.5)

def hold_mask(t,speed,target):
    t=np.asarray(t);speed=np.asarray(speed)
    if len(t)<25 or not np.isfinite([t,speed]).all() or np.any(np.diff(t)<=0):raise ValueError('Invalid speed history')
    dt=float(np.median(np.diff(t)))
    if max(abs(np.diff(t)-dt))>1e-5:raise ValueError('Nonuniform speed history')
    window=max(5,round(1./dt)|1)
    acceleration=savgol_filter(speed,window,3,deriv=1,delta=dt)
    eligible=(t>=GATES['earliest_s'])&(t<=t[-1]-GATES['edge_trim_s'])&(abs(speed-target)<=GATES['speed_error_m_s'])&(abs(acceleration)<=GATES['acceleration_m_s2'])
    valid=np.zeros(len(t),dtype=bool);segments=[]
    edges=np.diff(np.r_[False,eligible,False].astype(int))
    for a,b in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)):
        if t[b-1]-t[a]>=GATES['minimum_hold_s']:
            valid[a:b]=True;segments.append([float(t[a]),float(t[b-1])])
    return valid,acceleration,segments

def stats(values):
    v=np.asarray(values,float)
    if not len(v) or not np.isfinite(v).all():raise ValueError('Missing/nonfinite measurement')
    return dict(mean=float(v.mean()),rms=float(np.sqrt(np.mean(v*v))),peak=float(max(abs(v))),p10_p90=np.percentile(v,[10,90]).tolist())

def steering_map(manifest,motion):
    predictor=Predictor(manifest);extensions={};checks={};reference={}
    straight=[s for s in motion['samples'] if s['t']>=4]
    for c,mech in predictor.mechanisms.items():
        p=mech.p;wheel=manifest['wheels'][c]
        if (c[1]=='L') != (p['hub'][0]>0):raise ValueError('Left/right hub convention is inconsistent')
        if mech.translating_rack:
            targets=np.array([s['rack_target_m'] for s in straight])
            if max(abs(targets))>1e-6:raise ValueError('Straight rack target is not centred')
            extension=0.
        elif mech.wishbone or mech.radius_toe or mech.ball_radius_toe:
            length=np.linalg.norm(p['tie_outer']-p['tie_inner'])
            targets=np.array([s['actuator_rest_lengths'][c] for s in straight]) if mech.front or wheel.get('toe_link') else np.full(len(straight),length)
            if np.ptp(targets)>1e-6:raise ValueError('Straight tie targets changed')
            extension=float(np.median(targets)-length)
        else:extension=0.;targets=np.array([0.])
        extensions[c]=extension
        checks[c]=dict(hub_x_m=float(p['hub'][0]),native_target_m=float(np.median(targets)),extension_from_captured_geometry_m=extension)
        reference[c]=float(wheel['ride_reference']['hub_height_m']-p['hub'][2])
    curves=[]
    for mode in ('level_bump','opposite_wheel_travel'):
        for offset in np.linspace(-.04,.04,17):
            corners={}
            for c,mech in predictor.mechanisms.items():
                travel=reference[c]+offset*(1 if mode=='level_bump' or c[1]=='L' else -1)
                try:
                    pose=predictor.solve(c,float(travel),extensions[c]);axis=pose['hub_axis']-pose['hub']
                    axis*=1 if mech.p['hub_axis'][0]>mech.p['hub'][0] else -1
                    camber,toe=angles(axis);corners[c]=dict(reachable=True,toe_deg=float(toe),camber_deg=float(camber),travel_m=float(travel))
                except ValueError as exc:corners[c]=dict(reachable=False,reason=str(exc))
            curves.append(dict(mode=mode,offset_m=float(offset),corners=corners))
    return dict(convention='X left, -Y forward, Z up; positive axle toe is left steering. Roll sweep means left bump/right droop.',
        checks=checks,curves=curves,scope='Sealed CAD-derived hardpoints and native zero-input targets; not an independent new SolidWorks mate capture.')

def analyze(run):
    read=lambda n:json.loads((run/(n+'.json')).read_bytes())
    job,probe,m,motion,completion=[read(n) for n in ('job','probe','build_manifest','motion_diagnostics','completion')]
    r=np.genfromtxt(run/'vehicle.csv',delimiter=',',names=True)
    if m!=job['manifest'] or job.get('steady_speed')!=probe.get('steady_speed'):raise ValueError('Changed manifest/controller configuration')
    if job['scenario']!='steady_speed' or completion.get('status')!='completed' or probe.get('completion',{}).get('status')!='completed' or probe.get('error') or probe.get('resource_abort') or not probe.get('sources_unchanged'):
        raise ValueError('Incomplete or changed speed recording')
    if job['id']!=completion['job_id'] or job['id']!=motion['job_id'] or len(r)!=completion['samples'] or not np.isfinite(np.array(r.tolist())).all() or r['t'][-1]<job['duration']-.01:
        raise ValueError('Incomplete/mismatched telemetry')
    if len(motion['samples'])!=len(r) or not np.allclose([s['t'] for s in motion['samples']],r['t'],rtol=0,atol=1e-6):raise ValueError('Motion/vehicle clocks differ or motion samples missing')
    if max(r['broken'])>0 or min(r['up_z'])<.5:raise ValueError('Damaged/overturned recording')
    if any(abs(s['steering_command'])>1e-6 or abs(s['steering_applied'])>1e-6 for s in motion['samples'] if s['t']>=4):raise ValueError('Steering assistance invalidates speed isolation')
    if not probe.get('deterministic'):raise ValueError('Fixed control cadence required for controller replay')
    integral=0.;prior=0.;controller_error=[]
    for sample in r:
        throttle=brake=0.
        if sample['t']>4:throttle,brake,integral=controller_step(sample['speed'],sample['t'],sample['t']-prior,integral,job['steady_speed'])
        prior=sample['t'];controller_error.extend([abs(throttle-sample['throttle']),abs(brake-sample['brake'])])
    if max(controller_error)>1e-5:raise ValueError('Native pedals differ from controller oracle')
    target=job['steady_speed']['target_m_s'];mask,acceleration,segments=hold_mask(r['t'],r['speed'],target)
    curvature,_=speed_analysis.path_curvature(r['t'],r['forward_distance'],r['lateral_distance'])
    native=compare(m,motion,'steady_speed')
    selected=[s for s in native['samples'] if any(a<=s['t']<=b for a,b in segments)]
    row=dict(run=str(run),target_m_s=target,manifest_sha256=probe['manifest_sha256'],controller_sha256=probe['controller_sha256'],
        recording_status='completed',measurement_status='valid_hold' if selected else 'unsettled_speed',qualification_status='not_qualified',
        gate=GATES,hold_segments_s=segments,production_motion_checks=native['checks'],
        controller_replay_peak_error=max(controller_error),
        history=dict(time_s=r['t'].tolist(),speed_m_s=r['speed'].tolist(),acceleration_m_s2=acceleration.tolist(),right_curvature_1_m=(-curvature).tolist(),hold=mask.tolist()),
        evidence_sha256={n:hashlib.sha256((run/n).read_bytes()).hexdigest() for n in ('vehicle.csv','job.json','build_manifest.json','motion_diagnostics.json','completion.json','probe.json')})
    if not selected:return row,steering_map(m,motion)
    if any(not s['corners'][c]['reachable'] for s in selected for c in ('FL','FR','RL','RR')):raise ValueError('CAD pose unreachable during hold')
    corners={c:{key:stats([s['corners'][c][key] for s in selected]) for key in ('actual_toe_deg','ideal_toe_deg','toe_error_deg','actual_camber_deg','ideal_camber_deg','camber_error_deg','travel_m','tie_length_error_m','mount_error_m')} for c in ('FL','FR','RL','RR')}
    timestamps={s['t'] for s in selected};raw=[s for s in motion['samples'] if s['t'] in timestamps]
    chassis=m['chassis_nodes'];origin=np.array([m['nodes'][n]['position'] for n in chassis]);weights=np.array([m['nodes'][n]['mass_kg'] for n in chassis]);roll=[]
    for s in raw:
        rotation,_=rigid_fit(origin,np.array([s['reference_positions'][n] for n in chassis]),weights)
        roll.append(float(np.degrees(np.arctan2(rotation[0,2],rotation[2,2]))))
    row.update(corners=corners,speed_m_s=stats(r['speed'][mask]),acceleration_m_s2=stats(acceleration[mask]),
        right_curvature_1_m=stats(-curvature[mask]),roll_left_up_deg=stats(roll),
        throttle=stats(r['throttle'][mask]),brake=stats(r['brake'][mask]),
        body_shape_error_m={owner:stats([s['bodies'][owner]['shape_error_m'] for s in selected]) for owner in selected[0]['bodies']},
        body_roles={owner:m['component_roles'].get(owner) for owner in selected[0]['bodies']},
        wheel_torques={c:{key:stats([s['wheel_torques'][c][key] for s in raw]) for key in ('propulsion_torque','braking_torque','friction_torque')} for c in corners},
        coilovers={c:dict(compression_m=stats([m['wheels'][c]['ride_reference']['reference_shock_length_m']-s['coilovers'][c][0]['length_m'] for s in raw]),
            stop_elastic_n=stats([sum(b['elastic_force_n'] for b in s['coilovers'][c] if b['spring_n_m']==0) for s in raw])) for c in corners},
        steering_load_n={c:stats([sum(b['elastic_force_n']+b['damping_force_n'] for b in s['steering_loads']['tie_rods'][c]) for s in raw]) for c in ('FL','FR','RL','RR')},
        motion_history=[dict(t=s['t'],roll_left_up_deg=roll[i],corners={c:{k:s['corners'][c][k] for k in ('actual_toe_deg','ideal_toe_deg','toe_error_deg','travel_m')} for c in corners}) for i,s in enumerate(selected)])
    return row,steering_map(m,motion)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('runs',nargs='+',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    results=[analyze(run) for run in a.runs];rows=[r[0] for r in results]
    if len({r['manifest_sha256'] for r in rows})!=1 or len({r['controller_sha256'] for r in rows})!=1:raise ValueError('Mixed vehicle/controller identities')
    repeats=[]
    for target in sorted({r['target_m_s'] for r in rows}):
        pair=[r for r in rows if r['target_m_s']==target]
        repeats.append(dict(target_m_s=target,recordings=len(pair),vehicle_csv_identical=len(pair)==2 and pair[0]['evidence_sha256']['vehicle.csv']==pair[1]['evidence_sha256']['vehicle.csv'],valid_holds=all(r['measurement_status']=='valid_hold' for r in pair)))
    report=dict(scope=__doc__,runs=rows,repeats=repeats,steering_reference=results[0][1],qualification_status='not_qualified',
        sampling_limit='Motion comparison uses 20 Hz snapshots; high-frequency vibration peaks require separate physics-rate capture.')
    a.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,2,figsize=(12,8),layout='constrained')
    for index,row in enumerate(rows):
        h=row['history'];label=f"{row['target_m_s']*3.6:g} km/h, run {index+1}"
        axes[0,0].plot(h['time_s'],h['speed_m_s'],label=label)
        if row['measurement_status']!='valid_hold':continue
        hist=row['motion_history'];times=[s['t'] for s in hist]
        axes[0,1].plot(h['time_s'],h['right_curvature_1_m'],label=label)
        axes[1,0].plot(times,[sum(s['corners'][c]['ideal_toe_deg'] for c in ('FL','FR'))/2 for s in hist],label=label)
        axes[1,1].plot(times,[sum(s['corners'][c]['toe_error_deg'] for c in ('FL','FR'))/2 for s in hist],label=label)
    for ax,title,y in zip(axes.flat,['Speed control','Observed turning','Expected front steering at measured travel','Additional front steering error'],['Speed (m/s)','Right curvature (1/m)','Mean front toe (degrees, left +)','Mean front toe residual (degrees, left +)']):
        ax.set(title=title,xlabel='Simulation time (s)',ylabel=y);ax.grid(alpha=.25);ax.legend()
    fig.savefig(a.output.with_suffix('.png'),dpi=140);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    for ax,mode in zip(axes,('level_bump','opposite_wheel_travel')):
        curve=[s for s in results[0][1]['curves'] if s['mode']==mode]
        for c in ('FL','FR','RL','RR'):
            ax.plot([s['offset_m']*1000 for s in curve],[s['corners'][c].get('toe_deg',np.nan) for s in curve],label=c)
        ax.set(title=mode.replace('_',' '),xlabel='Travel offset (mm; left side for opposite travel)',ylabel='Predicted toe (degrees, left +)');ax.grid(alpha=.25);ax.legend()
    fig.savefig(a.output.with_name(a.output.stem+'-reference.png'),dpi=140);plt.close(fig)
    print(json.dumps([dict(target=r['target_m_s'],status=r['measurement_status'],segments=r['hold_segments_s'],curvature=r.get('right_curvature_1_m'),toe={c:v['toe_error_deg'] for c,v in r.get('corners',{}).items()}) for r in rows],indent=2))

if __name__=='__main__':main()
