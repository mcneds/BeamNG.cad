"""Isolated diagnostic tire/render revision; never edits source CAD or baseline."""
import argparse,json,sys,zipfile,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components as c
from build_static_frame import completed_build
from vehicle_revisions import package_revision,canonical
from prepare_frame import write_dae,dae_materials
from rigid_visuals import render
from vehicle_templates import cad_tire_budget

p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('output',type=Path)
p.add_argument('--rigid-visual',nargs='*',default=[]);p.add_argument('--tire-budget',action='store_true')
p.add_argument('--rigid-fixed',nargs='*',default=[],help='Explicit diagnostic rigid attachment to the frame; no moving or breakaway parts')
p.add_argument('--wheel-visuals',action='store_true',help='Bind separate CAD rim/hub and tire bodies to the corresponding native wheel groups')
p.add_argument('--refit-rigid',nargs='*',default=[],help='Diagnostic internal rigid-body refit using final shared node masses')
p.add_argument('--component-scale',type=float,default=1.)
p.add_argument('--component-damping-scale',type=float,default=1.);a=p.parse_args()
if not 0<a.component_scale<=1:p.error('Component scale must be in (0,1]')
if not 0<a.component_damping_scale<=1:p.error('Component damping scale must be in (0,1]')
receipt=a.baseline/'static_frame_build.json';record,archive=completed_build(receipt)
m=json.loads((a.baseline/'manifest.json').read_text());project=json.loads((a.baseline/'project.snapshot.json').read_text())
with zipfile.ZipFile(archive) as z:contents={n:z.read(n) for n in z.namelist()}
prefix='vehicles/'+m['model']+'/';file=prefix+m['main_jbeam'];parts=json.loads(contents[file]);part=parts[m['main_part']]
changes={}
if a.refit_rigid:
    from rigid_revision import refit
    from rigid_bracing import budget_connections
    from frame_harness.build import node_table
    selected=[];contracts={}
    for owner in a.refit_rigid:
        role=m.get('component_roles',{}).get(owner,'') or ''
        if not any(role.endswith(suffix) for suffix in ('_wishbone','_trailing_arm','_upright')):
            raise ValueError('Rigid refit requires a declared rigid suspension member')
        changed,contracts[owner]=refit(part,m['mass_allocations'],owner);selected.extend(changed)
    budget=budget_connections(part,node_table(part),selected,limit=3.4)
    m['torsionbars']=part.get('torsionbars',[])[1:]
    changes['rigid_refit']=dict(components=contracts,budget=budget)
    m['limitations'].append('Diagnostic internal rigidity refit uses final assembled node masses. Low-mass hardpoints remain flagged; material accuracy is not established.')
if a.wheel_visuals:
    from wheel_visuals import render as render_wheel
    from coilover_visuals import replace_rows
    from vehicle_revisions import physical_snapshot
    before=physical_snapshot(contents,m)
    for owner,role in m['component_roles'].items():
        if not (role or '').endswith('_wheel'):continue
        comp=next(v for v in project['Components'] if v['Id']==owner)
        names=m['component_meshes'][owner]
        flex,contract=render_wheel(part,role.removesuffix('_wheel').upper(),c.read_geometry(comp)[0],names,comp.get('WheelVisualRoles'))
        replace_rows(part,names,[],flex)
        m.setdefault('wheel_render',{})[owner]=contract
    contents[file]=canonical(parts)
    if before!=physical_snapshot(contents,m):raise ValueError('Wheel render revision changed physical properties')
    changes['wheel_visuals']=dict(physics_sha256=before['sha256'],contracts=m['wheel_render'])
