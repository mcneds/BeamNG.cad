"""Publish compact, read-only UI references from verified native vehicle exports.

Positions stay in BeamNG metres. Visible edges come from the exported CAD meshes,
never the numerical beam graph. Sources must match the manifest's hashes.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NS = {'c': 'http://www.collada.org/2005/11/COLLADASchema'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mesh_wire(paths):
    vertices, lookup, faces = [], {}, set()
    for path in paths:
        root = ET.parse(path)
        if root.find('.//c:up_axis', NS).text != 'Z_UP':
            raise ValueError('Reference requires exported Z-up geometry')
        if any(root.findall('.//c:' + tag, NS) for tag in ('matrix', 'translate', 'rotate', 'scale')):
            raise ValueError('Bake scene transforms before publishing a reference')
        for mesh in root.findall('.//c:mesh', NS):
            sources = {s.get('id'): s for s in mesh.findall('c:source', NS)}
            for triangles in mesh.findall('c:triangles', NS):
                inputs = triangles.findall('c:input', NS)
                entry = next(i for i in inputs if i.get('semantic') == 'VERTEX')
                vertex = mesh.find("c:vertices[@id='%s']" % entry.get('source')[1:], NS)
                source = sources[vertex.find("c:input[@semantic='POSITION']", NS).get('source')[1:]]
                accessor = source.find('.//c:accessor', NS)
                if int(accessor.get('stride', '3')) != 3:
                    raise ValueError('Expected xyz positions')
                xyz = list(map(float, source.find('c:float_array', NS).text.split()))
                indices = []
                for n in range(0, len(xyz), 3):
                    p = tuple(round(v, 6) for v in xyz[n:n+3])
                    if p not in lookup:
                        lookup[p] = len(vertices); vertices.append(p)
                    indices.append(lookup[p])
                stride = max(int(i.get('offset', 0)) for i in inputs) + 1
                raw = list(map(int, triangles.find('c:p', NS).text.split()))
                raw = raw[int(entry.get('offset', 0))::stride]
                for n in range(0, len(raw), 3):
                    face = tuple(indices[i] for i in raw[n:n+3])
                    if len(set(face)) == 3:
                        faces.add(face)
    edges = {}
    for a,b,c in faces:
        u = [vertices[b][i]-vertices[a][i] for i in range(3)]
        v = [vertices[c][i]-vertices[a][i] for i in range(3)]
        normal = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
        length = math.sqrt(sum(x*x for x in normal))
        if length < 1e-14: continue
        normal = [x/length for x in normal]
        for edge in ((a,b),(b,c),(c,a)):
            edges.setdefault(tuple(sorted(edge)), []).append(normal)
    # Retain creases and silhouettes in the principal views; omit tessellation
    # diagonals on flat surfaces. The result is an illustration, not collision data.
    kept = []
    for edge, normals in sorted(edges.items()):
        if len(normals) != 2 or sum(a*b for a,b in zip(*normals)) < .94 or any(
                normals[0][i]*normals[1][i] < -1e-6 for i in range(3)):
            kept.append(edge)
    used = sorted({i for edge in kept for i in edge})
    remap = {old:new for new,old in enumerate(used)}
    return {'vertices':[vertices[i] for i in used], 'edges':[[remap[a],remap[b]] for a,b in kept]}


def markers(role, definition):
    """Map catalog requests to explicit declaration points; never guess a pivot."""
    points = []
    def add(key, coords, source, note=''):
        points.append(dict(id=key, positions=coords, source=source, note=note))
    hp = definition['hardpoints'].get(role[:2].upper(), {})
    keys=CATALOG[role]['hardpoints']
    for group in CATALOG_DATA['mvp_template_sets']:
        selected=definition.get('templates',{}).get(group['id'])
        option=next((o for o in group['options'] if o['id']==selected),{})
        keys=option.get('hardpoints',{}).get(role,keys)
    for key in keys:
        names = {}
        if 'wishbone' in role:
            arm = 'upper' if 'upper' in role else 'lower'
            names = dict(inboard_front=arm+'_inner_front', inboard_rear=arm+'_inner_rear', outboard_joint=arm+'_ball')
        elif 'upright' in role:
            names = dict(upper_joint='upper_ball', lower_joint='lower_ball', steering_joint='tie_outer', toe_joint='tie_outer',carrier_joint='carrier_ball',upper_radius_joint='radius_upper_outer',lower_radius_joint='radius_lower_outer')
        elif role.endswith('radius_rod'):
            link='radius_upper' if 'upper' in role else 'radius_lower'
            names=dict(chassis_joint=link+'_inner',upright_joint=link+'_outer')
        elif role.endswith(('tie_rod','toe_link')):
            names = dict(rack_joint='tie_inner', chassis_joint='tie_inner', upright_joint='tie_outer')
        elif role.endswith('trailing_arm'):
            names = dict(pivot_axis_a='hinge_inner', pivot_axis_b='hinge_outer', hub_center='hub', spring_mount='shock_bottom', damper_mount='shock_bottom',carrier_joint='carrier_ball')
        elif role.endswith('spring_damper'):
            names = dict(chassis_mount='shock_top', suspension_mount='shock_bottom')
        elif role.endswith('wheel'):
            names = dict(hub_center='hub')
        if key in names and names[key] in hp:
            name = names[key]
            add(key, [hp[name]], 'hardpoints.'+role[:2].upper()+'.'+name,
                'Shared coilover attachment in this example.' if key in ('spring_mount','damper_mount') else '')
        elif key in ('hub_axis','wheel_axis') and 'hub_axis' in hp:
            # hub_axis is a SECOND POINT, not a unit direction in this schema.
            add(key, [hp['hub'],hp['hub_axis']], 'hardpoints.'+role[:2].upper()+'.hub -> hub_axis', 'Two points define the wheel rotation axis.')
        elif key == 'mounts':
            owners = ['panel_floor'] if role == 'panel' else [role]
            for owner in owners:
                if owner in definition['fixed_mounts']:
                    add(key, definition['fixed_mounts'][owner], 'fixed_mounts.'+owner, 'Separate attachment locations; not a continuous beam.')
        elif role in definition['halfshafts'] and key in ('inner_joint','outer_joint'):
            name = key.split('_')[0];add(key,[definition['halfshafts'][role][name]],'halfshafts.'+role+'.'+name)
        elif role in definition['shafts']:
            name = dict(rear_joint='outer',front_joint='inner',input_joint='inner',output_joint='outer').get(key)
            if name: add(key,[definition['shafts'][role][name]],'shafts.'+role+'.'+name)
        elif role == 'steering_rack' and key in ('left_joint','right_joint'):
            side = 'FL' if key=='left_joint' else 'FR';add(key,[definition['hardpoints'][side]['tie_inner']],'hardpoints.'+side+'.tie_inner')
        # Housing shaft axes are not explicit in this tested definition. Joint
        # positions alone don't prove the bearing axis, so show them as missing.
        if not any(p['id']==key for p in points):
            add(key, [], '', 'Not explicitly located in this tested reference. Define from your CAD; no example coordinate is inferred.')
    return points


CATALOG_DATA=json.loads((ROOT/'beamng.cad/FramePipeline/template_catalog.json').read_text())
CATALOG = {r['id']:r for r in CATALOG_DATA['mvp_roles']}


def publish(manifest_path, output):
    m = json.loads(manifest_path.read_text()); directory = manifest_path.parent
    meshes = {}
    sources = {'manifest_sha256':sha(manifest_path), 'files':{}}
    for owner, role in m['component_roles'].items():
        meshes.setdefault(role, [])
        name = m['model'] if owner == 'frame' else owner
        found = [key for key in m['files'] if Path(key).name == name+'.dae']
        if not found: raise ValueError('Missing reference mesh: '+owner)
        for key in found:
            path=directory/key
            if sha(path) != m['files'][key]: raise ValueError('Altered reference: '+key)
            sources['files'][key]=m['files'][key];meshes[role].append(path)
    definition=m['template_definition']
    roles={role:dict(mesh_wire(paths),markers=markers(role,definition)) for role,paths in meshes.items()}
    # Optional brake hardware has no visible mesh in this MVP, but its declared
    # hub axis can still be explained; caliper mounts remain explicitly missing.
    for role in CATALOG:
        if role.endswith('_brake'): roles[role]=dict(vertices=[],edges=[],markers=markers(role,definition))
    result=dict(version=1,templates=definition['templates'],label=manifest_path.parent.name,
                units='BeamNG metres: +X left, -Y front, +Z up', provenance=sources,roles=roles)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,separators=(',',':'))+'\n')
    print(output.name, output.stat().st_size, 'bytes;',sum(len(r['edges']) for r in roles.values()),'visible edges')


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('primary',type=Path);parser.add_argument('alternate',type=Path)
    args=parser.parse_args();dest=ROOT/'beamng.cad/FramePipeline/reference'
    publish(args.primary,dest/'primary.json');publish(args.alternate,dest/'alternate.json')
