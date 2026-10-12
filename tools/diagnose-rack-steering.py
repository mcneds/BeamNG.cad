"""Incremental rack-motion attribution through the unchanged CAD linkage.

The ordered substitutions are geometric diagnostics, not independent causal
experiments or qualification. Native suspension travel and CAD tie lengths
stay fixed. The last substitution must reconstruct the recorded endpoint.
"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle_motion import Predictor,rigid_fit,angles
rack_pose=runpy.run_path(str(ROOT/'tools/diagnose-straightline-suspension.py'))['rack_pose']


def diagnose(run,after=17.):
    files=['build_manifest.json','motion_diagnostics.json','motion_comparison.json','completion.json']
    manifest,raw,comparison,completion=[json.loads((run/p).read_text()) for p in files]
    if completion.get('status')!='completed':raise ValueError('Requires complete recording')
    contract=manifest['steering_contract'];original={n:np.array(v['position']) for n,v in manifest['nodes'].items()}
    chassis=manifest['chassis_nodes'];masses=[manifest['nodes'][n]['mass_kg'] for n in chassis]
    mounts=[n for n in contract['housing_nodes'] if '_mount_' in n]
    predictor=Predictor(manifest);samples=[]
    for sample in raw['samples']:
        if sample['t']<after:continue
        row=min(comparison['samples'],key=lambda r:abs(r['t']-sample['t']))
        if abs(row['t']-sample['t'])>1e-6:raise ValueError('Motion histories do not align')
        # Native single-precision rest lengths leave nanometre target offsets.
        if abs(row['steering_applied'])>1e-9 or abs(row['steering_command'])>1e-9 or abs(sample['rack_target_m'])>1e-7:raise ValueError('Requires zero steering')
        world=sample['reference_positions']
        rotation,translation=rigid_fit([original[n] for n in chassis],[world[n] for n in chassis],masses)
        local={n:(np.array(p)-translation)@rotation.T for n,p in world.items()}
        hr,ht=rigid_fit([original[n] for n in mounts],[local[n] for n in mounts])
        housing={n:(p-ht)@hr.T for n,p in local.items()}
        observed=dict(t=sample['t'],corners={})
        for corner in ('FL','FR'):
            name=corner+'_tie_inner';a,b=contract['rail_nodes'][contract['rail_sliders'][name]]
            line=housing[b]-housing[a];fraction=(housing[name]-housing[a])@line/(line@line)
            nearest=housing[a]+fraction*line;old=original[a]+fraction*(original[b]-original[a])
            points={'reference':original[name], 'housing':original[name]@hr+ht}
            points['guide']=points['housing']+(nearest-old)@hr
            points['travel']=points['guide']+(old-original[name])@hr
            points['off_guide']=points['travel']+(housing[name]-nearest)@hr
            if np.linalg.norm(points['off_guide']-local[name])>1e-9:raise ValueError('Endpoint decomposition failed')
            data=row['corners'][corner];mechanism=predictor.mechanisms[corner]
            predictor.solve(corner,data['travel_m'],0);state=predictor.previous[corner].copy()
            predictions={}
            for key,point in points.items():
                pose=rack_pose(mechanism,data['travel_m'],point,state)
                axis=pose['hub_axis']-pose['hub'];axis*=1 if mechanism.p['hub_axis'][0]>mechanism.p['hub'][0] else -1
                predictions[key]=float(angles(axis)[1])
            observed['corners'][corner]=dict(actual=data['actual_toe_deg'],**predictions)
        samples.append(observed)
    if not samples:raise ValueError('No selected samples')
    means={k:float(np.mean([r['corners'][c][k] for r in samples for c in ('FL','FR')])) for k in samples[0]['corners']['FL']}
    return dict(scope=__doc__,qualified=False,run=str(run),after_s=after,mean_front_toe_deg=means,samples=samples,
                input_sha256={p:hashlib.sha256((run/p).read_bytes()).hexdigest() for p in files})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise ValueError('Use a new output path')
    result=diagnose(a.run);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['mean_front_toe_deg'],indent=2))
