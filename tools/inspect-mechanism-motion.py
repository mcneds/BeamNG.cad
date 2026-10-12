"""Locate loss of rigid-body shape and torsion leverage in native telemetry."""
import argparse,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from rigid_bracing import angle
p=argparse.ArgumentParser();p.add_argument('run',type=Path);a=p.parse_args()
d=json.loads((a.run/'compiled.json').read_text());motion=json.loads((a.run/'motion_diagnostics.json').read_text())
print('physics step range',motion.get('physics_dt_min'),motion.get('physics_dt_max'))
owners={n:v['component'] for n,v in d['explicit_nodes'].items()}
for sample in motion['samples']:
    q=sample.get('mechanism_positions',{});summary=[]
    for owner in sorted({owners[n] for n in q}):
        names=[n for n in q if owners[n]==owner]
        original=np.array([d['actual_nodes'][n]['position'] for n in names]);current=np.array([q[n] for n in names])
        x=original-original.mean(axis=0);y=current-current.mean(axis=0);u,s,vt=np.linalg.svd(x.T@y);r=u@np.diag([1,1,np.linalg.det(u@vt)])@vt
        residual=float(max(np.linalg.norm(x@r-y,axis=1)));worst=(0,None);lever=(1,None)
        for bar in d['torsionbars']:
            if not all(n in names for n in bar[:4]):continue
            initial=np.array([d['actual_nodes'][n]['position'] for n in bar[:4]]);now=np.array([q[n] for n in bar[:4]])
            delta=angle(now)-angle(initial);change=abs(np.arctan2(np.sin(delta),np.cos(delta)))
            if change>worst[0]:worst=(float(change),bar[:4])
            def arm(v):
                axis=v[2]-v[1];axis/=np.linalg.norm(axis)
                return np.linalg.norm(np.cross(v[3]-v[2],axis))
            ratio=arm(now)/arm(initial)
            if ratio<lever[0]:lever=(float(ratio),bar[:4])
        summary.append(dict(owner=owner,residual=residual,angle=worst,lever=lever))
    print(json.dumps(dict(t=sample['t'],fastest=sample.get('fastest_node'),worst=sorted(summary,key=lambda s:-s['residual'])[:2])))
