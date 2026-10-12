"""Immutable vehicle revisions. Render replacements never invoke a physics generator.

Unknown JBeam sections and every runtime Lua file are physical by default. This
deliberately fails closed when a future generator adds a controller or device.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import numpy as np
import components as c
import coilover_visuals
from build_static_frame import completed_build, digest
from prepare_frame import read_stl, write_dae, dae_materials
from appearance_textures import mesh_uvs, dae_texture_assets
from frame_harness.build import node_table

VISUAL_SECTIONS = frozenset(('information', 'flexbodies', 'props', 'cameras', 'cameraExternal', 'cameraChase'))
PHYSICAL_MANIFEST = ('nodes', 'explicit_beams', 'chassis_nodes', 'wheels', 'mounts',
                     'expected_dry_mass_kg', 'expected_wheel_names', 'device_contract',
                     'joints', 'vehicle_template_selection', 'fixed_nodes', 'mass_allocations', 'template_definition', 'required_controllers', 'torsionbars', 'shaft_chains', 'fixed_attachment_contract', 'numerical_mass', 'cad_dry_mass_kg', 'frame_locator_conditioning', 'frame_reference', 'alignment', 'wheel_support_reuse')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def physical_snapshot(contents, manifest):
    parts = {}
    runtime = {}
    for name, data in sorted(contents.items()):
        if name.endswith('.jbeam'):
            for part_id, part in json.loads(data).items():
                if part_id in parts:
                    raise ValueError('Duplicate physical part: ' + part_id)
                parts[part_id] = {key: value for key, value in part.items() if key not in VISUAL_SECTIONS}
        elif name.endswith('.lua') or name.endswith('.pc'):
            runtime[name] = hashlib.sha256(data).hexdigest()
    if not parts:
        raise ValueError('Vehicle has no physical graph')
    value = dict(version=1, parts=parts, runtime=runtime,
                 contract={key: copy.deepcopy(manifest[key]) for key in PHYSICAL_MANIFEST if key in manifest})
    return dict(value=value, sha256=hashlib.sha256(canonical(value)).hexdigest())


def load_baseline(receipt):
    receipt = Path(receipt).resolve()
    record, archive = completed_build(receipt)
    manifest_path = receipt.parent / 'manifest.json'
    if not record.get('component_files') or not manifest_path.is_file():
        raise ValueError('Select a packaged component or complete vehicle as the appearance baseline')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    with zipfile.ZipFile(archive) as z:
        contents = {name: z.read(name) for name in z.namelist()}
    snapshot = physical_snapshot(contents, manifest)
    if manifest.get('physics_sha256', snapshot['sha256']) != snapshot['sha256']:
        raise ValueError('Physical snapshot differs from the packaged baseline')
    return record, manifest, contents, snapshot


def appearance_meshes(component):
    """Only coordinates are read. Open sheets require neither density nor thickness."""
    root = Path(component.get('AppearanceDirectory') or component['GeometryDirectory']).resolve()
    geometry = json.loads((root / 'geometry.json').read_text(encoding='utf-8-sig'))
    transform = np.asarray(component.get('AppearanceTransform') or np.eye(4), dtype=float).reshape(4, 4)
    if not np.isfinite(transform).all() or not np.allclose(transform[3], [0, 0, 0, 1]):
        raise ValueError('Invalid render alignment')
    if abs(np.linalg.det(transform[:3, :3])) < 1e-9:
        raise ValueError('Render alignment must be invertible')
    meshes = []
    hashes = {'geometry.json': digest(root / 'geometry.json')}
    for item in geometry['Meshes']:
        path = (root / item['File']).resolve()
        if path.parent != root:
            raise ValueError('Appearance file escapes its geometry directory')
        hashes[item['File']] = digest(path)
        triangles = np.asarray(read_stl(path, 'X-ZY'), dtype=float)
        uvs=mesh_uvs(item,triangles)
        if uvs is not None:item=item | {'TextureCoordinates':uvs}
        for group in item.get('AppearanceGroups',[]):
            texture=group['Appearance'].get('TextureFile')
            if texture:hashes['texture:'+texture]=digest(Path(texture))
        if not triangles.size or not np.isfinite(triangles).all():
            raise ValueError('Appearance mesh is empty or nonfinite')
        triangles = triangles @ transform[:3, :3].T + transform[:3, 3]
        if np.linalg.det(transform[:3, :3]) < 0:
            triangles = triangles[:, ::-1]
            if uvs is not None:item=item | {'TextureCoordinates':np.asarray(uvs).reshape(-1,3,2)[:,::-1].reshape(-1,2).tolist()}
        meshes.append((item, triangles))
    if not meshes:
        raise ValueError('Select at least one appearance body')
    return meshes, dict(files=hashes, alignment=transform.tolist())


def binding_groups(part, declared=None):
    groups = {}
    for name, node in node_table(part).items():
        values=node['options'].get('group', [])
        if isinstance(values,str):values=[values]
        for group in values:
            groups.setdefault(group, []).append(node['position'])
    # A baseline can name its render binding explicitly. Legacy components use
    # their existing structure group; never add groups to frozen physical nodes.
    candidates = declared or sorted(groups, key=lambda key: (not key.endswith('_structure'), -len(groups[key]), key))
    wheel_groups={group for row in part.get('pressureWheels',[])[1:] if isinstance(row,list) for group in row[1:3]}
    for group in candidates:
        if group in wheel_groups:return [group]
        points = np.asarray(groups.get(group, []), dtype=float)
        if len(points) >= 4 and np.linalg.matrix_rank(points - points[0], tol=1e-7) == 3:
            return [group]
    raise ValueError('Physical component has no volumetric render binding; regenerate it with an explicit binding')


def package_revision(output, project, manifest, contents, provenance, parent_receipt, physics_origin):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('Use a fresh revision directory')
    # Reserve the unpacked assets plus a worst-case archive, provenance and
    # metadata. NTFS compression may need uncompressed space while a file is
    # open; its final allocation is not a safe packaging-space estimate.
    payload=sum(len(data) for data in contents.values())
    required=int(payload*2.02)+sum(len(data) for data in provenance.values())+64*1024**2
    volume=output.parent
    while not volume.exists():volume=volume.parent
    available=shutil.disk_usage(volume).free
    if available<required:
        raise OSError(28,f'Not enough space to package this vehicle: reserve {required/1024**2:.0f} MiB, available {available/1024**2:.0f} MiB on {volume.anchor}. Free space or choose another build directory.')
    output.mkdir(parents=True)
    for name, data in contents.items():
        path = (output / name).resolve()
        if not path.is_relative_to(output / 'vehicles' / project['Identity']['namespace']):
            raise ValueError('Revision asset escapes its vehicle directory')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for name, data in provenance.items():
        path = (output / 'provenance' / name).resolve()
        if not path.is_relative_to(output / 'provenance'):
            raise ValueError('Invalid provenance path')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = copy.deepcopy(manifest)
    manifest['files'] = {name: digest(output / name) for name in contents}
    manifest['provenance_files'] = {p.relative_to(output).as_posix(): digest(p) for p in (output / 'provenance').rglob('*') if p.is_file()}
    snapshot = physical_snapshot(contents, manifest)
    manifest['physics_sha256'] = snapshot['sha256']
    manifest['physics_origin'] = physics_origin
    manifest['appearance_sha256'] = hashlib.sha256(canonical({n: v for n, v in manifest['files'].items() if not n.endswith(('.jbeam', '.lua', '.pc'))}) +
        canonical({n: {k: {s: p[s] for s in ('flexbodies', 'props') if s in p} for k, p in json.loads(data).items()} for n, data in contents.items() if n.endswith('.jbeam')})).hexdigest()
    c.write(output / 'physics.snapshot.json', snapshot)
    c.write(output / 'manifest.json', manifest)
    c.write(output / 'project.snapshot.json', project)
    target = output / 'work' / 'dist' / (project['Identity']['namespace'] + '.zip')
    target.parent.mkdir(parents=True)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in contents:
            archive.write(output / name, name)
    result = dict(format='truemesh-static-frame-build', version=2, status='succeeded', identity=project['Identity'],
                  zip_file=target.relative_to(output).as_posix(), zip_sha256=digest(target),
                  component_files=manifest['files'], component_manifest_sha256=digest(output / 'manifest.json'),
                  component_provenance_sha256=manifest['provenance_files'], physics_sha256=snapshot['sha256'],
                  generation_status='succeeded', recording_status='not_run', qualification_status='diagnostic',
                  parent_receipt=str(parent_receipt), limitations=manifest.get('limitations', []))
    c.write(output / 'static_frame_build.json', result)
    completed_build(output / 'static_frame_build.json')
    return result


def replace_appearance(project, component_ids, output):
    receipt = Path(project.get('LastBuildReceipt', ''))
    record, manifest, contents, baseline = load_baseline(receipt)
    if project['Identity'] != record['identity']:
        raise ValueError('Import/fork the physical baseline into this project before replacing its appearance')
    components = {item['Id']: item for item in project['Components']}
    if not component_ids or len(set(component_ids)) != len(component_ids):
        raise ValueError('Choose distinct components to replace')
    prefix = 'vehicles/' + manifest['model'] + '/'
    replacements = {};cad_materials={}
    appearance = copy.deepcopy(manifest.get('appearance_inputs', {}))
    scratch = Path(output).with_name(Path(output).name + '.appearance-work')
    if scratch.exists():
        raise FileExistsError('Appearance scratch directory already exists')
    scratch.mkdir(parents=True)
    try:
        for owner in component_ids:
            if owner not in components or owner not in manifest.get('component_parts', {}):
                raise ValueError('Appearance needs an existing stable physical component: ' + owner)
            part_id = manifest['component_parts'][owner]
            matches = [(name, json.loads(data)) for name, data in contents.items()
                       if name.endswith('.jbeam') and part_id in json.loads(data)]
            if len(matches) != 1:
                raise ValueError('Physical part binding is ambiguous')
            name, parts = matches[0]
            part = parts[part_id]
            rigid_appearance=(components[owner].get('RigidAppearance')
                              or manifest.get('component_reports',{}).get(owner,{}).get('allocation_method')=='hardpoint_lumped')
            # Props validate a noncollinear three-node basis in render(); they
            # do not require the volumetric group used by flexbody locators.
            declared=manifest.get('render_bindings', {}).get(owner)
            groups = (declared or []) if rigid_appearance else binding_groups(part, declared)
            split=coilover_visuals.active(components[owner])
            if split:
                meshes,mesh_names,props,flex,source,contract=coilover_visuals.render(components[owner],part,manifest,groups,manifest['model']+'__appearance_'+owner)
                manifest.setdefault('coilover_render',{})[owner]=contract
            else:
                meshes, source = appearance_meshes(components[owner])
                mesh_names = [manifest['model'] + '__appearance_' + owner + '_' + str(i) for i in range(len(meshes))]
                props=[];flex=[[mesh,groups,[]] for mesh in mesh_names]
                role=manifest.get('component_roles',{}).get(owner,'') or ''
                if role.endswith('_wheel'):
                    from wheel_visuals import render as render_wheel
                    flex,contract=render_wheel(part,role.removesuffix('_wheel').upper(),meshes,mesh_names,components[owner].get('WheelVisualRoles'))
                    manifest.setdefault('wheel_render',{})[owner]=contract
                elif rigid_appearance:
                    # Sparse rigid arms lack the surrounding node cloud needed
                    # by flexbody locators. Native props use the existing three
                    # noncollinear sites without changing physics or mass.
                    from rigid_visuals import render as render_rigid
                    render_part=copy.deepcopy(part)
                    render_owner=components[owner].get('VisualParentId') or owner
                    meshes,contract=render_rigid(render_owner,render_part,manifest['mass_allocations'],meshes,mesh_names)
                    props=[row for row in render_part['props'][1:] if row[1] in mesh_names]
                    flex=[]
                    manifest.setdefault('rigid_render',{})[owner]=contract
                manifest.get('coilover_render',{}).pop(owner,None)
            # Mesh identifiers are package-owned, independent of CAD names/counts.
            path = scratch / (owner + '.dae')
            write_dae(path, [(item | {'Id': mesh_names[i]}, tris) for i, (item, tris) in enumerate(meshes)])
            material = manifest['model'] + '__appearance_material'
            contents[prefix + 'appearance_' + owner + '.dae'] = path.read_bytes().replace(b'mochi_frame_material', material.encode())
            cad_materials.update(dae_materials(contents[prefix + 'appearance_' + owner + '.dae'],prefix))
            contents.update({prefix+name:data for name,data in dae_texture_assets(path).items()})
            owned=manifest.get('component_meshes',{}).get(owner)
            if owned is None:owned=[row[0] for row in part.get('flexbodies',[])[1:] if isinstance(row,list)]
            coilover_visuals.replace_rows(part,owned,props,flex)
            manifest.setdefault('component_meshes',{})[owner]=mesh_names
            contents[name] = canonical(parts)
            appearance[owner] = source
            replacements[owner] = dict(meshes=mesh_names, groups=groups)
        materials = json.loads(contents[prefix + 'main.materials.json'])
        materials[material] = dict(name=material, mapTo=material, **{'class': 'Material'}, doubleSided=True,
                                   Stages=[dict(baseColorFactor=[.32, .56, .72, 1], roughnessFactor=.55)], version=1.5)
        materials.update(cad_materials)
        contents[prefix + 'main.materials.json'] = canonical(materials)
        after = physical_snapshot(contents, manifest)
        if baseline['sha256'] != after['sha256']:
            raise ValueError('Appearance operation attempted to change the physical model')
        manifest = copy.deepcopy(manifest)
        manifest.update(appearance_inputs=appearance, appearance_replacements=replacements,
                        rendered_review_status='required', calibration_inputs_status='not_applied',
                        physical_evidence=dict(baseline_receipt=str(receipt), baseline_zip_sha256=record['zip_sha256'],
                                               physics_sha256=baseline['sha256'], qualification_status=record.get('qualification_status', 'diagnostic')))
        provenance = {'baseline-receipt.json': receipt.read_bytes(),
                      'baseline-manifest.json': (receipt.parent / 'manifest.json').read_bytes(),
                      'baseline-physics.json': canonical(baseline)}
        # Evidence must survive removal of the original build directory.
        for name in record.get('component_provenance_sha256', {}):
            provenance['baseline/' + name] = (receipt.parent / name).read_bytes()
        for name in ('component-verification.json', 'verification.json'):
            if (receipt.parent / name).is_file():
                provenance[name] = (receipt.parent / name).read_bytes()
        acceptance=receipt.parent/'tests/acceptance.json'
        if acceptance.is_file():provenance['vehicle-acceptance.json']=acceptance.read_bytes()
        for owner in component_ids:
            current=coilover_visuals.inputs(components[owner])[1] if coilover_visuals.active(components[owner]) else appearance_meshes(components[owner])[1]
            if current!=appearance[owner]:
                raise ValueError('Appearance CAD changed during packaging: '+owner)
        if load_baseline(receipt)[3]!=baseline:raise ValueError('Physical baseline changed during appearance replacement')
        return package_revision(output, project, manifest, contents, provenance, receipt,
                                manifest.get('physics_origin', 'Existing packaged physics; replacement CAD properties have not been applied'))
    finally:
        shutil.rmtree(scratch)


def fork_baseline(project, receipt, output):
    """Give an immutable template its own namespace without retuning it."""
    record,manifest,contents,snapshot=load_baseline(receipt)
    old=record['identity']['namespace'];new=project['Identity']['namespace']
    from package_identity import validate_identity
    validate_identity(project['Identity'])
    if old==new:raise ValueError('A template fork needs a new project identity')
    def rename(value):
        if isinstance(value,dict):return {rename(key):rename(item) for key,item in value.items()}
        if isinstance(value,list):return [rename(item) for item in value]
        if isinstance(value,str):
            if value==old:return new
            if value in ('vehicles/'+old,'/vehicles/'+old):return value[:-len(old)]+new
            if value.startswith(old+'__'):return new+value[len(old):]
            if value.startswith('vehicles/'+old+'/'):return 'vehicles/'+new+'/'+rename(value[len('vehicles/'+old+'/'):])
            if value.startswith('/vehicles/'+old+'/'):return '/vehicles/'+new+'/'+rename(value[len('/vehicles/'+old+'/'):])
            if value in (old+'.jbeam',old+'.dae'):return new+value[len(old):]
        return value
    result={}
    for name,data in contents.items():
        if name.endswith(('.jbeam','.json','.pc')):data=canonical(rename(json.loads(data)))
        elif name.endswith('.dae'):
            import xml.etree.ElementTree as ET
            root=ET.fromstring(data)
            for element in root.iter():
                for key,value in list(element.attrib.items()):
                    if value.startswith('#'):element.set(key,'#'+rename(value[1:]))
                    else:element.set(key,rename(value))
            data=ET.tostring(root,encoding='utf-8',xml_declaration=True)
        elif name.endswith('.lua') and old.encode() in data:
            raise ValueError('Template runtime contains an embedded namespace; provide an explicit runtime migration')
        result[rename(name)]=data
    changed=rename(manifest)
    # Verify every physical JBeam value after the declared reversible rename.
    expected=rename(snapshot['value']['parts'])
    actual=physical_snapshot(result,changed)
    if actual['value']['parts']!=expected:raise ValueError('Fork changed physical properties')
    provenance={'template-receipt.json':Path(receipt).read_bytes(),'template-physics.json':canonical(snapshot),
                'template-manifest.json':(Path(receipt).parent/'manifest.json').read_bytes(),
                'namespace-migration.json':canonical(dict(old=old,new=new,physical_values_preserved=True))}
    for name in record.get('component_provenance_sha256',{}):provenance['template/'+name]=(Path(receipt).parent/name).read_bytes()
    if changed.get('template_definition'):
        provenance['template-definition.json']=canonical(changed['template_definition'])
    changed.update(fork_source=dict(receipt=str(receipt),physics_sha256=snapshot['sha256'],zip_sha256=record['zip_sha256']),
                   rendered_review_status='required',calibration_inputs_status='not_applied')
    return package_revision(output,project,changed,result,provenance,receipt,manifest.get('physics_origin','Imported template physics'))
