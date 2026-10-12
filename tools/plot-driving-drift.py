"""Align recorded drift with heading, speed and suspension motion.

Local linear fits over one second estimate velocity and heading rate from
graphics-rate chassis positions. These diagnostics do not change qualification.
"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def slope(t, values, half_window=.5):
    result=np.empty(len(t))
    for i,at in enumerate(t):
        keep=np.abs(t-at)<=half_window
        tt=t[keep];vv=values[keep];tt=tt-tt.mean()
        result[i]=float(tt@vv/(tt@tt)) if len(tt)>=3 and tt@tt>0 else np.nan
    return result


def plot(run,output):
    files=('motion_comparison.json','vehicle.csv','build_manifest.json','result.json')
    motion=json.loads((run/files[0]).read_text(encoding='utf-8'))
    telemetry=np.genfromtxt(run/files[1],delimiter=',',names=True)
    manifest=json.loads((run/files[2]).read_text(encoding='utf-8'))
    result=json.loads((run/files[3]).read_text(encoding='utf-8'))
    rows=motion['samples'];t=np.array([s['t'] for s in rows]);active=t>=4
    lateral=np.array([s['lateral_m'] for s in rows]);forward=np.array([s['forward_m'] for s in rows])
    yaw=np.degrees(np.unwrap(np.radians([s['yaw_deg'] for s in rows])))
    vx=slope(t,lateral);vy=slope(t,forward);speed=np.hypot(vx,vy)
    moving=active&(speed>1.)
    path_heading=np.degrees(np.arctan2(-vx,vy));path_heading[~moving]=np.nan
    curvature=slope(t,yaw)/np.maximum(speed,1.);curvature[~moving]=np.nan
    front=np.array([np.mean([s['corners'][c]['actual_toe_deg'] for c in ('FL','FR')]) for s in rows])
    rear=np.array([np.mean([s['corners'][c]['actual_toe_deg'] for c in ('RL','RR')]) for s in rows])
    front_ideal=np.array([np.mean([s['corners'][c]['ideal_toe_deg'] for c in ('FL','FR')]) for s in rows])
    rear_ideal=np.array([np.mean([s['corners'][c]['ideal_toe_deg'] for c in ('RL','RR')]) for s in rows])
    hardpoints=manifest['template_definition']['hardpoints']
    wheelbase=abs(np.mean([hardpoints[c]['hub'][1] for c in ('FL','FR')])-np.mean([hardpoints[c]['hub'][1] for c in ('RL','RR')]))
    no_slip=np.degrees(np.tan(np.radians(rear-front))/wheelbase);no_slip[~moving]=np.nan
    ideal_no_slip=np.degrees(np.tan(np.radians(rear_ideal-front_ideal))/wheelbase);ideal_no_slip[~moving]=np.nan
    fig,axes=plt.subplots(4,2,figsize=(13,12),sharex=True,layout='constrained')
    axes[0,0].plot(t,lateral,label='Recorded chassis COM')
    for sign in (-1,1):axes[0,0].axhline(sign*.5,color='#b52b32',ls=':',label='Drift limit' if sign==1 else None)
    axes[0,0].set_ylabel('Lateral position (m)')
    axes[0,1].plot(telemetry['t'],telemetry['speed']*3.6,label='Recorded speed');axes[0,1].set_ylabel('Speed (km/h)')
    axes[1,0].plot(t,yaw,label='Chassis heading');axes[1,0].plot(t,path_heading,label='Motion direction (1 s fit)')
    axes[1,0].set_ylabel('Heading (degrees; right positive)')
    axes[1,1].plot(t,curvature,label='Chassis heading / distance')
    axes[1,1].plot(t,no_slip,label='Small-angle no-slip wheel estimate',alpha=.8)
    axes[1,1].plot(t,ideal_no_slip,'--',label='Ideal linkage at measured travel',alpha=.8)
    axes[1,1].set_ylabel('Curvature (degrees / m)')
    axes[2,0].plot(t,front,label='Front mean wheel angle');axes[2,0].plot(t,rear,label='Rear mean wheel angle')
    axes[2,0].plot(t,front_ideal,'--',color='#2468aa',alpha=.7,label='Front ideal linkage')
    axes[2,0].plot(t,rear_ideal,'--',color='#b45720',alpha=.7,label='Rear ideal linkage')
    axes[2,0].set_ylabel('Mean signed toe (degrees)')
    for c in ('FL','FR','RL','RR'):
        axes[2,1].plot(t,[s['corners'][c]['actual_camber_deg'] for s in rows],label=c)
        axes[3,1].plot(t,[s['corners'][c]['travel_m']*1000 for s in rows],label=c)
    axes[2,1].set_ylabel('Signed camber (degrees)');axes[3,1].set_ylabel('Suspension travel (mm)')
    if manifest.get('steering_contract'):
        axis=np.array(manifest['steering_contract']['axis'])
        for c in ('FL','FR'):
            rest=np.array(hardpoints[c]['tie_inner'])
            error=[((np.array(s['corners'][c]['actual']['tie_inner'])-rest)@axis-s['corners'][c]['actuator_extension_m'])*1000 for s in rows]
            axes[3,0].plot(t,error,label=c+' rack end minus target')
        axes[3,0].set_ylabel('Rack tracking error (mm)')
    else:
        for c in ('FL','FR'):
            axes[3,0].plot(t,[s['corners'][c]['tie_length_error_m']*1000 for s in rows],label=c+' tie length minus target')
        axes[3,0].set_ylabel('Steering-link extension error (mm)')
    for ax in axes.flat:
        ax.set_xlim(4,t[-1]);ax.grid(alpha=.2);ax.legend(fontsize=8,loc='best')
    for ax in axes[-1]:ax.set_xlabel('Recorded time (s)')
    fig.suptitle(run.parent.parent.name+' · '+result['scenario']+' · '+result['status']+'\n'
                 'Drift diagnostics: speed changes and changing alignment can both curve displacement over time')
    output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(output,dpi=150);plt.close(fig)
    indices=np.flatnonzero(active);peak=indices[np.argmax(abs(lateral[active]))]
    summary=dict(run=str(run.resolve()),status=result['status'],qualification_changed=False,
                 peak_lateral_m=float(lateral[peak]),peak_time_s=float(t[peak]),
                 final_lateral_m=float(lateral[-1]),final_yaw_deg=float(yaw[-1]),
                 method=__doc__,limitation='No-slip curve is a diagnostic approximation, not a tire-force model or acceptance criterion.',
                 files={name:hashlib.sha256((run/name).read_bytes()).hexdigest() for name in files})
    late=t>=17
    if np.any(late):
        summary['late_run_mean']=dict(front_toe_deg=float(front[late].mean()),rear_toe_deg=float(rear[late].mean()),
                                     front_ideal_toe_deg=float(front_ideal[late].mean()),rear_ideal_toe_deg=float(rear_ideal[late].mean()),
                                     scope='Samples from 17 seconds; descriptive correlation, not causal attribution.')
    output.with_suffix('.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();plot(args.run,args.output)
