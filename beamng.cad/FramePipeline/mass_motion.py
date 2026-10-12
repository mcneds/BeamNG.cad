"""Kinetic sensitivity of existing nodes to ideal CAD suspension travel."""
import numpy as np
import hashlib,json
from pathlib import Path
from suspension_loads import ride_reference
from vehicle_templates import TemplateModel,Mechanism


def normalized_inertia_cost(target,jacobian):
    """Per-kg trace increment, invariant to invertible coordinate changes."""
    target=np.asarray(target,float);jacobian=np.asarray(jacobian,float)
    if (target.shape!=(2,2) or jacobian.shape!=(3,2) or
            not np.isfinite(target).all() or not np.isfinite(jacobian).all() or
            not np.allclose(target,target.T,atol=1e-10,rtol=1e-8)):
        raise ValueError('Invalid coupled inertia data')
    try:np.linalg.cholesky(target)
    except np.linalg.LinAlgError as exc:raise ValueError('Reference inertia must be positive definite') from exc
    return float(np.trace(np.linalg.solve(target,jacobian.T@jacobian)))


def pose_offsets(values=None):
    """Explicit diagnostic operating envelope; never alters physical travel."""
    if values is None:return (-.02,-.01,0.,.01,.02)
    if (not isinstance(values,(list,tuple)) or not 1<=len(values)<=17 or
        any(isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v) or abs(v)>.15 for v in values) or
        tuple(sorted(set(values)))!=tuple(values) or 0. not in values):
        raise ValueError('Motion offsets must be sorted unique finite values within +/-150 mm, include zero, and contain at most 17 poses')
    return tuple(float(v) for v in values)


def coupled_motion_cost(manifest,names,reference_project,step=1e-4,travel_offsets=None):
    """Minimize added covered-member energy ratios in travel AND steering.

    Equal average over declared travel poses; trace(Mcad^-1 * Madded) treats both
    generalized coordinates without an arbitrary steering/travel unit scale.
    Ownership fractions match the generator's additive-mass allocation policy.
    Wheels, links and tires remain outside this CAD member reference.
    """
    from components import read_geometry
    from suspension_inertia import rigid_kinetic_matrix
    offsets=pose_offsets(travel_offsets)
    if not 1e-6<=step<=1e-3:raise ValueError('Invalid finite-difference step')
    path=Path(reference_project);raw=path.read_bytes();project=json.loads(raw)
    components={c['Id']:c for c in project['Components']};roles={r:o for o,r in manifest['component_roles'].items() if r}
    selected=set(names);frame=set(manifest['chassis_nodes']);covered=selected&frame
    cost={n:0. for n in names};details={};inputs={}
    model=TemplateModel(manifest['template_definition'])
    for corner in ('FL','FR'):
        mechanism=Mechanism(model,corner);height,extension,_=ride_reference(model,corner,manifest.get('alignment',{}));bodies={}
        for suffix,key in [('upper_wishbone','upper_arm'),('lower_wishbone','lower_arm'),('upright','upright')]:
            owner=roles[corner.lower()+'_'+suffix];component=components[owner];folder=Path(component['GeometryDirectory'])
            if component.get('MvpRole')!=corner.lower()+'_'+suffix:raise ValueError('Reference component role differs')
            expected=manifest['geometry_inputs_sha256'][owner]
            actual={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in expected}
            if actual!=expected:raise ValueError('Reference geometry/material differs from generated baseline')
            _,moments,_=read_geometry(component)
            report=manifest['component_reports'][owner]
            if not np.isclose(moments[0],report['target_mass_kg'],rtol=1e-8,atol=1e-8) or not np.allclose(moments[1],report['target_com_m'],rtol=0,atol=1e-7):
                raise ValueError('Reference mass policy differs from generated baseline')
            bodies[owner]=(key,moments);inputs[owner]=dict(directory=str(folder),files=actual,mass_policy=component.get('MassPolicy'),thickness_m=component.get('Thickness'))
        samples=[]
        for offset in offsets:
            h=height+offset;x,pose=mechanism.solve(h,extension)
            residual=np.r_[mechanism.constraints(x,extension),pose['hub'][2]-mechanism.p['hub'][2]-h]
            if not np.isfinite(residual).all() or max(abs(residual))>1e-7:raise ValueError('Operating-envelope CAD pose did not converge')
            transform=mechanism.component_transforms(x,extension)
            transforms=[]
            for a,b in [(h-step,extension),(h+step,extension),(h,extension-step),(h,extension+step)]:
                pose,_=mechanism.solve(a,b);transforms.append(mechanism.component_transforms(pose,b))
            reference=np.zeros((2,2));derivatives={}
            for owner,(key,moments) in bodies.items():
                ds=[(transforms[1][key]-transforms[0][key])/(2*step),(transforms[3][key]-transforms[2][key])/(2*step)]
                derivatives[owner]=ds;reference+=rigid_kinetic_matrix(*moments,transform[key],ds)
            velocities={};sample_cost={n:0. for n in names}
            for owner,ds in derivatives.items():
                for name in selected&set(manifest['mass_allocations'][owner]):
                    point=np.r_[manifest['nodes'][name]['position'],1.];j=np.array([(d@point)[:3] for d in ds]).T
                    if name in velocities and np.linalg.norm(velocities[name]-j)>1e-4:raise ValueError('Shared node has conflicting ideal motion: '+name)
                    if name in frame and np.linalg.norm(j)>1e-4:raise ValueError('Chassis node moves in ideal mechanism')
                    velocities[name]=j;covered.add(name)
                    fraction=manifest['mass_allocations'][owner][name]/manifest['nodes'][name]['mass_kg']
                    if not 0<=fraction<=1+1e-8:raise ValueError('Invalid mass ownership fraction')
                    sample_cost[name]+=fraction*normalized_inertia_cost(reference,j)
            for name,value in sample_cost.items():cost[name]+=value/len(offsets)
            samples.append(dict(travel_offset_m=offset,cad_generalized_mass_kg=reference.tolist(),node_cost_per_kg=sample_cost))
        details[corner]=samples
    if selected-covered:raise ValueError('No coupled mass sensitivity for '+', '.join(sorted(selected-covered)))
    if path.read_bytes()!=raw:raise ValueError('Reference project changed during optimization setup')
    for item in inputs.values():
        if any(hashlib.sha256((Path(item['directory'])/n).read_bytes()).hexdigest()!=v for n,v in item['files'].items()):raise ValueError('Reference input changed during optimization setup')
    return cost,dict(scope=coupled_motion_cost.__doc__,objective='mean_normalized_inertia_trace',cost_units='1/kg',step_m=step,
        travel_offsets_m=list(offsets),travel_scope='Evaluation envelope only; no physical travel limit or hardpoint changes',
        reference_project=str(path.resolve()),reference_project_sha256=hashlib.sha256(raw).hexdigest(),reference_inputs=inputs,corners=details)


