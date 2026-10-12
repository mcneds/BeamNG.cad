"""Speed-binned path curvature and CAD toe residuals for unassisted acceleration.

An accelerating run confounds speed, load transfer and elapsed time. These
observations are not a constant-speed causal test. Path curvature distinguishes
turning severity from cumulative lateral displacement. Motion snapshots do not
resolve high-frequency vibration. No authored geometry or acceptance is tuned.
"""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
from scipy.signal import savgol_filter
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle_motion import compare

def path_curvature(t,x,y,window_s=1.):
    t=np.asarray(t);x=np.asarray(x);y=np.asarray(y);dt=float(np.median(np.diff(t)))
    if dt<=0 or max(abs(np.diff(t)-dt))>1e-5 or not np.isfinite([t,x,y]).all():raise ValueError('Invalid/nonuniform path telemetry')
    window=max(5,int(round(window_s/dt))|1)
    if len(t)<window:raise ValueError('Path too short')
    dx,dy=[savgol_filter(v,window,3,deriv=1,delta=dt) for v in (x,y)]
    ddx,ddy=[savgol_filter(v,window,3,deriv=2,delta=dt) for v in (x,y)]
    speed=np.hypot(dx,dy)
    curvature=np.divide(dx*ddy-dy*ddx,speed**3,out=np.zeros_like(speed),where=speed>1)
    return curvature,speed

def analyze(run):
    read=lambda n:json.loads((run/(n+'.json')).read_bytes())
    job,probe,m,motion,completion=[read(n) for n in ('job','probe','build_manifest','motion_diagnostics','completion')]
    r=np.genfromtxt(run/'vehicle.csv',delimiter=',',names=True)
    if job['scenario']!='acceleration' or completion.get('status')!='completed' or probe.get('completion',{}).get('status')!='completed' or probe.get('error') or probe.get('resource_abort') or not probe.get('sources_unchanged'):
        raise ValueError('Incomplete or changed acceleration recording')
    if job['id']!=completion['job_id'] or job['id']!=motion['job_id'] or len(r)!=completion['samples'] or not np.isfinite(np.array(r.tolist())).all() or r['t'][-1]<24.99:
        raise ValueError('Incomplete/mismatched telemetry')
    if max(r['broken'])>0 or any(abs(s['steering_command'])>1e-6 or abs(s['steering_applied'])>1e-6 for s in motion['samples'] if s['t']>4):
        raise ValueError('Damaged or assisted acceleration is not a straightline comparison')
    k,planar_speed=path_curvature(r['t'],r['forward_distance'],r['lateral_distance'])
    # CSV left is positive: negate to make right curvature/drift positive.
    right=-k;native=compare(m,motion,'acceleration')['samples']
    bins=[]
    for low in range(0,18,2):
        mask=(r['t']>=4)&(r['t']<=24.5)&(r['speed']>=max(low,1))&(r['speed']<low+2)&(planar_speed>1)
        if mask.sum()<5:continue
        selected=[s for s in native if 4<=s['t']<=24.5 and max(low,1)<=np.interp(s['t'],r['t'],r['speed'])<low+2]
        corners={}
        for c in ('FL','FR','RL','RR'):
            values=[s['corners'][c] for s in selected]
            if not values or not all(v['reachable'] for v in values):raise ValueError('Missing/unreachable CAD motion in speed bin')
            corners[c]={}
            for key in ('actual_toe_deg','ideal_toe_deg','toe_error_deg','travel_m'):
                v=np.array([row[key] for row in values]);corners[c][key]=dict(mean=float(v.mean()),rms=float(np.sqrt(np.mean(v*v))),peak=float(max(abs(v))))
        bins.append(dict(speed_m_s=[low,low+2],samples=int(mask.sum()),right_curvature_1_m=float(np.median(right[mask])),
            right_curvature_range_1_m=np.percentile(right[mask],[10,90]).tolist(),corners=corners))
    if np.any(np.diff(r['forward_distance'][r['t']>1])<0):raise ValueError('Forward coordinate is not monotonic for distance comparison')
    offsets={str(x):float(-np.interp(x,r['forward_distance'],r['lateral_distance'])) for x in (5,10,20,40,100) if x<max(r['forward_distance'])}
    return dict(run=str(run),manifest_sha256=probe['manifest_sha256'],right_drift_at_forward_m=offsets,bins=bins,
        all_beams_intact=True,qualification_status='not_qualified',curvature_smoothing_window_s=1.,
        history=dict(speed_kmh=(r['speed']*3.6).tolist(),right_curvature_1_m=right.tolist(),forward_m=r['forward_distance'].tolist(),right_m=(-r['lateral_distance']).tolist(),time_s=r['t'].tolist()),
        evidence_sha256={n:hashlib.sha256((run/n).read_bytes()).hexdigest() for n in ('vehicle.csv','job.json','build_manifest.json','motion_diagnostics.json','completion.json','probe.json')})

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('runs',nargs='+',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--baseline-repeat',type=Path);a=p.parse_args()
    rows=[analyze(r) for r in a.runs];repeat=None
    if a.baseline_repeat:
        probe=json.loads((a.baseline_repeat/'probe.json').read_bytes());completion=json.loads((a.baseline_repeat/'completion.json').read_bytes())
        repeat=dict(run=str(a.baseline_repeat),telemetry_identical=(a.runs[0]/'vehicle.csv').read_bytes()==(a.baseline_repeat/'vehicle.csv').read_bytes(),
            manifest_identical=probe['manifest_sha256']==rows[0]['manifest_sha256'],complete=completion['status']=='completed' and probe.get('sources_unchanged') is True)
        if not all(repeat[k] for k in ('telemetry_identical','manifest_identical','complete')):raise ValueError('Baseline repeat differs; investigate before attributing changes')
    report=dict(scope=__doc__,runs=rows,baseline_repeat=repeat)
    a.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(10,8),layout='constrained')
    for row in rows:
        label=Path(row['run']).name.removeprefix('rear-pair-').removesuffix('-acceleration-20261012');h=row['history'];bins=row['bins']
        axes[0].plot(h['forward_m'],h['right_m'],label=label)
        axes[1].plot([np.mean(b['speed_m_s'])*3.6 for b in bins],[b['right_curvature_1_m'] for b in bins],'.-',label=label)
    axes[0].set(xlabel='Forward displacement (m)',ylabel='Right displacement (m)',xlim=(0,100),ylim=(0,15))
    axes[1].set(xlabel='Speed bin centre (km/h)',ylabel='Median right path curvature (1/m)')
    for ax in axes:ax.legend();ax.grid(alpha=.25)
    fig.suptitle('Rear spring A/B and speed dependence — unassisted acceleration pilots')
    fig.savefig(a.output.with_suffix('.png'),dpi=140);plt.close(fig)
    print(json.dumps([dict(run=r['run'],drift=r['right_drift_at_forward_m'],curvature=[(b['speed_m_s'],b['right_curvature_1_m']) for b in r['bins']]) for r in rows],indent=2))

if __name__=='__main__':main()
