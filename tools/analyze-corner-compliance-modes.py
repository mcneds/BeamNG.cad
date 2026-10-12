"""Diagnostic fixed-chassis suspension tangent, with optional rigid wheel inertia.

This is NOT a vehicle modal reference: tire/contact/pressure stiffness, wheel
spin/gyroscopic forces, frame motion, shaft coupling, prestress, stops and
filtered damping states are omitted. It tests whether a numerical suspension
mode can plausibly overlap a recorded oscillation. No coefficients are fitted.
"""
import argparse,copy,hashlib,json,sys
from pathlib import Path
import numpy as np
from scipy.linalg import eigh
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from angular_screen import matrices
from frame_harness.build import node_table
from frame_harness.vehicle_motion import rigid_fit
from rigid_bracing import gradient


def ideal_positions(manifest,offset,steering_extension=0.):
    """Rigid CAD member positions at a diagnostic offset from ride height.

    This changes evaluation geometry only, never the generated hardpoints.
    Unsupported/unreachable states fail instead of silently clipping travel.
    """
    from vehicle_templates import TemplateModel,Mechanism
    from suspension_loads import ride_reference
    if not np.isfinite([offset,steering_extension]).all() or abs(offset)>.15 or abs(steering_extension)>.1:
        raise ValueError('Invalid diagnostic pose')
    model=TemplateModel(manifest['template_definition']);frame=set(manifest['chassis_nodes'])
    positions={n:np.array(v['position'],float) for n,v in manifest['nodes'].items()};assigned={};details={}
    for corner in ('FL','FR'):
        mechanism=Mechanism(model,corner);height,extension,_=ride_reference(model,corner,manifest.get('alignment',{}))
        x,p=mechanism.solve(height+offset,extension+steering_extension)
        residual=np.r_[mechanism.constraints(x,extension+steering_extension),p['hub'][2]-mechanism.p['hub'][2]-height-offset]
        if max(abs(residual))>1e-7:raise ValueError('Ideal pose did not converge')
        transforms=mechanism.component_transforms(x,extension+steering_extension)
        for suffix,key in [('upper_wishbone','upper_arm'),('lower_wishbone','lower_arm'),('upright','upright'),('wheel','wheel')]:
            owners=[o for o,r in manifest['component_roles'].items() if r==corner.lower()+'_'+suffix]
            if len(owners)!=1:raise ValueError('Ambiguous corner ownership')
            for name in manifest['mass_allocations'][owners[0]]:
                point=(transforms[key]@np.r_[manifest['nodes'][name]['position'],1.])[:3]
                if name in assigned and np.linalg.norm(point-assigned[name])>1e-6:raise ValueError('Shared node has conflicting ideal positions')
                if name in frame and np.linalg.norm(point-positions[name])>1e-6:raise ValueError('Ideal chassis anchor moves')
                assigned[name]=point;positions[name]=point
        details[corner]=dict(captured_pose_hub_offset_m=float(height+offset),residual_m=float(max(abs(residual))))
    return positions,dict(ride_offset_m=offset,steering_extension_m=steering_extension,corners=details,
        scope='Diagnostic ideal CAD poses; offsets are not new suspension limits or hardpoint changes')


def cross(v):
    x,y,z=v
    return np.array([[0.,-z,y],[z,0.,-x],[-y,x,0.]])


def wheel_mass_matrix(axle,positions,masses):
    """Condense a rigid, nonspinning wheel onto axle center and direction.

    Axis stretch and axial spin are excluded; free wheel spin needs its own
    coordinate. Every generated wheel mass is counted once, excluding axles.
    """
    axle=np.asarray(axle,float);positions=np.asarray(positions,float);masses=np.asarray(masses,float)
    if axle.shape!=(2,3) or positions.shape!=(len(masses),3) or not len(masses) or np.any(masses<=0) or not all(np.isfinite(v).all() for v in [axle,positions,masses]):
        raise ValueError('Invalid wheel geometry or mass')
    delta=axle[1]-axle[0];length=np.linalg.norm(delta)
    if length<1e-6:raise ValueError('Degenerate axle')
    axis=delta/length;center=axle.mean(0);result=np.zeros((6,6))
    for p,m in zip(positions,masses):
        lever=cross(p-center)@cross(axis)/length
        j=np.column_stack((.5*np.eye(3)+lever,.5*np.eye(3)-lever))
        result+=m*j.T@j
    return result


def generated_wheel_nodes(compiled,manifest,axes):
    actual=compiled['actual_nodes'];cid={v['cid']:n for n,v in actual.items()};explicit=set(manifest['nodes'])
    adjacent={n:set() for n in actual}
    for b in compiled['beams']:
        a,z=cid[b['a']],cid[b['b']];adjacent[a].add(z);adjacent[z].add(a)
    found=set();pending=list(axes)
    while pending:
        for name in adjacent[pending.pop()]:
            if name not in explicit and name not in found:found.add(name);pending.append(name)
    return sorted(found)