def motion_cost(manifest,names,step=1e-4):
    if not 1e-6<=step<=1e-3:raise ValueError('Invalid finite-difference step')
    model=TemplateModel(manifest['template_definition']);roles={r:o for o,r in manifest['component_roles'].items() if r}
    selected=set(names);frame=set(manifest['chassis_nodes']);cost={n:0. for n in names};covered=set(frame)&selected;details={}
    for corner in ('FL','FR'):
        mech=Mechanism(model,corner);height,extension,_=ride_reference(model,corner,manifest.get('alignment',{}))
        low,lo=mech.solve(height-step,extension);high,hi=mech.solve(height+step,extension)
        tl=mech.component_transforms(low,extension);th=mech.component_transforms(high,extension);velocities={}
        for suffix,key in [('upper_wishbone','upper_arm'),('lower_wishbone','lower_arm'),('upright','upright'),('wheel','wheel')]:
            owner=roles.get(corner.lower()+'_'+suffix)
            if owner is None or key not in tl:continue
            derivative=(th[key]-tl[key])/(2*step)
            for name in set(manifest['mass_allocations'][owner])&selected:
                v=(derivative@np.r_[manifest['nodes'][name]['position'],1.])[:3]
                if name in velocities and np.linalg.norm(velocities[name]-v)>1e-4:raise ValueError('Shared node has conflicting ideal motion: '+name)
                velocities[name]=v
        hp=manifest['wheels'][corner]['hardpoint_nodes']
        for key in ('tie_inner','tie_outer','shock_top','shock_bottom'):
            name=hp.get(key)
            if name in selected and key in hi:velocities[name]=(np.asarray(hi[key])-lo[key])/(2*step)
        for name,v in velocities.items():
            if not np.isfinite(v).all():raise ValueError('Nonfinite mechanism derivative')
            if name in frame and np.linalg.norm(v)>1e-4:raise ValueError('Chassis node moves in ideal mechanism')
            cost[name]=max(cost[name],float(v@v));covered.add(name)
        details[corner]={name:np.asarray(v).tolist() for name,v in velocities.items()}
    if selected-covered:raise ValueError('No kinematic mass sensitivity for '+', '.join(sorted(selected-covered)))
    return cost,dict(step_m=step,node_velocities_per_unit_hub_travel=details,
        scope='Squared full spatial velocity per unit ideal hub travel. It weights added kinetic inertia, not the gravity-derivative effective mass used for preload. Chassis geometry and intended motion are unchanged.')
