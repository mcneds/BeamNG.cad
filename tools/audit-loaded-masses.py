"""Read-only audit of brake reaction masses against the documented car guideline.

The 2 kg guideline applies to brake reaction nodes, not tire tread nodes or every
structural node. The moment bound indicates whether redistributing that component's
existing CAD mass can reach the target at a given fixed point at all.
"""
import argparse,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components as c
p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);p.add_argument('--target',type=float,default=2.);a=p.parse_args()
m=json.loads(a.manifest.read_text());parts=json.loads((a.manifest.parent/m['vehicle_directory']/m['main_jbeam']).read_text())
rows=[]
for part in parts.values():
    if 'pressureWheels' not in part:continue
    header=part['pressureWheels'][0]
    for row,options in c.expand(part['pressureWheels']):
        wheel=dict(zip(header,row))|options;name=wheel['name']
        # Audit both axle nodes when the native default coupling is implicit.
        targets={'brake_arm':wheel['nodeArm:']}
        if 'nodeCoupling:' in wheel:targets['brake_coupling']=wheel['nodeCoupling:']
        else:targets.update(axis_1=wheel['node1:'],axis_2=wheel['node2:'])
        for role,node_name in targets.items():
            node=m['nodes'][node_name];owner=node['component'];report=m['component_reports'].get(owner,{})
            bound=None;additional=node['mass_kg']-m['mass_allocations'].get(owner,{}).get(node_name,0)
            if all(k in report for k in ('target_mass_kg','target_center_m','target_inertia_kg_m2')):
                mass=report['target_mass_kg'];inertia=np.array(report['target_inertia_kg_m2'])
                covariance=(np.trace(inertia)/2*np.eye(3)-inertia)/mass
                offset=np.array(node['position'])-report['target_center_m']
                bound=float(mass/(1+offset@np.linalg.solve(covariance,offset))+additional)
            rows.append(dict(wheel=name,role=role,node=node_name,mass_kg=node['mass_kg'],
                target_kg=a.target,target_met=node['mass_kg']>=a.target,
                maximum_from_existing_cad_moments_kg=bound,target_possible_from_existing_moments=bound is None or bound>=a.target,
                brake_torque_nm=wheel.get('brakeTorque')))
print(json.dumps(dict(scope='Typical-car brake-node guideline; feasibility bounds are necessary, not sufficient, for simultaneous allocation',
    reference='https://documentation.beamng.com/modding/vehicle/sections/wheels/',nodes=rows),indent=2))