def strain_energy(part,nodes,displacements):
    """Twice the material strain energy; must sum to v.T K v."""
    terms=[]
    for section in ('beams','hydros','torsionbars'):
        defaults={}
        for row in part.get(section,[])[1:]:
            if isinstance(row,dict):defaults.update(row);continue
            ids=row[:4 if section=='torsionbars' else 2]
            v=np.array([displacements.get(n,np.zeros(3)) for n in ids])
            if not np.any(v):continue
            o=defaults|(row[-1] if isinstance(row[-1],dict) else {})
            p=np.array([nodes[n]['position'] for n in ids])
            if section=='torsionbars':change=float(np.sum(gradient(p)*v));spring=o['spring']
            else:
                d=p[1]-p[0];change=float((v[1]-v[0])@d/np.linalg.norm(d));spring=o.get('beamSpring',0)
            value=float(spring*change**2)
            if value>0:terms.append(dict(section=section,nodes=ids,coefficient=spring,twice_energy=value))
    total=sum(r['twice_energy'] for r in terms)
    for r in terms:r['fraction']=r['twice_energy']/total
    return total,sorted(terms,key=lambda r:r['twice_energy'],reverse=True)


def analyze(build,run,pose_run=None,travel_offset=None,steering_extension=0.):
    read=lambda p:json.loads(p.read_bytes());manifest=read(build/'manifest.json');probe=read(run/'probe.json')
    if hashlib.sha256((build/'manifest.json').read_bytes()).hexdigest()!=probe['manifest_sha256'] or not probe['sources_unchanged']:
        raise ValueError('Build does not match recording')
    source=build/manifest['vehicle_directory']/manifest['main_jbeam']
    if hashlib.sha256(source.read_bytes()).hexdigest()!=manifest['files'][source.relative_to(build).as_posix()]:raise ValueError('Changed JBeam')
    part=read(source)[manifest['main_part']];compiled=read(run/'compiled.json');frame=set(manifest['chassis_nodes']);results={}
    pose=None;pose_evidence=None;extra_sources=[]
    if travel_offset is not None:
        if pose_run is not None:raise ValueError('Choose measured or ideal pose')
        pose,pose_evidence=ideal_positions(manifest,travel_offset,steering_extension)
    if pose_run is not None:
        pp=read(pose_run/'probe.json');pj=read(pose_run/'job.json');motion=read(pose_run/'motion_diagnostics.json')
        if pp['manifest_sha256']!=probe['manifest_sha256'] or not pp['sources_unchanged'] or pp.get('error') or pp.get('completion',{}).get('status')!='completed' or motion['job_id']!=pj['id']:
            raise ValueError('Invalid measured-pose recording')
        sample=min(motion['samples'],key=lambda s:abs(s['t']-6.));positions=sample['mechanism_positions'];datum=sorted(frame)
        rotation,translation=rigid_fit([manifest['nodes'][n]['position'] for n in datum],[positions[n] for n in datum])
        pose={n:(np.array(p)-translation)@rotation.T for n,p in positions.items()}
        pose_evidence=dict(run=str(pose_run),time_s=sample['t'],scope='Geometry-only material tangent at measured pose; prestress/stops still omitted')
        extra_sources=[pose_run/n for n in ('probe.json','job.json','motion_diagnostics.json')]
    for corner in ('FL','FR'):
        roles={corner.lower()+'_'+s for s in ('upper_wishbone','lower_wishbone','upright','wheel')}
        selected=sorted(set().union(*(set(manifest['mass_allocations'][o]) for o,r in manifest['component_roles'].items() if r in roles))-frame)
        allowed=set(selected)|frame;subset=copy.deepcopy(part);excluded=[]
        for section,count in [('beams',2),('hydros',2),('torsionbars',4)]:
            rows=[part.get(section,[[]])[0]]
            for row in part.get(section,[])[1:]:
                if isinstance(row,dict):rows.append(row);continue
                ids=set(row[:count])
                if ids<=allowed:rows.append(row)
                elif ids&set(selected):excluded.append(dict(section=section,nodes=row[:count]))
            subset[section]=rows
        if any(isinstance(r,list) and r[0] in selected for r in part.get('slidenodes',[])[1:]):raise ValueError('Selected slider requires a different tangent model')
        subset['slidenodes']=[];nodes=node_table(subset);names=list(nodes)
        if pose is not None:
            for name,node in nodes.items():node['position']=pose[name].tolist()
        k,c=matrices(subset,nodes);indices=np.array([3*names.index(n)+a for n in selected for a in range(3)])
        mass=np.repeat([nodes[n]['options']['nodeWeight'] for n in selected],3);scale=np.sqrt(mass[:,None]*mass[None,:])
        k=k[indices][:,indices].toarray()*scale;c=c[indices][:,indices].toarray()*scale
        axes=[manifest['wheels'][corner]['nodes'][n] for n in ('axis_in','axis_out')]
        generated=generated_wheel_nodes(compiled,manifest,axes);wheel=manifest['wheels'][corner]
        if len(generated)!=wheel['tire_contract']['hub_nodes']+wheel['tire_contract']['tread_nodes']:raise ValueError('Generated wheel ownership ambiguous')
        positions=np.array([compiled['actual_nodes'][n]['position'] for n in generated]);weights=np.array([compiled['actual_nodes'][n]['mass_kg'] for n in generated])
        if not np.isclose(sum(weights),wheel['wheel_mass_kg'],rtol=1e-6):raise ValueError('Generated wheel mass differs')
        axle=np.array([compiled['actual_nodes'][n]['position'] for n in axes])
        if pose is not None:
            new_axle=np.array([pose[n] for n in axes]);u=axle[1]-axle[0];u/=np.linalg.norm(u);v=new_axle[1]-new_axle[0];v/=np.linalg.norm(v)
            dot=float(u@v)
            if dot<-.99:raise ValueError('Wheel axis reversed in measured pose')
            skew=cross(np.cross(u,v));rotation=np.eye(3)+skew+skew@skew/(1+dot)
            positions=(positions-axle.mean(0))@rotation.T+new_axle.mean(0);axle=new_axle
        wm=wheel_mass_matrix(axle,positions,weights)
        ai=np.array([3*selected.index(n)+i for n in axes for i in range(3)])
        delta=np.array(nodes[axes[1]]['position'])-nodes[axes[0]]['position'];angle=np.array([-delta[1],delta[0],0.])/(delta[0]**2+delta[1]**2)
        toe=np.zeros(len(mass));toe[ai[:3]]=-angle;toe[ai[3:]]=angle
        # Compare flex to authored bump steer at the same measured hub height.
        # Raw yaw compliance includes legitimate suspension travel.
        from vehicle_templates import TemplateModel,Mechanism
        from suspension_loads import ride_reference
        model=TemplateModel(manifest['template_definition']);mechanism=Mechanism(model,corner)
        _,extension,_=ride_reference(model,corner,manifest.get('alignment',{}));extension+=steering_extension
        height=float(np.mean([nodes[n]['position'][2] for n in axes])-mechanism.p['hub'][2]);step=1e-5
        _,low=mechanism.solve(height-step,extension);_,high=mechanism.solve(height+step,extension)
        a=np.asarray(low['hub_axis'])-low['hub'];b=np.asarray(high['hub_axis'])-high['hub']
        slope=float(np.arctan2(a[0]*b[1]-a[1]*b[0],a[0]*b[0]+a[1]*b[1])/(2*step))
        residual_toe=toe.copy();residual_toe[ai[[2,5]]]-=.5*slope
        reports={}
        for mode in ('without_wheel','rigid_wheel'):
            M=np.diag(mass)
            if mode=='rigid_wheel':M[np.ix_(ai,ai)]+=wm
            eigen,vectors=eigh(k,M);modes=[]
            if eigen.min()<-1e-5:raise ValueError('Negative stiffness mode in local screen')
            for i,value in enumerate(eigen):
                if value<=1. or value>(2*np.pi*150)**2:continue
                v=vectors[:,i];shape={n:v[3*j:3*j+3] for j,n in enumerate(selected)};energy,terms=strain_energy(subset,nodes,shape)
                if not np.isclose(energy,value,rtol=1e-7):raise ValueError('Modal strain-energy reconstruction differs')
                modes.append(dict(hz=float(np.sqrt(value)/(2*np.pi)),modal_damping_ratio=float(v@c@v/(2*np.sqrt(value))),
                    toe_gain_rad=float(toe@v),residual_toe_gain_rad=float(residual_toe@v),nodes={n:p.tolist() for n,p in shape.items()},largest_strain_energy_terms=terms[:8]))
            reports[mode]=modes
        # The fixed-chassis principal model is only a local necessary screen;
        # it omits coupling outside the selected corner and generated tire DOFs.
        mass_scale=np.sqrt(mass[:,None]*mass[None,:])
        local_step=.0005**2*k/mass_scale+2*.0005*c/mass_scale
        local_peak=float(np.linalg.eigvalsh(local_step)[-1])
        compliance=float(toe@np.linalg.solve(k,toe))
        results[corner]=dict(nodes=selected,excluded_constraints=excluded,local_explicit_step_eigenvalue=local_peak,
            ideal_toe_travel_slope_rad_per_m=slope,static_yaw_compliance_rad_per_nm=compliance,
            static_residual_toe_compliance_rad_per_nm=float(residual_toe@np.linalg.solve(k,residual_toe)),
            generated_wheel_nodes=len(generated),generated_wheel_mass_kg=float(sum(weights)),modes=reports)
    return dict(scope=__doc__,qualified=False,measured_pose=pose_evidence,corners=results,source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [build/'manifest.json',source,run/'compiled.json',run/'probe.json',Path(__file__),*extra_sources]})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('build',type=Path);p.add_argument('run',type=Path);p.add_argument('--pose-run',type=Path);p.add_argument('--travel-offset',type=float);p.add_argument('--steering-extension',type=float,default=0.);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    r=analyze(a.build,a.run,a.pose_run,a.travel_offset,a.steering_extension);a.output.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({c:{k:[{f:v[f] for f in ('hz','modal_damping_ratio','toe_gain_rad')} for v in modes] for k,modes in row['modes'].items()} for c,row in r['corners'].items()},indent=2))
