"""Compare axle, hub-ring and tread-ring alignment over recorded time.

Ring axes describe tire deformation, not a contact-force or vehicle-dynamics
reference. Recorded native forces and slip retain their native sign convention.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle_motion import rigid_fit,angles


def diagnose(run,after=17.):
    files=('build_manifest.json','motion_diagnostics.json')
    manifest,motion=[json.loads((run/name).read_text(encoding='utf-8')) for name in files]
    chassis=manifest['chassis_nodes']
    original=np.array([manifest['nodes'][name]['position'] for name in chassis])
    masses=np.array([manifest['nodes'][name]['mass_kg'] for name in chassis])
    samples=[];signs={}
    for sample in motion['samples']:
        world=sample['reference_positions']
        rotation,_=rigid_fit(original,[world[n] for n in chassis],masses)
        corners={}
        for corner,wheel in manifest['wheels'].items():
            shape=sample['wheel_torques'][corner]['tire_shape']
            a,b=[world[wheel['nodes'][name]] for name in ('axis_in','axis_out')]
            axes=dict(axle=(np.array(b)-a)@rotation.T,
                      hub=np.array(shape['hub_axis']['direction_world'])@rotation.T,
                      tread=np.array(shape['tread_axis']['direction_world'])@rotation.T)
            values={}
            for kind,axis in axes.items():
                # Set direction once; never flip a later damaged or reversed axis.
                signs.setdefault((corner,kind),1 if axis[0]>0 else -1)
                camber,toe=angles(axis*signs[corner,kind])
                values[kind]=dict(toe_deg=float(toe),camber_deg=float(camber))
            corners[corner]=dict(axes=values,down_force_n=shape['down_force_n'],side_slip_m_s=shape['side_slip_m_s'])
        if sample['t']>=after:
            samples.append(dict(t=sample['t'],corners=corners,steering_loads=sample.get('steering_loads')))
    if not samples:raise ValueError('No tire samples in requested interval')
    mean={axle:{kind:{quantity:float(np.mean([s['corners'][corner]['axes'][kind][quantity] for s in samples for corner in corners]))
                     for quantity in ('toe_deg','camber_deg')} for kind in ('axle','hub','tread')}
          for axle,corners in dict(front=('FL','FR'),rear=('RL','RR')).items()}
    return dict(scope=__doc__,run=str(run.resolve()),after_s=after,qualification_changed=False,
                mean_alignment=mean,samples=samples,
                hashes={name:hashlib.sha256((run/name).read_bytes()).hexdigest() for name in files})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path)
    p.add_argument('--after',type=float,default=17.);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();report=diagnose(a.run,a.after)
    a.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report['mean_alignment'],indent=2))
