"""Completed vehicle packaging through the normal CAD worker boundary."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import tempfile
import shutil
import zipfile
import numpy as np
import components as c
import coilover_visuals
from component_worker import read, geometry_inputs, verify_current_frame, validate_project
from build_static_frame import completed_build, digest
from package_identity import layout
from prepare_frame import write_dae, dae_materials
from appearance_textures import dae_texture_assets
from vehicle_revisions import canonical, package_revision, appearance_meshes
from vehicle_templates import generate, frame_mounts, frame_mount_plan
from frame_harness.build import node_table, beam_table


def definition_for_project(project):
    if (project.get('JointWorkspace') or {}).get('Mode')=='authored':
        from joint_authoring import definition
        result=definition(project)
        from shaft_chains import validate
        validate(result,project['Components'])
        return result
    path=Path(project.get('TemplateDefinitionPath') or '')
    if not path.is_file():raise ValueError('Choose a reviewed vehicle template definition with hardpoints and mounts')
    definition=read(path)
    if definition.get('kind')!='vehicle_template' or definition.get('version')!=1:raise ValueError('Unsupported vehicle template definition')
    chosen={v['Category']:v['Template'] for v in project.get('MvpTemplates',[])}
    if chosen!=definition['templates']:raise ValueError('Vehicle setup changed; regenerate the template hardpoints and frame mounting plan')
    from shaft_chains import validate
    validate(definition,project['Components'])
    return definition


def template_input(project):
    definition=definition_for_project(project)
    raw=canonical(definition) if (project.get('JointWorkspace') or {}).get('Mode')=='authored' else Path(project['TemplateDefinitionPath']).read_bytes()
    if read_bytes(raw)!=definition:raise ValueError('Template changed during intake')
    return definition,raw


def build(project_path,output,cgal=None,save_report=False):
    output=Path(output).resolve()
    if output.exists():raise FileExistsError('Use a fresh revision directory')
    from frame_harness import build as harness_build
    from frame_harness.progress import emit
    from vehicle_wizard import kinematics as wizard_kinematics
    emit('Check vehicle inputs',completed=0,total=1)
    roots={'worker':Path(__file__).parent,'harness':Path(harness_build.__file__).parent,'kinematics':Path(wizard_kinematics.__file__).parent}
    sources={label+'/'+p.relative_to(root).as_posix():p for label,root in roots.items()
             for p in (list(root.glob('*.py'))+list((root/'lua').glob('*.lua'))) if p.is_file()}
    implementation={name:p.read_bytes() for name,p in sources.items()}
    project=read(project_path);definition,template_bytes=template_input(project)
    project_fingerprint=c.fingerprint(project)
    validate_project(project)
    receipt=Path(project.get('FrameBuildReceipt') or '')
    record,archive=completed_build(receipt)
    if record.get('identity')!=project['Identity']:raise ValueError('The calibrated frame belongs to a different project')
    frame=next(v for v in project['Components'] if v['Template']=='calibrated_frame')
    verify_current_frame(frame,record);inputs=geometry_inputs(project)
    emit('Check vehicle inputs',completed=1,total=1)
    with zipfile.ZipFile(archive) as z:contents={name:z.read(name) for name in z.namelist()}
    model=project['Identity']['namespace'];prefix='vehicles/'+model+'/'
    _,_,jbeam,_=layout(record);parts=read_bytes(contents[prefix+jbeam])
    if len(parts)!=1:raise ValueError('Start from a frame-only calibrated package')
    frame_source=contents[prefix+jbeam]
    original=copy.deepcopy(next(iter(parts.values())))
    mounts=frame_mounts(definition)
    if set(mounts)!=set(original.get('cadMountPatches',{})):raise ValueError('Frame mount plan differs; regenerate and calibrate the frame before building this vehicle')
    for name,position in mounts.items():
        if not np.allclose(position,original['cadMountPatches'][name]['position'],atol=1e-7,rtol=0):raise ValueError('Mount moved: '+name)
    plan=frame_mount_plan(definition,project['Components'])
    if any(original['cadMountPatches'][name].get('mode','short')!=item['mode'] for name,item in plan.items()):
        raise ValueError('Frame mount representation changed; regenerate and calibrate the frame with the current mounting plan')
    scratch=output.with_name(output.name+'.generation');scratch.mkdir(parents=True,exist_ok=False)
    try:
        from component_representation import physical_project,visual,refit_existing_part
        physical,representation_report=physical_project(project,c.read_geometry)
        frame_physical=next(v for v in physical['Components'] if v['Id']==frame['Id'])
        if frame_physical.get('_VisualMass'):
            # Fit combined frame and carried visual moments on the existing graph.
            representation_report['host_mass_fits']={frame['Id']:refit_existing_part(original,c.read_geometry(frame_physical)[1],frame_physical['_VisualMass'])}
        graph,part,wheels,kinematics,devices,meshes,bindings=generate(physical,original,definition,scratch=scratch,cgal=cgal)
        c.write(scratch/'representation.json',representation_report)
    except Exception as error:
        c.write(scratch/'failure.json',dict(error=str(error),project=str(project_path),frame_receipt=str(receipt)))
        raise ValueError(str(error)+'; generation evidence: '+str(scratch)) from error
    # Preserve the frame's authored skin and controller. New components carry
    # their own mesh IDs and binding groups independent of CAD object names.
    original_controllers=original.get('controller',[['fileName']])[1:]
    for row in original_controllers:
        if row[0] not in {r[0] for r in part['controller'][1:]}:part['controller'].append(row)
    part.pop('slots',None)
    part['information']=dict(name='CAD template vehicle',authors='BeamNG CAD',value=10000)
    part.setdefault('flexbodies',[['mesh','[group]:','nonFlexMaterials']])
    component_meshes={frame['Id']:[r[0] for r in part['flexbodies'][1:] if isinstance(r,list)]}
    bindings[frame['Id']]=['frame_structure']
    cad_materials={};coilover_render={};coilover_inputs={};wheel_render={}
    for index,comp in enumerate(project['Components']):
        emit('Package component meshes',completed=index,total=len(project['Components']),detail=comp['Name'])
        owner=comp['Id']
        if owner==frame['Id']:continue
        if owner not in meshes:
            if not visual(comp):raise ValueError('No physical template owns component '+comp['Name'])
            parent=comp.get('VisualParentId')
            if parent not in bindings:raise ValueError('Choose a physical render parent for visual-only component '+comp['Name'])
            meshes[owner]=appearance_meshes(comp)[0];bindings[owner]=bindings[parent]
            member=comp.get('VisualParentMemberId')
            if member:
                native=next(v for v in physical['JointWorkspace']['Members'] if v['Id']==member)
                groups={g for v in graph.nodes.values() for g in v['options'].get('group',[]) if g==member+'_structure'}
                if not groups:raise ValueError(comp['Name']+': chosen moving member has no render binding')
                bindings[owner]=sorted(groups)
        names=[]
        if owner in getattr(graph,'moving_render',{}):
            moving=[]
            for member in graph.moving_render[owner]:
                for mesh in member['meshes']:
                    name=model+'__'+owner+'_mesh_'+str(len(names));names.append(name);moving.append(mesh)
                    part['flexbodies'].append([name,[member['group']],[]])
            meshes[owner]=moving
        elif coilover_visuals.active(comp):
            render_context=dict(template_definition=definition,mass_allocations=graph.mass_allocations)
            split,names,props,flex,source,contract=coilover_visuals.render(comp,part,render_context,bindings[owner],model+'__'+owner+'_coilover')
            meshes[owner]=split;coilover_inputs[owner]=source;coilover_render[owner]=contract
            coilover_visuals.replace_rows(part,[],props,flex)
        else:
            for index,(item,_) in enumerate(meshes[owner]):names.append(model+'__'+owner+'_mesh_'+str(index))
            if (comp.get('MvpRole') or '').endswith('_wheel'):
                from wheel_visuals import render as render_wheel
                corner=comp['MvpRole'].removesuffix('_wheel').upper()
                flex,wheel_render[owner]=render_wheel(part,corner,meshes[owner],names,comp.get('WheelVisualRoles'))
                part['flexbodies'].extend(flex)
            elif (comp.get('RigidAppearance') or owner in graph.fixed_attachment_contract
                  or graph.reports.get(owner,{}).get('allocation_method')=='hardpoint_lumped'):
                from rigid_visuals import render as render_rigid
                render_owner=comp['VisualParentId'] if visual(comp) else owner
                meshes[owner],_=render_rigid(render_owner,part,graph.mass_allocations,meshes[owner],names)
            else:part['flexbodies'].extend([[name,bindings[owner],[]] for name in names])
        component_meshes[owner]=names
        with tempfile.TemporaryDirectory(prefix='vehicle-mesh-',dir=output.parent) as mesh_scratch:
            path=Path(mesh_scratch)/'mesh.dae';write_dae(path,[(item|{'Id':names[i]},tris) for i,(item,tris) in enumerate(meshes[owner])])
            contents[prefix+owner+'.dae']=path.read_bytes().replace(b'mochi_frame_material',(model+'__template_material').encode())
            cad_materials.update(dae_materials(contents[prefix+owner+'.dae'],prefix))
            contents.update({prefix+name:data for name,data in dae_texture_assets(path).items()})
    materials=read_bytes(contents[prefix+'main.materials.json']);name=model+'__template_material'
    materials[name]=dict(name=name,mapTo=name,**{'class':'Material'},Stages=[dict(baseColorFactor=[.4,.55,.65,1],roughnessFactor=.6)],doubleSided=True,version=1.5)
    materials.update(cad_materials)
    contents[prefix+'main.materials.json']=canonical(materials);contents[prefix+jbeam]=canonical({model:part})
    nodes={name:dict(position=v['position'],mass_kg=v['options']['nodeWeight'],component=graph.owners[name]) for name,v in graph.nodes.items()}
    mass=sum(v['mass_kg'] for v in nodes.values())+sum(w['wheel_mass_kg'] for w in wheels.values())
    expected=sum(c.read_geometry(comp)[1][0] for comp in project['Components'])
    numerical_mass=graph.numerical_mass
    if abs(mass-expected-numerical_mass['added_mass_kg'])>max(.005,expected*1e-5):raise ValueError(f'Physical component mass accounting differs: {mass:.9g} vs CAD {expected:.9g} plus declared numerical support mass')
    ref=part['refNodes'][1][0];minimum=min(definition['hardpoints'][corner]['hub'][2]-definition.get('parameters',{}).get('tire_radius_m',.28) for corner in wheels)
    manifest=dict(kind='exported_vehicle',version=1,capabilities=['structure','vehicle','mounts'],model=model,main_part=model,main_jbeam=jbeam,config='base.pc',
                  vehicle_directory='vehicles/'+model,nodes=nodes,explicit_beams=len(beam_table(part)),chassis_nodes=graph.frame_ids,fixed_nodes=[],
                  wheels=wheels,expected_wheel_names=list(wheels),allows_generated_wheel_graph=True,expected_dry_mass_kg=mass,cad_dry_mass_kg=expected,numerical_mass=numerical_mass,spawn_z=.06+nodes[ref]['position'][2]-minimum,
                  device_contract=devices,joints=graph.joints,mounts=graph.mounts,component_parts={v['Id']:model for v in project['Components']},component_meshes=component_meshes,render_bindings=bindings,
                  required_controllers={row[0]:dict(region_count=len(row[1]['regions'])) for row in original_controllers if row[0]=='cadSkin'},
                  torsionbars=part.get('torsionbars',[])[1:],collision_policy=graph.collision_policy,
                  component_reports=graph.reports,connection_budget=graph.connection_budget,fixed_attachment_contract=graph.fixed_attachment_contract,rigid_refits=getattr(graph,'rigid_refits',{}),frame_locator_conditioning=getattr(graph,'frame_locator_conditioning',{}),geometry_inputs_sha256=inputs,project_fingerprint=c.fingerprint(project),
                  mass_allocations=graph.mass_allocations,joint_refits=graph.joint_refits,shaft_chains=graph.shaft_chains,component_roles={v['Id']:v.get('MvpRole') for v in project['Components']},
                  coilover_render=coilover_render,coilover_inputs=coilover_inputs,wheel_render=wheel_render,representation=representation_report,
                  steering_contract=getattr(graph,'steering_contract',None),release_audit=getattr(graph,'release_audit',None),frame_reference=getattr(graph,'frame_reference',{}),alignment=getattr(graph,'alignment',{}),
                  vehicle_template_selection=project['MvpTemplates'],template_sha256=__import__('hashlib').sha256(template_bytes).hexdigest(),template_definition=definition,kinematics=kinematics,
                  frame_calibration=dict(qualification_status=record.get('qualification_status','diagnostic'),
                      local_mount_reference_qualified=record.get('calibration',{}).get('local_mount_reference_qualified'),
                      limitations=record.get('limitations',[])),
                  limitations=['Synthetic/provisional hardware parameters; native acceptance does not establish real vehicle performance or fracture behavior.',
                               graph.collision_policy['limitation'],
                               'Slender locating rods, coilovers and articulated halfshafts use endpoint mass approximations. Suspension arms default to mechanical hardpoints only; consult component reports for CAD COM/inertia approximation errors.',
                               'Translating rack uses provisional rail stiffness and actuator force; verify native motion before qualification.' if definition.get('steering') else
                               'Steering uses equivalent variable-length tie actuators.'])
    if any(k in definition.get('parameters',{}) for k in ('wishbone_frequency_hz','wishbone_damping_budget','wishbone_shared_edge_fit','numerical_step_limit','coupled_front_frequency_hz','conditioned_frame_frequency_hz','front_load_path_frequency_hz','frame_pivot_priority')):
        from numerical_revision import apply_conditioning
        apply_conditioning(part,manifest,definition['parameters'].get('wishbone_frequency_hz',400.),definition['parameters'].get('wishbone_frequency_members','all'),definition['parameters'].get('frame_pivot_priority',1.),definition['parameters'].get('conditioned_frame_frequency_hz'),definition['parameters'].get('front_load_path_frequency_hz'))
        contents[prefix+jbeam]=canonical({model:part})
    if 'frame_refinement_frequency_hz' in definition.get('parameters',{}):
        from numerical_revision import apply_conditioning
        apply_conditioning(part,manifest,definition['parameters'].get('wishbone_frequency_hz',400.),frame_priority=definition['parameters'].get('frame_refinement_pivot_priority',1.),frame_frequency=definition['parameters']['frame_refinement_frequency_hz'],frame_only=True)
        contents[prefix+jbeam]=canonical({model:part})
    if 'fixed_damping_step_limit' in definition.get('parameters',{}):
        from fixed_strain_damping import apply as apply_fixed_damping
        apply_fixed_damping(part,manifest,definition['parameters']['fixed_damping_step_limit'])
        contents[prefix+jbeam]=canonical({model:part})
    if 'rigid_stiffness_growth_factor' in definition.get('parameters',{}):
        from monotone_rigidity import apply as apply_stiffness_growth
        apply_stiffness_growth(part,manifest,definition['parameters']['rigid_stiffness_growth_factor'],definition['parameters'].get('rigid_stiffness_growth_limit',3.6),definition['parameters'].get('rigid_stiffness_growth_selection','front'))
        contents[prefix+jbeam]=canonical({model:part})
    if 'wishbone_filtered_damping_ratio' in definition.get('parameters',{}):
        from filtered_strain_damping import apply as apply_strain_damping
        apply_strain_damping(part,manifest,definition['parameters']['wishbone_filtered_damping_ratio'],definition['parameters'].get('wishbone_damping_cutoff_hz',25.),definition['parameters'].get('filtered_strain_step_limit',3.2))
        contents[prefix+jbeam]=canonical({model:part})
    if 'wishbone_angular_ratio' in definition.get('parameters',{}):
        from angular_arms import apply as apply_angular_arms
        apply_angular_arms(part,manifest,definition['parameters']['wishbone_angular_ratio'],definition['parameters'].get('wishbone_angular_mode','parallel'),definition['parameters'].get('wishbone_angular_members','all'))
        contents[prefix+jbeam]=canonical({model:part})
    if 'brake_reaction_hardpoint_corners' in definition.get('parameters',{}):
        from brake_reaction import apply as apply_brake_routing
        apply_brake_routing(part,manifest,definition['parameters']['brake_reaction_hardpoint_corners'],definition['parameters'].get('brake_reaction_inertia_fraction',.95))
        contents[prefix+jbeam]=canonical({model:part})
    rigidity_plan_path=definition.get('parameters',{}).get('rigidity_mass_plan_path')
    if rigidity_plan_path:
        from rigidity_mass_plan import apply as apply_rigidity_mass
        rigidity_plan_bytes=Path(rigidity_plan_path).read_bytes()
        apply_rigidity_mass(part,manifest,json.loads(rigidity_plan_bytes),definition['parameters'].get('rigidity_mass_added_limit_kg',30.))
        numerical_mass=manifest['numerical_mass'];wheels=manifest['wheels']
        contents[prefix+jbeam]=canonical({model:part})
    if 'wheel_support_reuse_kg' in definition.get('parameters',{}):
        from wheel_support_reuse import apply as apply_wheel_support_reuse
        apply_wheel_support_reuse(part,manifest,definition['parameters']['wheel_support_reuse_kg'])
        numerical_mass=manifest['numerical_mass'];wheels=manifest['wheels']
        contents[prefix+jbeam]=canonical({model:part})
    provenance={'frame-receipt.json':receipt.read_bytes(),'frame-source.jbeam':frame_source,
                'template.json':template_bytes}
    if rigidity_plan_path:provenance['rigidity-mass-plan.json']=rigidity_plan_bytes
    for owner,report in graph.reports.items():
        if report.get('allocation_method')=='hardpoint_lumped':
            manifest['limitations'].append(f"{owner}: mechanical hardpoints retain {report['target_mass_kg']:.6f} kg CAD arm mass before numerical support additions; COM error {report['com_error_m']*1000:.3f} mm, inertia error {report['inertia_relative_error']:.1%}. Mass moments are approximate and not qualified.")
    manifest['limitations'].append('Spring preload is calculated automatically from assembled support loads. Coilover free length and installed preload are not supplied; ride height and corner weights remain provisional.')
    if any(w['ride_reference']['kind']=='level_axle_plane' for w in wheels.values()):
        manifest['limitations'].append('Automatic preload uses a common left/right hub height on each axle. The free CAD mating pose is retained for geometry, not used as four independent loaded ride positions. Without an explicit axle ride height, the mean captured hub height is a provisional reference; tie lengths and alignment are unchanged.')
    missing_springs=[corner for corner,w in wheels.items() if not w.get('coilover_spring')]
    if missing_springs:
        manifest['limitations'].append('Automatic spring-rate fallback is active for '+', '.join(missing_springs)+'. Enter the real spring settings before physical qualification; opposite-side settings are not inferred.')
    if manifest['frame_locator_conditioning'].get('patches'):
        manifest['limitations'].append(manifest['frame_locator_conditioning']['scope'])
        manifest['frame_calibration'].update(qualification_status='diagnostic',local_mount_reference_qualified=False)
    if manifest['frame_reference']:
        manifest['limitations'].append(manifest['frame_reference']['scope'])
        manifest['frame_calibration'].update(qualification_status='replaced_by_rigid_reference',local_mount_reference_qualified=False)
    if definition.get('diagnostic_assumptions'):
        manifest['limitations'].extend(definition['diagnostic_assumptions'])
        manifest['diagnostic_scope']='Initial CAD vehicle integration; physical qualification is pending'
    if numerical_mass['added_mass_kg']:
        manifest['limitations'].append(f"Numerical support mass adds {numerical_mass['added_mass_kg']:.6f} kg beyond CAD mass. Mass/COM/inertia and suspension loading are therefore not material-equivalent to CAD.")
    if definition.get('fixed_shafts'):
        manifest['limitations'].append('Explicitly fixed CAD shaft sections retain their rigid placement and mass; ideal powertrain transfers torque without shaft spin animation or articulated shaft failure.')
    if definition.get('fixed_panel_components'):
        manifest['limitations'].append('Listed panel attachments are rigid for this integration preview. Panel breakaway is disabled; saved native bolt definitions are not qualified by this build.')
    for name in record.get('calibration_files_sha256',{}):provenance[name]=(receipt.parent/name).read_bytes()
    if inputs!=geometry_inputs(project):raise ValueError('CAD changed during vehicle generation')
    for comp in project['Components']:
        if comp['Id'] in coilover_inputs and coilover_visuals.inputs(comp)[1]!=coilover_inputs[comp['Id']]:raise ValueError('Coilover appearance changed during packaging')
    if template_bytes!=template_input(project)[1] or project_fingerprint!=c.fingerprint(read(project_path)):
        raise ValueError('Project/template changed during vehicle generation')
    if completed_build(receipt)[0]!=record:raise ValueError('Calibrated frame changed during vehicle generation')
    if any(p.read_bytes()!=implementation[name] for name,p in sources.items()):raise ValueError('Generator implementation changed during vehicle generation')
    if rigidity_plan_path and Path(rigidity_plan_path).read_bytes()!=rigidity_plan_bytes:raise ValueError('Numerical mass plan changed during generation')
    for name,data in implementation.items():provenance['generator/'+name]=data
    for report in scratch.glob('*/report.json'):provenance['components/'+report.parent.name+'.json']=report.read_bytes()
    origin='CAD geometry with reported numerical support mass and provisional rigid components' if numerical_mass['added_mass_kg'] else 'Native CAD frame calibration with CAD-mass template components'
    if manifest['frame_reference']:origin+='; numerical rigid-frame reference'
    result=package_revision(output,project,manifest,contents,provenance,receipt,origin)
    if not save_report:
        if scratch.resolve().parent!=output.parent or scratch.name!=output.name+'.generation':raise ValueError('Unsafe diagnostic cleanup path')
        shutil.rmtree(scratch)
    emit('Vehicle generation finished',completed=1,total=1,outcome='succeeded')
    return result


def read_bytes(value):return json.loads(value)
