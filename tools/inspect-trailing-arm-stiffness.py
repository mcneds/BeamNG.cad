"""Read-only linear gravity/load probe of generated two-point trailing arms.

Frame hinges are held at their declared positions. Generated wheel contact and
coilover preload act at design height. The free hinge rotation is projected out;
this isolates bracing compliance, not tire dynamics or full-vehicle equilibrium.
"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from frame_harness.build import beam_table
from frame_harness.projection import axial_columns
from rigid_bracing import gradient


def inspect(manifest_path):
    manifest_path=Path(manifest_path);m=json.loads(manifest_path.read_text())
    part=json.loads((manifest_path.parent/m['vehicle_directory']/m['main_jbeam']).read_text())[m['main_part']]
    report={}
    for corner,wheel in m['wheels'].items():
        if wheel['template']!='trailing_arm':continue
        role=corner.lower()+'_trailing_arm'
        owner=next(n for n,r in m['component_roles'].items() if r==role)
        names=list(m['mass_allocations'][owner]);index={n:i for i,n in enumerate(names)}
        xyz=np.array([m['nodes'][n]['position'] for n in names])
        beams=[b for b in beam_table(part) if b['a'] in index and b['b'] in index]
        A,_,_=axial_columns(xyz,[(index[b['a']],index[b['b']]) for b in beams])
        K=(A*np.array([b['spring'] for b in beams]))@A.T
        for row in m['torsionbars']:
            if not set(row[:4])<=set(names):continue
            ids=[index[n] for n in row[:4]];g=np.zeros_like(xyz);g[ids]=gradient(xyz[ids]);v=g.ravel()
            K+=row[4]['spring']*np.outer(v,v)
        force=np.zeros_like(xyz);force[:,2]=[-9.81*m['nodes'][n]['mass_kg'] for n in names]
        axes=[index[wheel['nodes'][key]] for key in ('axis_in','axis_out')]
        force[axes,2]+=(wheel['static_support_mass_kg']-wheel['wheel_mass_kg'])*9.81/2
        p=m['template_definition']['hardpoints'][corner]
        direction=np.array(p['shock_bottom'])-p['shock_top'];direction/=np.linalg.norm(direction)
        force[index[wheel['nodes']['shock_bottom']]]+=wheel['spring_preload_n']*direction
        # Gravity at a shaft's outer endpoint reaches its declared carrier
        # supports. A least-norm force distribution preserves its full wrench.
        for joint in m['joints']:
            if joint.get('parent')!=owner or joint['kind']!='spherical':continue
            child=joint['nodes'][-1];parents=joint['nodes'][:-1]
            if child in index or not set(parents)<=set(names):continue
            center=np.mean([m['nodes'][n]['position'] for n in parents],axis=0)
            columns=[]
            for name in parents:
                r=np.array(m['nodes'][name]['position'])-center
                columns.extend(np.r_[axis,np.cross(r,axis)] for axis in np.eye(3))
            load=np.array([0.,0.,-9.81*m['nodes'][child]['mass_kg']])
            wrench=np.r_[load,np.cross(np.array(m['nodes'][child]['position'])-center,load)]
            distributed=np.linalg.lstsq(np.array(columns).T,wrench,rcond=None)[0].reshape(-1,3)
            force[[index[n] for n in parents]]+=distributed
        fixed=[index[wheel['hardpoint_nodes'][key]] for key in ('hinge_inner','hinge_outer')]
        free=np.array([i for i in range(len(names)*3) if i//3 not in fixed])
        eigen,modes=np.linalg.eigh(K[np.ix_(free,free)]);keep=eigen>max(eigen)*1e-8
        displacement=np.zeros(len(names)*3)
        displacement[free]=modes[:,keep]@((modes[:,keep].T@force.ravel()[free])/eigen[keep])
        displacement=displacement.reshape(-1,3);deformed=xyz+displacement
        axis=deformed[axes[1]]-deformed[axes[0]]
        report[corner]=dict(toe_deg=float(np.degrees(np.arctan2(axis[1],axis[0]))),
            camber_deg=float(np.degrees(np.arctan2(axis[2],np.linalg.norm(axis[:2])))),
            maximum_displacement_m=float(max(np.linalg.norm(displacement,axis=1))),
            free_rigid_modes=int(sum(~keep)),scope=__doc__)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('manifest',type=Path)
    print(json.dumps(inspect(parser.parse_args().manifest),indent=2))