if a.rigid_fixed:
    from fixed_structure import attach
    from frame_harness.build import node_table
    from rigid_bracing import budget_connections
    added=[];contracts=dict(m.get('fixed_attachment_contract',{}))
    for owner in a.rigid_fixed:
        if owner in contracts:raise ValueError('Component already has a rigid attachment: '+owner)
        if owner not in m['template_definition'].get('fixed_mounts',{}):
            raise ValueError('Rigid attachment requires an existing fixed component: '+owner)
        if any(v.get('child')==owner for v in m.get('mounts',[])):
            raise ValueError('Cannot rigidly attach a breakaway component: '+owner)
        rows,contracts[owner]=attach(part,m['mass_allocations'][owner],m['chassis_nodes'])
        added.extend(rows)
    # Keep the baseline suspension coefficients unchanged. Reserve the small
    # additional tangent budget explicitly for this diagnostic intervention;
    # 3.4 remains below the explicit step boundary of 4, but requires native tests.
    budget=budget_connections(part,node_table(part),[row[-1] for row in added],limit=3.4)
    m['fixed_attachment_contract']=contracts
    m['explicit_beams']+=len(added)
    m['torsionbars']=part.get('torsionbars',[])[1:]
    changes['rigid_fixed']=dict(components=contracts,budget=budget)
    m['limitations'].append('Explicit diagnostic rigid attachment of selected fixed structures. Their mass remains simulated; no shaft rotation or attachment failure is represented.')
for owner in a.rigid_visual:
    comp=next(v for v in project['Components'] if v['Id']==owner);comp['RigidAppearance']=True
    meshes,contract=render(owner,part,m['mass_allocations'],c.read_geometry(comp)[0],m['component_meshes'][owner])
    with tempfile.TemporaryDirectory(dir=a.output.parent) as tmp:
        path=Path(tmp)/'mesh.dae';write_dae(path,meshes)
        contents[prefix+owner+'.dae']=path.read_bytes().replace(b'mochi_frame_material',(m['model']+'__template_material').encode())
    materials=json.loads(contents[prefix+'main.materials.json'])
    materials.update(dae_materials(contents[prefix+owner+'.dae']))
    contents[prefix+'main.materials.json']=canonical(materials)
    changes[owner]=contract
if a.tire_budget:
    changes['tire_budget']={}
    for row in part['pressureWheels'][1:]:
        row[-1],changes['tire_budget'][row[0]]=cad_tire_budget(row[-1])
contents[file]=canonical(parts)
if a.component_scale!=1 or a.component_damping_scale!=1:
    frame=set(m['chassis_nodes'])
    for section in ('beams','hydros'):
        for row in part.get(section,[])[1:]:
            if not isinstance(row,list) or set(row[:2])<=frame:continue
            o=row[-1]
            if o.get('beamType') in ('|BOUNDED','|SUPPORT'):continue
            for key in ('beamSpring','beamDamp'):
                if key in o:o[key]*=a.component_scale*(a.component_damping_scale if key=='beamDamp' else 1.)
    for row in part.get('torsionbars',[])[1:]:
        if isinstance(row,list) and not set(row[:4])<=frame:
            for key in ('spring','damp'):row[-1][key]*=a.component_scale*(a.component_damping_scale if key=='damp' else 1.)
    changes['component_scale']=a.component_scale
    changes['component_damping_scale']=a.component_damping_scale
    m['torsionbars']=part.get('torsionbars',[])[1:]
    m['connection_budget']['diagnostic_component_scale']=a.component_scale
    for report in m.get('component_reports',{}).values():report['diagnostic_component_scale']=a.component_scale
    contents[file]=canonical(parts)
m['limitations'].append('Diagnostic revision: see diagnostic_revision for explicit render/physics interventions. Pending native validation.')
m['diagnostic_revision']=changes
provenance={n.removeprefix('provenance/'):(a.baseline/n).read_bytes() for n in m.get('provenance_files',{})}
provenance['revision/baseline-receipt.json']=receipt.read_bytes();provenance['revision/changes.json']=canonical(changes)
provenance['revision/script.py']=Path(__file__).read_bytes();provenance['revision/rigid_visuals.py']=(ROOT/'beamng.cad/FramePipeline/rigid_visuals.py').read_bytes()
if a.rigid_fixed:provenance['revision/fixed_structure.py']=(ROOT/'beamng.cad/FramePipeline/fixed_structure.py').read_bytes()
if a.wheel_visuals:provenance['revision/wheel_visuals.py']=(ROOT/'beamng.cad/FramePipeline/wheel_visuals.py').read_bytes()
if a.refit_rigid:provenance['revision/rigid_revision.py']=(ROOT/'beamng.cad/FramePipeline/rigid_revision.py').read_bytes()
package_revision(a.output,project,m,contents,provenance,receipt,'Native CAD vehicle with explicit diagnostic tire/render revision')
print('REVISION '+str(a.output/'manifest.json'),flush=True)
