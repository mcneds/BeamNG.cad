"""Attribute a recorded hub-path error; measured geometry never qualifies a run.

Solve the same rigid linkage with controlled substitutions of measured frame
mounts and rod lengths. Compare with the original independent prediction first.
This is a diagnostic sensitivity experiment, not a replacement acceptance model.
"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle_motion import Predictor

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('run',type=Path)
p.add_argument('--output',type=Path)
a=p.parse_args()
read=lambda name:json.loads((a.run/name).read_text())
manifest=read('build_manifest.json');comparison=read('motion_comparison.json')
predictor=Predictor(manifest);result={}
for corner,mechanism in predictor.mechanisms.items():
    if not mechanism.radius_toe:continue
    sample=max((s for s in comparison['samples'] if s['t']>=4),key=lambda s:s['corners'][corner]['hub_path_error_m'])
    recorded=sample['corners'][corner];actual={k:np.array(v) for k,v in recorded['actual'].items()}
    rest=mechanism.p;links=mechanism.locating_links
    baseline,_=mechanism.solve(recorded['travel_m'])
    modes={}
    for mounts,rods in ((False,False),(True,False),(False,True),(True,True)):
        origin=actual['hinge_inner'] if mounts else rest['hinge_inner']
        axis=(actual if mounts else rest)['hinge_outer']-origin;axis/=np.linalg.norm(axis)
        original_axis=rest['hinge_outer']-rest['hinge_inner'];original_axis/=np.linalg.norm(original_axis)
        rotation=Rotation.align_vectors([axis],[original_axis])[0]
        carrier=rotation.apply(rest['carrier_ball']-rest['hinge_inner'])
        def pose(x):
            rigid=lambda point:rest['hub']+Rotation.from_rotvec(x[1:4]).apply(point-rest['hub'])+x[4:7]
            arm=origin+Rotation.from_rotvec(axis*x[0]).apply(carrier)
            return rigid,arm
        def residual(x):
            rigid,arm=pose(x)
            values=list(rigid(rest['carrier_ball'])-arm)
            for link in links:
                inner=link+'_inner';outer=link+'_outer'
                length=np.linalg.norm((actual if rods else rest)[outer]-(actual if rods else rest)[inner])
                values.append(np.linalg.norm(rigid(rest[outer])-(actual if mounts else rest)[inner])-length)
            return np.r_[values,rigid(rest['hub'])[2]-actual['hub'][2]]
        fit=least_squares(residual,baseline,xtol=1e-12,ftol=1e-12,gtol=1e-12,max_nfev=500)
        if not fit.success or max(abs(fit.fun))>1e-7:raise ValueError('Diagnostic pose did not solve: '+corner)
        hub=pose(fit.x)[0](rest['hub'])
        if not mounts and not rods and np.linalg.norm(hub-recorded['ideal']['hub'])>1e-6:
            raise ValueError('Diagnostic baseline differs from original independent prediction')
        modes[('measured_mounts' if mounts else 'original_mounts')+'_'+('measured_rods' if rods else 'original_rods')]=dict(
            hub_m=hub.tolist(),remaining_hub_error_m=float(np.linalg.norm(hub-actual['hub'])))
    result[corner]=dict(time_s=sample['t'],travel_m=recorded['travel_m'],original_error_m=recorded['hub_path_error_m'],
        rod_length_changes_m={link:float(np.linalg.norm(actual[link+'_outer']-actual[link+'_inner'])-
            np.linalg.norm(rest[link+'_outer']-rest[link+'_inner'])) for link in links},experiments=modes)
report=dict(scope=__doc__,run=str(a.run.resolve()),corners=result)
text=json.dumps(report,indent=2)
if a.output:a.output.write_text(text+'\n')
print(text)
