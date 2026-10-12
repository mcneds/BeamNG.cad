"""Attribute steering compliance using controlled measured-geometry substitutions.

The unchanged CAD reference remains the acceptance reference. These experiments
substitute measured chassis pivots, rack endpoints or tie length independently;
they diagnose correlation and sensitivity, never qualify a recording.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle_motion import Predictor, angles


def diagnose(run, after=17.):
    files=('build_manifest.json','motion_comparison.json')
    manifest,comparison=[json.loads((run/name).read_text(encoding='utf-8')) for name in files]
    predictor=Predictor(manifest);samples=[]
    modes=dict(reference=(False,False,False),chassis_pivots=(True,False,False),
               rack_endpoint=(False,True,False),tie_length=(False,False,True),
               all_measured=(True,True,True))
    for sample in comparison['samples']:
        if sample['t']<after:continue
        row=dict(t=sample['t'],corners={})
        for corner in ('FL','FR'):
            mechanism=predictor.mechanisms[corner]
            if not mechanism.wishbone or not mechanism.translating_rack:
                raise ValueError('Diagnostic requires front wishbones with a translating rack')
            recorded=sample['corners'][corner];rest=mechanism.p
            actual={k:np.array(v) for k,v in recorded['actual'].items()}
            initial,original=mechanism.solve(recorded['travel_m'],recorded['actuator_extension_m'])
            predictions={}
            for name,(mounts,rack,tie) in modes.items():
                arm_frames={}
                for arm in ('lower','upper'):
                    a,b=[arm+'_inner_'+end for end in ('front','rear')]
                    old_axis=rest[b]-rest[a];old_axis/=np.linalg.norm(old_axis)
                    origin=(actual if mounts else rest)[a]
                    axis=(actual if mounts else rest)[b]-origin;axis/=np.linalg.norm(axis)
                    rotation=Rotation.align_vectors([axis],[old_axis])[0]
                    arm_frames[arm]=(origin,axis,rotation.apply(rest[arm+'_ball']-rest[a]))
                inner=actual['tie_inner'] if rack else original['tie_inner']
                source=actual if tie else rest
                length=np.linalg.norm(source['tie_outer']-source['tie_inner'])
                def pose(x):
                    rotation=Rotation.from_rotvec(x[2:5])
                    def rigid(point):return rest['hub']+rotation.apply(point-rest['hub'])+x[5:8]
                    balls={}
                    for i,arm in enumerate(('lower','upper')):
                        origin,axis,offset=arm_frames[arm]
                        balls[arm]=origin+Rotation.from_rotvec(axis*x[i]).apply(offset)
                    return rigid,balls
                def residual(x):
                    rigid,balls=pose(x)
                    return np.r_[rigid(rest['lower_ball'])-balls['lower'],
                                 rigid(rest['upper_ball'])-balls['upper'],
                                 np.linalg.norm(rigid(rest['tie_outer'])-inner)-length,
                                 rigid(rest['hub'])[2]-actual['hub'][2]]
                fit=least_squares(residual,initial,xtol=1e-12,ftol=1e-12,gtol=1e-12,max_nfev=300)
                if not fit.success or max(abs(fit.fun))>1e-7:
                    raise ValueError(f'{corner} {name}: diagnostic pose did not solve at {sample["t"]}')
                rigid,_=pose(fit.x);axis=rigid(rest['hub_axis'])-rigid(rest['hub'])
                axis*=1 if axis[0]>=0 else -1
                if name=='reference' and np.linalg.norm(rigid(rest['hub'])-recorded['ideal']['hub'])>1e-6:
                    raise ValueError('Diagnostic baseline disagrees with unchanged independent reference')
                predictions[name]=float(angles(axis)[1])
            row['corners'][corner]=dict(actual_toe_deg=recorded['actual_toe_deg'],predicted_toe_deg=predictions)
        samples.append(row)
    if not samples:raise ValueError('No samples in requested time window')
    means={name:float(np.mean([row['corners'][c]['predicted_toe_deg'][name] for row in samples for c in ('FL','FR')])) for name in modes}
    means['actual']=float(np.mean([row['corners'][c]['actual_toe_deg'] for row in samples for c in ('FL','FR')]))
    return dict(scope=__doc__,run=str(run.resolve()),after_s=after,qualification_changed=False,
                mean_front_toe_deg=means,samples=samples,
                hashes={name:hashlib.sha256((run/name).read_bytes()).hexdigest() for name in files})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path)
    p.add_argument('--after',type=float,default=17.);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();report=diagnose(a.run,a.after)
    a.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report['mean_front_toe_deg'],indent=2))
