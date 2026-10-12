"""Separate recorded rack motion into mounting, guide and actuator compliance.

Every measurement is in the recorded chassis frame or the rack housing mount
frame. This is a diagnostic decomposition; it never updates the CAD reference.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle_motion import rigid_fit


def diagnose(run, after=17.):
    files = ('build_manifest.json', 'motion_diagnostics.json')
    manifest, motion = [json.loads((run/name).read_text(encoding='utf-8')) for name in files]
    contract = manifest['steering_contract']
    original = {name: np.array(node['position']) for name, node in manifest['nodes'].items()}
    chassis = manifest['chassis_nodes']
    mounts = [name for name in contract['housing_nodes'] if '_mount_' in name]
    masses = np.array([manifest['nodes'][name]['mass_kg'] for name in chassis])
    axis = np.array(contract['axis'])
    samples = []
    for sample in motion['samples']:
        if sample['t'] < after:
            continue
        world = sample['reference_positions']
        rotation, translation = rigid_fit([original[n] for n in chassis], [world[n] for n in chassis], masses)
        local = {name: (np.array(point)-translation)@rotation.T for name, point in world.items()}
        housing_rotation, housing_translation = rigid_fit([original[n] for n in mounts], [local[n] for n in mounts])
        housing = {name: (point-housing_translation)@housing_rotation.T for name, point in local.items()}
        target = sample['rack_target_m']
        endpoints = {}
        for corner in ('FL', 'FR'):
            name = corner+'_tie_inner'
            a, b = contract['rail_nodes'][contract['rail_sliders'][name]]
            line = housing[b]-housing[a]
            fraction = (housing[name]-housing[a])@line/(line@line)
            nearest = housing[a]+fraction*line
            original_guide_point = original[a]+fraction*(original[b]-original[a])
            expected = original[name]+axis*target
            mounted_expected = expected@housing_rotation+housing_translation
            endpoints[corner] = dict(
                chassis_error_m=(local[name]-expected).tolist(),
                mounting_error_m=(mounted_expected-expected).tolist(),
                housing_frame_error_m=(housing[name]-expected).tolist(),
                guide_deformation_m=(nearest-original_guide_point).tolist(),
                travel_along_guide_error_m=(original_guide_point-expected).tolist(),
                slider_off_guide_m=(housing[name]-nearest).tolist())
        a, b = contract['actuator_nodes']
        extension = float(np.linalg.norm(local[b]-local[a])-contract['actuator_rest_length_m'])
        samples.append(dict(t=sample['t'],endpoints=endpoints,
                            actuator_error_m=extension-target))
    if not samples:
        raise ValueError('No complete rack samples in the requested time interval')
    mean = {corner: {key: np.mean([row['endpoints'][corner][key] for row in samples],axis=0).tolist()
                    for key in samples[0]['endpoints'][corner]} for corner in ('FL','FR')}
    return dict(scope=__doc__,run=str(run.resolve()),after_s=after,qualification_changed=False,
                mean_endpoint_displacements_m=mean,
                mean_actuator_error_m=float(np.mean([row['actuator_error_m'] for row in samples])),samples=samples,
                hashes={name:hashlib.sha256((run/name).read_bytes()).hexdigest() for name in files})


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    parser.add_argument('--after',type=float,default=17.)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=diagnose(args.run,args.after)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key not in ('samples','hashes')},indent=2))
