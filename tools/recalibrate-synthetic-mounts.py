"""Fresh mount topology calibration from an existing owned CAD preparation.

The baseline project and calibration remain unchanged. All outputs and evidence
are isolated, and the normal calibration/package/hash checks remain mandatory.
"""
import argparse,hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components as c
import calibration_worker as calibration
from full_vehicle_worker import definition_for_project
from vehicle_templates import frame_mount_plan
from build_static_frame import customize

p=argparse.ArgumentParser();p.add_argument('project',type=Path);p.add_argument('prepared',type=Path);p.add_argument('output',type=Path);p.add_argument('--frame-capture',type=Path);a=p.parse_args()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
if a.output.exists():raise FileExistsError('Use a fresh calibration output directory')
a.output.mkdir(parents=True)
project=read(a.project);project_path=a.output/'project.json'
if a.frame_capture:
    from prepare_frame import prepare
    capture=read(a.frame_capture);native=read(Path(capture['project']));recipe=read(a.frame_capture.parent/'recipe.json')
    frames=[v for v in native['Components'] if v['MvpRole']=='frame']
    if len(frames)!=1:raise ValueError('Expected exactly one frame in the native revision')
    shapes={v['id']:v for v in recipe['components']};audits={}
    for revised_component in native['Components']:
        owner=revised_component['Id'];prior=next((v for v in project['Components'] if v['Id']==owner),None)
        if prior is None or prior['MvpRole']!=revised_component['MvpRole']:raise ValueError('Native revision changed component ownership: '+owner)
        _,component_moments,_=c.read_geometry(revised_component)
        materials=read(Path(revised_component['GeometryDirectory'])/'material-snapshot.json')
        component_densities={float(v['density_kg_m3']) for v in materials['bodies']}
        if len(component_densities)!=1:raise ValueError('Independent primitive audit requires one material per component')
        shape=shapes[owner]
        volume=sum(s['analytic_volume_m3'] if s['kind']!='sheet' else
                   s['size'][0]*s['size'][1]*shape['thickness'] if shape['surface_mass_mode']=='thickness' else 0
                   for s in shape['primitives'])
        target=volume*next(iter(component_densities))
        if abs(component_moments[0]-target)>max(1e-6,target*1e-5):raise ValueError('Native mass/primitive audit failed: '+owner)
        audits[owner]=dict(native_mass_kg=component_moments[0],analytic_mass_kg=target)
        prior.update({key:revised_component[key] for key in ('GeometryDirectory','BodyIds','Selections','Configuration')})
    c.write(a.output/'native-revision-audit.json',dict(native_capture=str(a.frame_capture),components=audits))
    revised=frames[0];_,moments,_=c.read_geometry(revised)
    snapshot=read(Path(revised['GeometryDirectory'])/'material-snapshot.json')
    densities={float(v['density_kg_m3']) for v in snapshot['bodies']}
    if len(densities)!=1:raise ValueError('Independent volume audit requires one material')
    expected=shapes[revised['Id']]['analytic_volume_m3']*next(iter(densities))
    if abs(moments[0]-expected)>max(1e-6,expected*1e-5):raise ValueError('Native frame mass/primitive volume audit failed')
    index=next(i for i,v in enumerate(project['Components']) if v['MvpRole']=='frame')
    project['Components'][index]|={key:revised[key] for key in ('GeometryDirectory','BodyIds','Selections','Configuration')}
    project['FrameBuildReceipt']='';project['LastBuildReceipt']=''
    c.write(a.output/'frame-cad-audit.json',dict(native_mass_kg=moments[0],analytic_mass_kg=expected,native_capture=str(a.frame_capture)))
    prepare(Path(revised['GeometryDirectory'])/'geometry.json',a.prepared,a.output/'prepared',
            'C:/Program Files/Blender Foundation/Blender 5.0/blender.exe',
            'C:/Users/ak1di/AppData/Local/Microsoft/WindowsApps/PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0/python.exe')
else:shutil.copytree(a.prepared,a.output/'prepared')
c.write(project_path,project)
for name in ('fixed-graph.jbeam','fixed-graph-info.json'):
    if (a.output/'prepared'/name).exists():raise ValueError('Use a geometry preparation, not a fixed-graph revision')
c.write(a.output/'prepared/frame-mounts.json',frame_mount_plan(definition_for_project(project),project['Components']))
calibration.prepare(a.output/'prepared',a.output/'generation')
review=read(a.output/'generation/review.json');review.update(approved=True,approval_source='Owned synthetic fixture; production support/load generation on the fresh graph')
c.write(a.output/'generation/review.json',review)
def implementation_hashes():
    roots=[ROOT/'beamng.cad/FramePipeline',ROOT/'dependencies/cad-calibration/Test Harness/frame_harness']
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for root in roots for p in root.rglob('*') if p.suffix in ('.py','.lua')}
implementation=implementation_hashes()
calibration.calibrate(a.output/'generation')
if implementation!=implementation_hashes():
    c.write(a.output/'failure.json',dict(error='Generator implementation changed during calibration; fresh output required'))
    raise ValueError('Generator implementation changed during calibration; candidate cannot be packaged')
calibration.package(a.output/'generation','solidworks-assigned',a.output/'frame-package')
profile=dict(Name='Independent Synthetic Frame',Brand='CAD',Author='BeamNG CAD harness',Description='Fresh structural mounting topology',Configuration='Prototype',PreviewImage='')
c.write(a.output/'profile.json',profile)
customize(a.output/'frame-package/static_frame_build.json',a.output/'profile.json',a.output/'frame-namespaced',project_path)
project=read(project_path);project['FrameBuildReceipt']=str((a.output/'frame-namespaced/static_frame_build.json').resolve());project['LastBuildReceipt']=project['FrameBuildReceipt']
c.write(project_path,project)
print('SYNTHETIC_PROJECT '+str(project_path.resolve()),flush=True)
