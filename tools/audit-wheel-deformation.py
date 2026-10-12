"""Compare native rim and tread ring axes with the moving axle over a recording."""
import argparse,json
from pathlib import Path
import numpy as np


def angle(a,b):
    a=np.asarray(a,float);b=np.asarray(b,float)
    if a.shape!=(3,) or b.shape!=(3,) or not np.isfinite([a,b]).all() or min(np.linalg.norm(a),np.linalg.norm(b))<1e-8:
        raise ValueError('Missing or invalid native wheel axis')
    return float(np.degrees(np.arccos(np.clip(abs(a@b)/(np.linalg.norm(a)*np.linalg.norm(b)),0,1))))


def audit(directory):
    manifest=json.loads((directory/'build_manifest.json').read_text(encoding='utf-8'))
    data=json.loads((directory/'motion_diagnostics.json').read_text(encoding='utf-8'))
    completion=json.loads((directory/'completion.json').read_text(encoding='utf-8'))
    if data['job_id']!=completion['job_id'] or completion['status']!='completed':raise ValueError('Recording did not complete or identity differs')
    if not data['samples'] or completion['simulated_seconds']-data['samples'][-1]['t']>.6:raise ValueError('Incomplete wheel telemetry')
    rows=[]
    for sample in data['samples']:
        row={'t':sample['t'],'corners':{}}
        for corner,wheel in manifest['wheels'].items():
            names=wheel['nodes'];positions=sample['mechanism_positions']
            axis=np.asarray(positions[names['axis_out']])-positions[names['axis_in']]
            tire=sample['wheel_torques'][corner]['tire_shape']
            hub=tire['hub_axis']['direction_world'];tread=tire['tread_axis']['direction_world']
            row['corners'][corner]=dict(rim_axle_tilt_deg=angle(axis,hub),tread_rim_tilt_deg=angle(hub,tread),
                tread_axle_tilt_deg=angle(axis,tread),tread_center_offset_m=float(tire['center_offset_m']))
        rows.append(row)
    active=[r for r in rows if r['t']>=4.]
    if not active:raise ValueError('No post-startup wheel telemetry')
    peaks={c:{k:max(abs(r['corners'][c][k]) for r in active) for k in active[0]['corners'][c]} for c in manifest['wheels']}
    return dict(job_id=data['job_id'],scope='Native ring deformation diagnostic; distinct from upright/axle alignment. Does not qualify tires or vehicle.',
                peaks=peaks,samples=rows)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('recording',type=Path);p.add_argument('--plot',type=Path);a=p.parse_args()
    result=audit(a.recording)
    (a.recording/'wheel-deformation-audit.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result['peaks'],indent=2))
    if a.plot:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig,axes=plt.subplots(2,1,figsize=(9,6),layout='constrained',sharex=True)
        for c in result['peaks']:
            for ax,key in zip(axes,('rim_axle_tilt_deg','tread_rim_tilt_deg')):
                ax.plot([s['t'] for s in result['samples']],[s['corners'][c][key] for s in result['samples']],label=c)
        axes[0].set(title='Metal rim axis relative to axle',ylabel='Angle (degrees)')
        axes[1].set(title='Tread axis relative to metal rim',ylabel='Angle (degrees)',xlabel='Recording time (s)')
        for ax in axes:ax.legend(ncols=4);ax.grid(alpha=.2)
        a.plot.parent.mkdir(parents=True,exist_ok=True);fig.savefig(a.plot)
