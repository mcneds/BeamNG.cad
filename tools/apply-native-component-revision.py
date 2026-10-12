"""Merge freshly exported native fixture groups into an isolated harness project."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components as c

p=argparse.ArgumentParser();p.add_argument('project',type=Path);p.add_argument('capture',type=Path);p.add_argument('output',type=Path)
p.add_argument('--components',nargs='+',help='Explicit subset of captured component IDs to revise')
a=p.parse_args()
read=lambda p:json.loads(Path(p).read_text(encoding='utf-8-sig'))
project=read(a.project);capture=read(a.capture);native=read(capture['project']);recipe=read(a.capture.parent/'recipe.json')
if a.output.exists():raise FileExistsError('Use a new candidate project')
shapes={v['id']:v for v in recipe['components']};replacements={v['Id']:v for v in native['Components']};audit={}
if a.components:
    missing=set(a.components)-replacements.keys()
    if missing:raise ValueError('Components missing from native capture: '+', '.join(sorted(missing)))
    replacements={key:value for key,value in replacements.items() if key in a.components}
for owner,comp in replacements.items():
    if owner=='frame':raise ValueError('Frame revisions require fresh frame calibration')
    if owner not in {v['Id'] for v in project['Components']}:raise ValueError('New role requires template regeneration: '+owner)
    meshes,moments,_=c.read_geometry(comp)
    material=read(Path(comp['GeometryDirectory'])/'material-snapshot.json')
    densities={float(body['density_kg_m3']) for body in material['bodies']}
    if len(densities)!=1:raise ValueError('Independent primitive audit expects one assigned material per group')
    target=shapes[owner]['analytic_volume_m3']*next(iter(densities))
    if abs(moments[0]-target)>max(.000001,target*.00001):raise ValueError('Native mass/primitive audit failed: '+owner)
    audit[owner]=dict(native_mass_kg=moments[0],analytic_mass_kg=target,bodies=len(meshes))
for i,comp in enumerate(project['Components']):
    if comp['Id'] in replacements:
        revised=replacements[comp['Id']]
        if revised['MvpRole']!=comp['MvpRole']:raise ValueError('Role changed')
        project['Components'][i]=comp|{key:revised[key] for key in ('GeometryDirectory','BodyIds','Selections','Configuration')}
a.output.parent.mkdir(parents=True,exist_ok=True);c.write(a.output,project)
c.write(a.output.with_suffix('.audit.json'),dict(source_project=str(a.project),source_sha256=hashlib.sha256(a.project.read_bytes()).hexdigest(),
    native_capture=str(a.capture),native_capture_sha256=hashlib.sha256(a.capture.read_bytes()).hexdigest(),components=audit))
