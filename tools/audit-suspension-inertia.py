"""Compare CAD and generated rigid-member kinetic inertia through suspension travel.

The covered arms/carriers are only part of the moving system: wheels, links,
coilovers, chassis motion and tire compliance are not included in the summed
kinetic mass. Results are contribution errors, not vehicle eigenfrequencies or
physical qualification. The reference may contain explicitly provisional mass
and thickness inputs; this audit does not turn them into measurements.
"""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
import components as c
from suspension_loads import ride_reference
from suspension_inertia import rigid_kinetic_mass,nodal_kinetic_mass,rigid_kinetic_matrix,nodal_kinetic_matrix
from vehicle_templates import TemplateModel,Mechanism


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(manifest_path,reference_path,step=1e-4,steering=False):
    m=read(manifest_path);project=read(reference_path);model=TemplateModel(m['template_definition'])
    components={v['Id']:v for v in project['Components']};roles={v:k for k,v in m['component_roles'].items() if v}
    suffixes={'upper_wishbone':'upper_arm','lower_wishbone':'lower_arm','trailing_arm':'trailing_arm','upright':'upright'}
    result=dict(scope=__doc__,manifest=str(manifest_path.resolve()),manifest_sha256=sha(manifest_path),
        reference_project=str(reference_path.resolve()),reference_project_sha256=sha(reference_path),step_m=step,
        expected_vehicle_mass_kg=m['expected_dry_mass_kg'],recorded_cad_vehicle_mass_kg=m.get('cad_dry_mass_kg'),
        numerical_mass_kg=m.get('numerical_mass',{}).get('added_mass_kg'),corners={},reference_inputs={},qualified=False)
    for corner in ('FL','FR','RL','RR'):
        mechanism=Mechanism(model,corner);height,extension,kind=ride_reference(model,corner,m.get('alignment',{}));bodies={}
        for suffix,key in suffixes.items():
            owner=roles.get(corner.lower()+'_'+suffix)
            if owner is None:continue
            comp=components[owner];meshes,moments,_=c.read_geometry(comp);folder=Path(comp['GeometryDirectory'])
            if comp.get('MvpRole')!=corner.lower()+'_'+suffix:raise ValueError('Reference component role differs')
            allocations=m['mass_allocations'][owner]
            positions=np.array([m['nodes'][n]['position'] for n in allocations]);weights=np.array(list(allocations.values()))
            # Use ownership allocations, not whole assembled shared-node masses.
            # A hinge node can carry several components without double counting.
            bodies[owner]=(key,moments,positions,weights)
            paths=[folder/'geometry.json',folder/'material-snapshot.json']+[folder/r['File'] for r,_ in meshes]
            result['reference_inputs'][owner]=dict(name=comp['Name'],role=comp['MvpRole'],
                files={str(p.resolve()):sha(p) for p in paths},mass_policy=comp.get('MassPolicy'),
                thickness_m=comp.get('Thickness'),surface_bodies=sum(r.get('BodyKind')=='surface' for r,_ in meshes),
                cad_mass_kg=float(moments[0]),generated_allocated_mass_kg=float(weights.sum()))
        samples=[]
        for offset in (-.02,-.01,0.,.01,.02):
            h=height+offset;x,_=mechanism.solve(h,extension);lo,_=mechanism.solve(h-step,extension);hi,_=mechanism.solve(h+step,extension)
            transform=mechanism.component_transforms(x,extension)
            low=mechanism.component_transforms(lo,extension);high=mechanism.component_transforms(hi,extension)
            if steering and corner.startswith('F'):
                sl,_=mechanism.solve(h,extension-step);sh,_=mechanism.solve(h,extension+step)
                steer_low=mechanism.component_transforms(sl,extension-step);steer_high=mechanism.component_transforms(sh,extension+step)
            values={}
            for owner,(key,moments,positions,weights) in bodies.items():
                if key not in transform:raise ValueError('Missing rigid-member transform: '+key)
                derivative=(high[key]-low[key])/(2*step)
                target=rigid_kinetic_mass(*moments,transform[key],derivative)
                actual=nodal_kinetic_mass(positions,weights,derivative)
                if target['kinetic_mass_kg']<=1e-10:raise ValueError('Moving member has no kinetic inertia')
                values[owner]=dict(cad=target,generated_kinetic_mass_kg=actual,
                    relative_error=actual/target['kinetic_mass_kg']-1.)
                if steering and corner.startswith('F'):
                    derivatives=[derivative,(steer_high[key]-steer_low[key])/(2*step)]
                    values[owner]['cad_generalized_mass_kg']=rigid_kinetic_matrix(*moments,transform[key],derivatives).tolist()
                    values[owner]['generated_generalized_mass_kg']=nodal_kinetic_matrix(positions,weights,derivatives).tolist()
            target=sum(v['cad']['kinetic_mass_kg'] for v in values.values());actual=sum(v['generated_kinetic_mass_kg'] for v in values.values())
            samples.append(dict(travel_from_reference_m=offset,travel_from_captured_pose_m=h,components=values,
                cad_member_kinetic_mass_kg=target,generated_member_kinetic_mass_kg=actual,relative_error=actual/target-1))
            if steering and corner.startswith('F'):
                samples[-1]['motion_coordinates']=['hub_height_m','steering_actuator_extension_m']
                for key in ('cad_generalized_mass_kg','generated_generalized_mass_kg'):
                    samples[-1][key]=sum(np.array(v[key]) for v in values.values()).tolist()
        result['corners'][corner]=dict(reference=kind,actuator_extension_m=extension,samples=samples,
            max_relative_error=max(abs(s['relative_error']) for s in samples))
        print(corner, 'member inertia excess',f"{result['corners'][corner]['max_relative_error']:.1%}",flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('reference_project',type=Path)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--steering',action='store_true',help='Also audit the coupled front hub-travel/actuator-extension mass matrix');a=p.parse_args();r=audit(a.manifest,a.reference_project,steering=a.steering)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,indent=2,allow_nan=False))
