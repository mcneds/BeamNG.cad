"""Worker entry point for previewing and packaging owned components."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import components as c
from build_static_frame import completed_build, digest, validate_package
from package_identity import layout, validate_identity
from prepare_frame import dae_materials
from appearance_textures import dae_texture_assets
from frame_harness.build import node_table, beam_table
from frame_harness.cad import read_bodies
import numpy as np


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def progress(phase,completed,total):print('CAD_PROGRESS '+json.dumps(dict(phase=phase,completed=completed,total=total)),flush=True)


def geometry_inputs(project):
    result={}
    physical=list(project['Components'])
    if (project.get('JointWorkspace') or {}).get('Mode')=='authored':physical+=project['JointWorkspace'].get('Members',[])
    for component in physical:
        root=Path(component['GeometryDirectory']).resolve();geometry=read(root/'geometry.json')
        names=['geometry.json']+[v['File'] for v in geometry['Meshes']]
        if (root/'material-snapshot.json').exists():names.append('material-snapshot.json')
        hashes={}
        for name in names:
            path=(root/name).resolve()
            if path.parent!=root:raise ValueError('CAD input escapes its geometry directory')
            hashes[name]=digest(path)
        result[component['Id']]=hashes
    return result


def preview(project_path,component_id,output,cgal=None):
    project=read(project_path);component=next(v for v in project['Components'] if v['Id']==component_id)
    part,report=c.generate_component(component,[a for a in project['Anchors'] if a['ComponentId']==component_id],Path(output),cgal)
    if report.get('qualification')=='visual_only':
        parent=next((v for v in project['Components'] if v['Id']==report['visual_parent']),None)
        if parent is None or c.read_geometry(parent)[1][0]<=0:raise ValueError('Choose an existing physical parent with positive mass for this weightless visual')
    return part,report


def validate_project(project,driveline=None):
    from component_representation import validate
    validate(project,c.read_geometry)
    validate_identity(project['Identity']);seen=set();ids=set()
    from mvp_inventory import configuration
    driveline=project.get('Driveline') or driveline
    _,active_roles,_=configuration(read(HERE/'template_catalog.json'),project|dict(Driveline=driveline))
    drive_owners={e['component'] for table in ('endpoints','shafts','devices') for e in (driveline or {}).get(table,[])}
    for component in project['Components']:
        if component.get('MvpRole') and component['MvpRole'] not in active_roles and component['Id'] not in drive_owners:raise ValueError(component['Name']+': tagged outside the current vehicle setup. Change the setup or revise this assignment before packaging.')
        if component['Id'] in ids:raise ValueError('Duplicate component identity')
        ids.add(component['Id'])
        bodies=set(component['BodyIds'])
        if not bodies or seen&bodies:raise ValueError('Each selected CAD body must have exactly one component owner')
        seen.update(bodies)
    anchors={a['Id']:a for a in project['Anchors']}
    if len(anchors)!=len(project['Anchors']):raise ValueError('Duplicate anchor identity')
    for anchor in anchors.values():
        if anchor['ComponentId'] not in ids or anchor.get('Status')!='resolved':raise ValueError('Unresolved or orphaned mounting point: '+anchor['Name'])
        if anchor.get('GeneratedSource')=='auto_connect':
            from auto_connect import geometry_hash
            owner=next(c for c in project['Components'] if c['Id']==anchor['ComponentId'])
            if anchor.get('GeometryHash')!=geometry_hash(owner):raise ValueError('Auto-connect mounting geometry changed; preview again: '+anchor['Name'])
    for connection in project['Connections']:
        if connection['AnchorA'] not in anchors or connection['AnchorB'] not in anchors:raise ValueError('Connection has a missing mounting point')
    if len({v['Id'] for v in project['Connections']})!=len(project['Connections']):raise ValueError('Connections need independent identities')
    if len({tuple(sorted((v['AnchorA'],v['AnchorB']))) for v in project['Connections']})!=len(project['Connections']):raise ValueError('Duplicate connection between the same mounting points')


def verify_current_frame(component,record):
    if not record.get('calibration'):raise ValueError('Select a CAD-calibrated frame package first')
    source=Path(record['calibration']['generation'])/'source'
    original=source/'cad_source.dae'
    expected=record['calibration']['input_sha256'].get('cad_source.dae')
    if not original.is_file() or digest(original)!=expected:raise ValueError('Frame CAD snapshot is unavailable or changed; regenerate the calibrated frame')
    original_bodies={b.name:b for b in read_bodies(original)}
    meshes,_,geometry=c.read_geometry(component)
    if set(original_bodies)!={r['Id'] for r,_ in meshes}:raise ValueError('Frame ownership changed; recalibrate the frame first')
    for record,triangles in meshes:
        body=original_bodies[record['Id']]
        vertices=body.vertices[body.faces]
        if triangles.shape!=vertices.shape or not np.allclose(triangles,vertices,atol=2e-8,rtol=1e-7):raise ValueError('Frame geometry moved or changed; recalibrate the frame first')
    native=read(Path(component['GeometryDirectory'])/'material-snapshot.json')
    previous=read(source/'material-snapshot.json')
    if native!=previous:raise ValueError('Frame material assignments changed; recalibrate the frame first')


def build(project_path,output,cgal=None):
    project=read(project_path);validate_project(project);output=Path(output).resolve()
    if project.get('Driveline'):raise ValueError('Use vehicle generation for a driveline graph; a component-only package cannot preserve its torque topology')
    if output.exists():raise FileExistsError('Use a fresh component build directory')
    frame=next((v for v in project['Components'] if v['Template']=='calibrated_frame'),None)
    if frame is None:raise ValueError('Add the calibrated frame before packaging components')
    if sum(v['Template']=='calibrated_frame' for v in project['Components'])!=1:raise ValueError('Select exactly one calibrated frame')
    receipt=Path(project.get('FrameBuildReceipt') or project.get('LastBuildReceipt',''))
    record,archive=completed_build(receipt)
    if record.get('identity')!=project['Identity']:raise ValueError('Package this project\'s calibrated frame first')
    inputs=geometry_inputs(project)
    verify_current_frame(frame,record)
    output.mkdir();model=project['Identity']['namespace'];vehicle=output/'vehicles'/model;vehicle.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            target=(output/name).resolve()
            if not target.is_relative_to(vehicle):raise ValueError('Frame package escapes vehicle directory')
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(name))
    _,_,main_jbeam,_=layout(record);frame_parts=read(vehicle/main_jbeam)
    provenance=output/'provenance';provenance.mkdir()
    shutil.copy2(receipt,provenance/'frame-receipt.json')
    shutil.copy2(vehicle/main_jbeam,provenance/'frame-source.jbeam')
    for name in [*record.get('calibration_files_sha256',{}),*(['identity/source.jbeam'] if record.get('identity_export') else [])]:
        source=(receipt.parent/name).resolve();target=(provenance/name).resolve()
        if not source.is_relative_to(receipt.parent) or not target.is_relative_to(provenance):raise ValueError('Invalid frame provenance path')
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    provenance_files={p.relative_to(output).as_posix():digest(p) for p in provenance.rglob('*') if p.is_file()}
    if len(frame_parts)!=1:raise ValueError('Select a frame-only package as the component foundation')
    main=next(iter(frame_parts.values()));parts={frame['Id']:main};reports={};total=len(project['Components'])
    from component_representation import physical_project,refit_existing_part
    physical,representation_report=physical_project(project,c.read_geometry)
    physical_components={v['Id']:v for v in physical['Components']}
    if physical_components[frame['Id']].get('_VisualMass'):
        representation_report['host_mass_fits']={frame['Id']:refit_existing_part(main,c.read_geometry(physical_components[frame['Id']])[1],physical_components[frame['Id']]['_VisualMass'])}
    # Declare a whole-component render binding when creating the physical
    # baseline. Later appearance revisions never need to edit node groups.
    frame_nodes=node_table(main)
    for row in main['nodes'][1:]:
        if isinstance(row,list):
            if not isinstance(row[-1],dict):row.append({})
            existing=frame_nodes[row[0]]['options'].get('group',[])
            if isinstance(existing,str):existing=[existing]
            row[-1]['group']=list(dict.fromkeys([*existing,model+'__frame_visual']))
    for i,component in enumerate(project['Components'],1):
        progress('Generate components',i-1,total)
        if component['Id']==frame['Id']:continue
        effective=physical_components.get(component['Id'],component)
        part,report=c.generate_component(effective,[a for a in project['Anchors'] if a['ComponentId']==component['Id']],output/'components'/component['Id'],cgal)
        parts[component['Id']]=part;reports[component['Id']]=report
    visual_groups=c.bind_weightless_visuals(parts,reports)
    progress('Mounting and stability',0,1)
    groups,screen=c.attach(parts,project['Anchors'],project['Connections'],project_assembly=True)
    # Resolve the full graph before assigning file/slot names, so named anchors
    # are independent of project namespace and generated hull node numbers.
    from package_identity import remap
    mapping={}
    mapping.update({g:model+'__'+g for g in visual_groups})
    for owner,part in parts.items():
        if owner==frame['Id']:continue
        mapping[owner]=model+'__'+owner;mapping[owner+'_structure']=model+'__'+owner+'_structure'
        mapping.update({n:model+'__'+n for n in node_table(part)})
        for row in part.get('flexbodies',[])[1:]:
            if isinstance(row,list):mapping[row[0]]=model+'__'+row[0]
        for row in part.get('props',[])[1:]:
            if isinstance(row,list):mapping[row[1]]=model+'__'+row[1]
    for group in groups:
        if group['group']:mapping[group['group']]=model+'__'+group['group']
    main['slots']=[['type','default','description']]+[[model+'__'+v['Id'],model+'__'+v['Id'],v['Name']] for v in project['Components'] if v['Id']!=frame['Id']]
    part_names={frame['Id']:model};frame_files=[];cad_materials={}
    for component in project['Components']:
        owner=component['Id'];part=remap(parts[owner],mapping,model,model)
        name=model if owner==frame['Id'] else model+'__'+owner;part_names[owner]=name
        c.write(vehicle/(name+'.jbeam'),{name:part})
        if owner!=frame['Id']:
            import xml.etree.ElementTree as ET
            root=ET.parse(output/'components'/owner/'component.dae')
            local=dict(mapping)
            for element in root.iter():
                for key in ('id','name','symbol','material'):
                    value=element.get(key)
                    if value:local.setdefault(value,model+'__'+owner+'__'+value)
            local['mochi_frame_material']=model+'__component_material'
            for element in root.iter():
                for key,value in list(element.attrib.items()):
                    if key in ('id','name','symbol','material'):element.set(key,local.get(value,value))
                    elif value.startswith('#'):element.set(key,'#'+local.get(value[1:],value[1:]))
                if element.tag.endswith('}init_from') and element.text in local:element.text=local[element.text]
            root.write(vehicle/(name+'.dae'),encoding='utf-8',xml_declaration=True)
            for asset,data in dae_texture_assets(output/'components'/owner/'component.dae').items():(vehicle/asset).write_bytes(data)
            cad_materials.update(dae_materials((vehicle/(name+'.dae')).read_bytes(),'vehicles/'+model))
    # Every component uses the generator's neutral visual material with a project namespace.
    material_name=model+'__component_material'
    materials=read(vehicle/'main.materials.json');materials[material_name]={'name':material_name,'mapTo':material_name,'class':'Material','Stages':[{'baseColorFactor':[.45,.48,.52,1]}],'doubleSided':True,'version':1.5}
    materials.update(cad_materials)
    c.write(vehicle/'main.materials.json',materials)
    nodes={};explicit=0
    for owner,part in parts.items():
        for n,value in node_table(part).items():nodes[mapping.get(n,n)]={'position':value['position'],'mass_kg':value['options']['nodeWeight'],'component':owner}
        explicit+=len(beam_table(part))
    groups=[g|{'group':mapping.get(g['group'],g['group']),'edges':[[mapping.get(n,n) for n in edge] for edge in g['edges']]} for g in groups]
    minimum=min(n['position'][2] for n in nodes.values())
    expected_mass=sum(c.read_geometry(comp)[1][0] for comp in project['Components'])
    actual_mass=sum(n['mass_kg'] for n in nodes.values())
    if abs(actual_mass-expected_mass)>max(.005,expected_mass*1e-5):raise ValueError('Physical component mass differs from the requested CAD/custom mass')
    ref=main['refNodes'][1][0]
    files={p.relative_to(output).as_posix():digest(p) for p in vehicle.rglob('*') if p.is_file()}
    manifest={'kind':'exported_vehicle','version':1,'capabilities':['structure','mounts'],'model':model,'main_part':model,'main_jbeam':main_jbeam,'config':'base.pc','vehicle_directory':'vehicles/'+model,
              'nodes':nodes,'explicit_beams':explicit,'fixed_nodes':[],'chassis_nodes':list(node_table(main)),
              'expected_dry_mass_kg':sum(n['mass_kg'] for n in nodes.values()),'expected_wheel_names':[],'wheels':{},
              'spawn_z':.1+nodes[ref]['position'][2]-minimum,'files':files,'mounts':groups,'component_parts':part_names,
              'project_fingerprint':c.fingerprint(project),'geometry_inputs_sha256':inputs,'frame_receipt':str(receipt),'frame_zip_sha256':record['zip_sha256'],
              'screening':screen,'component_reports':reports,'representation':representation_report,'component_roles':{v['Id']:v.get('MvpRole') for v in project['Components']},'vehicle_template_selection':project.get('MvpTemplates') or [],
              'provenance_files':provenance_files,'limitations':['Component stiffness and joint failure loads are prototype tuning, not calibrated rupture behavior.']}
    if inputs!=geometry_inputs(project) or c.fingerprint(read(project_path))!=c.fingerprint(project):raise ValueError('CAD inputs changed during generation; use a fresh build')
    _,current_archive=completed_build(receipt)
    if digest(current_archive)!=record['zip_sha256']:raise ValueError('Frame package changed during generation')
    from vehicle_revisions import physical_snapshot
    snapshot=physical_snapshot({name:(output/name).read_bytes() for name in files},manifest)
    manifest['physics_sha256']=snapshot['sha256'];manifest['physics_origin']='CAD-calibrated frame and provisional component physics'
    c.write(output/'physics.snapshot.json',snapshot)
    c.write(output/'manifest.json',manifest);c.write(output/'project.snapshot.json',project)
    target=output/'work/dist'/ (model+'.zip');target.parent.mkdir(parents=True)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for name in files:z.write(output/name,name)
    result={'format':'truemesh-static-frame-build','version':2,'status':'succeeded','identity':project['Identity'],
            'zip_file':target.relative_to(output).as_posix(),'zip_sha256':digest(target),'component_files':files,
            'component_manifest_sha256':digest(output/'manifest.json'),'component_provenance_sha256':provenance_files,'generation_status':'succeeded','recording_status':'not_run','qualification_status':'diagnostic',
            'parent_receipt':str(receipt),'limitations':manifest['limitations']}
    c.write(output/'static_frame_build.json',result)
    completed_build(output/'static_frame_build.json');progress('Package components',1,1)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['preview','build','suggest','verify','inventory','appearance','vehicle','mount-plan','fork-template','properties','joint-scan','joint-definition','auto-connect','acknowledge-mass','frame-current','driveline-check','driveline-preset'])
    parser.add_argument('--corner-inset',type=float,default=.01);parser.add_argument('--support-distance',type=float,default=.05)
    parser.add_argument('--project',type=Path);parser.add_argument('--component');parser.add_argument('--output',type=Path);parser.add_argument('--cgal')
    parser.add_argument('--source-project',type=Path)
    parser.add_argument('--mounts-only',action='store_true',help='Verify attachments, including release, on either a component or complete vehicle package')
    parser.add_argument('--manifest',type=Path);parser.add_argument('--game');parser.add_argument('--profile');parser.add_argument('--repeats',type=int,default=3);parser.add_argument('--cancel-file');parser.add_argument('--save-report',action='store_true')
    args=parser.parse_args()
    if args.cancel_file:os.environ['BEAMNG_CAD_CANCEL']=args.cancel_file
    if args.action=='verify':
        if not args.manifest or not args.game or not args.profile:parser.error('verify requires --manifest, --game and --profile')
        completed_build(args.manifest.parent/'static_frame_build.json')
        is_vehicle='vehicle' in read(args.manifest).get('capabilities',[])
        if is_vehicle and not args.mounts_only:
            from frame_harness.vehicle import run_acceptance
            from frame_harness.models import HarnessProject
            project=HarnessProject(game=Path(args.game),userpath=Path(args.profile),source=args.manifest.parent,runs=args.manifest.parent/'tests')
            result=run_acceptance(args.manifest,project=project,save_report=args.save_report)
            from verification_receipts import record_vehicle_check
            record_vehicle_check(args.manifest,args.manifest.parent/'tests/acceptance.json','acceptance')
            if result['status']!='passed':raise ValueError('Vehicle acceptance failed; inspect tests/acceptance.json')
            return
        if args.project and not read(args.manifest).get('physics_sha256'):
            current=read(args.project);manifest=read(args.manifest)
            if c.fingerprint(current)!=manifest.get('project_fingerprint') or geometry_inputs(current)!=manifest.get('geometry_inputs_sha256'):
                raise ValueError('CAD geometry, materials or resolved mounting points changed. Package the current components before verification.')
        if args.repeats<1 or args.repeats>10:parser.error('repeats must be between 1 and 10')
        from frame_harness.component_tests import verify
        result=verify(args.manifest,args.game,args.profile,args.repeats,save_report=args.save_report)
        receipt=args.manifest.parent/'static_frame_build.json'
        record,_=completed_build(receipt)
        record.update(mounting_recording_status=result['recording_status'],mounting_qualification_status=result['qualification_status'],
                      mounting_verification_sha256=digest(args.manifest.parent/'component-verification.json'))
        if not is_vehicle:record.update(recording_status=result['recording_status'],qualification_status=result['qualification_status'])
        c.write(receipt,record)
        if result['status']!='passed':raise ValueError('Component verification failed; inspect component-verification.json')
        return
    if not args.project or not args.output:parser.error('Generation requires --project and --output')
    if args.action=='frame-current':
        project=read(args.project)
        from full_vehicle_worker import definition_for_project
        from vehicle_templates import frame_mount_plan
        # Definition errors must be resolved before spending time on calibration.
        plan=frame_mount_plan(definition_for_project(project),project['Components'])
        try:
            record,archive=completed_build(Path(project.get('FrameBuildReceipt') or ''))
            frame=next(v for v in project['Components'] if v['Template']=='calibrated_frame');verify_current_frame(frame,record)
            if record['identity']!=project['Identity']:raise ValueError('Frame belongs to another project')
            model=project['Identity']['namespace'];_,_,name,_=layout(record)
            with zipfile.ZipFile(archive) as z:part=next(iter(json.loads(z.read('vehicles/'+model+'/'+name)).values()))
            patches=part.get('cadMountPatches',{})
            if set(plan)!=set(patches):raise ValueError('Mount plan changed')
            for key,item in plan.items():
                actual=patches[key]
                if actual.get('mode','short')!=item['mode'] or not np.allclose(actual['position'],item['position'],rtol=0,atol=1e-7):raise ValueError('Mount location/representation changed')
                if item['mode']=='short' and abs(actual.get('attachment_length_m',.006)-item.get('attachment_length_m',.006))>1e-9:raise ValueError('Connector length changed')
            c.write(args.output,dict(Current=True,Reason='Current frame and mounting plan'))
        except (OSError,ValueError,KeyError) as error:c.write(args.output,dict(Current=False,Reason=str(error)))
    elif args.action=='acknowledge-mass':
        from component_representation import acknowledgement,visual
        project=read(args.project);component=next(v for v in project['Components'] if v['Id']==args.component)
        if not visual(component) or c.read_geometry(component)[1][0]!=0:raise ValueError('Only explicit zero-mass visual components need acknowledgement')
        c.write(args.output,dict(Hash=acknowledgement(component)))
    elif args.action=='auto-connect':
        from auto_connect import proposals
        result=proposals(read(args.project),args.corner_inset,args.support_distance)
        preview=Path(str(args.output)+'.previews');preview.mkdir(exist_ok=True)
        for row in result['Rows']:
            vertices=[];faces=[]
            for site in row.get('Preview',[]):
                p=np.array(site['position']);n=np.array(site['normal']);end=np.array(site['support'])
                for axis in np.eye(3):
                    start=len(vertices);vertices.extend([p-axis*.004,p+axis*.004,p+np.roll(axis,1)*.0005]);faces.append([start,start+1,start+2])
                start=len(vertices);vertices.extend([p,end if np.linalg.norm(end-p)>.001 else p+n*.025,p+np.array([.001,.001,.001])]);faces.append([start,start+1,start+2])
            if vertices:
                path=preview/(hashlib.sha256(row['Id'].encode()).hexdigest()[:16]+'.off');c.write_off(path,vertices,faces);row['PreviewFile']=str(path)
        c.write(args.output,result)
    elif args.action=='joint-scan':
        from joint_authoring import proposals
        c.write(args.output,proposals(read(args.project).get('JointWorkspace') or {}))
    elif args.action=='driveline-preset':
        from driveline_presets import from_project
        c.write(args.output,from_project(read(args.project)))
    elif args.action=='driveline-check':
        from driveline import resolve,validate
        project=read(args.project);spec=resolve(project)
        if not spec:raise ValueError('Create a driveline graph first')
        result=validate(spec,project)
        c.write(args.output,dict(status='passed',device_count=len(result['devices']),shaft_count=len(result['shafts']),routes=result['routes']))
    elif args.action=='joint-definition':
        from joint_authoring import definition
        c.write(args.output,definition(read(args.project)))
    elif args.action=='fork-template':
        from vehicle_revisions import fork_baseline
        project=read(args.project);fork_baseline(project,project['PhysicsTemplateReceipt'],args.output)
    elif args.action=='vehicle':
        from full_vehicle_worker import build as build_vehicle
        build_vehicle(args.project,args.output,args.cgal,args.save_report)
    elif args.action=='mount-plan':
        from full_vehicle_worker import definition_for_project
        from vehicle_templates import frame_mount_plan
        project=read(args.project)
        c.write(args.output,frame_mount_plan(definition_for_project(project),project['Components']))
    elif args.action=='properties':
        from property_revisions import recalibrate_component
        recalibrate_component(read(args.project),args.component,args.output)
        progress('Recalibrate component properties',1,1)
    elif args.action=='appearance':
        from vehicle_revisions import replace_appearance
        project=read(args.project)
        owners=[args.component] if args.component else [c['Id'] for c in project['Components'] if c.get('AppearancePackageState') in ('pending','failed')]
        for component in project['Components']:
            if component['Id'] in owners:
                component['AppearancePackageState']='current'
                component['AppearancePackageError']=None
        replace_appearance(project,owners,args.output)
        progress('Replace appearance',1,1)
    elif args.action=='inventory':
        from mvp_inventory import inventory
        c.write(args.output,inventory(read(args.project),args.source_project or args.project))
        print('CAD inventory: '+str(args.output),flush=True)
    elif args.action=='build':build(args.project,args.output,args.cgal)
    elif args.action=='preview':preview(args.project,args.component,args.output,args.cgal)
    else:
        component=next(v for v in read(args.project)['Components'] if v['Id']==args.component)
        meshes,moments,_=c.read_geometry(component);c.write(args.output,c.suggest(np.concatenate([t for _,t in meshes]),moments[0]))


if __name__=='__main__':main()
