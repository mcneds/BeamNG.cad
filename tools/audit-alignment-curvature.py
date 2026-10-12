"""Equal-weight rolling-geometry diagnostic, NOT a tire dynamics prediction.

Solve the four lateral wheel constraints for body lateral velocity and yaw rate
per unit forward speed. Toe incompatibility leaves a slip residual. Integrate
using measured speed, retaining CAD toe/bump steer. Ignores camber thrust, tire
load/stiffness, compliance dynamics and inertia; cannot qualify or tune handling.
"""
import argparse,csv,json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def rolling(toes,centers):
    angles=np.radians(toes);nx=np.cos(angles);ny=np.sin(angles)
    matrix=np.column_stack((nx,-nx*centers[:,1]+ny*centers[:,0]))
    if np.linalg.matrix_rank(matrix)!=2:raise ValueError('Degenerate wheel layout')
    solution=np.linalg.lstsq(matrix,ny,rcond=None)[0]
    return solution,float(np.sqrt(np.mean((matrix@solution-ny)**2)))


def audit(run,output):
    manifest=json.loads((run/'build_manifest.json').read_bytes())
    motion=json.loads((run/'motion_comparison.json').read_bytes())
    raw=list(csv.DictReader((run/'vehicle.csv').open()))
    times=np.array([float(r['t']) for r in raw]);speed=np.array([float(r['forward_speed']) for r in raw])
    corners=['FL','FR','RL','RR'];centers=np.array([manifest['template_definition']['hardpoints'][c]['hub'][:2] for c in corners]);centers-=centers.mean(0)
    samples=[s for s in motion['samples'] if s['t']>=4]
    if len(samples)<2:raise ValueError('Missing active motion')
    integrated={'ideal':0.,'measured':0.};rows=[];previous=None
    for s in samples:
        if abs(s['steering_applied'])>1e-8:raise ValueError('Requires uncommanded steering')
        v=float(np.interp(s['t'],times,speed));row=dict(t=s['t'],observed_yaw_deg=s['yaw_deg']-samples[0]['yaw_deg'],forward_speed_m_s=v)
        for label,key in [('ideal','ideal_toe_deg'),('measured','actual_toe_deg')]:
            toes=[s['corners'][c][key] for c in corners]
            (side,curvature),residual=rolling(toes,centers)
            rate=-np.degrees(curvature*v) # recorder row-vector heading convention
            if previous is not None:integrated[label]+=(rate+previous[label+'_yaw_rate_deg_s'])*.5*(s['t']-previous['t'])
            row.update({label+'_yaw_rate_deg_s':rate,label+'_integrated_yaw_deg':integrated[label],label+'_slip_residual':residual,label+'_toes_deg':toes})
        rows.append(row);previous=row
    fig,ax=plt.subplots(figsize=(10,5),layout='constrained')
    ax.plot([r['t'] for r in rows],[r['observed_yaw_deg'] for r in rows],label='Recorded heading change')
    for label,title in [('ideal','Rigid CAD linkage toe'),('measured','Measured wheel toe')]:
        ax.plot([r['t'] for r in rows],[r[label+'_integrated_yaw_deg'] for r in rows],label='Rolling estimate: '+title)
    ax.set(xlabel='Time (s)',ylabel='Heading change (degrees)',title='Alignment sensitivity only; equal tire weights, no camber thrust or tire dynamics')
    ax.grid(alpha=.2);ax.legend();fig.savefig(output,dpi=150);plt.close(fig)
    result=dict(scope=__doc__,qualification_changed=False,run=str(run),final=rows[-1],samples=rows)
    output.with_suffix('.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(rows[-1]))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();audit(a.run,a.output)
