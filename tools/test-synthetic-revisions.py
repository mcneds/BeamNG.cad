"""Use real native CAD captures to exercise appearance/property/template revisions.

This validates package invariants. Native behavior is recorded separately; these
checks never upgrade a vehicle's acceptance or fracture status.
"""
import argparse,copy,hashlib,json,sys,uuid,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components as c
from vehicle_revisions import replace_appearance,load_baseline,fork_baseline
from property_revisions import recalibrate_component,topology
read=lambda p:json.loads(Path(p).read_text(encoding='utf-8-sig'))

p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('appearance_capture',type=Path);p.add_argument('property_capture',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
if a.output.exists():raise FileExistsError('Use a fresh revision study')
a.output.mkdir(parents=True)
receipt=a.baseline/'static_frame_build.json';project=read(a.baseline/'project.snapshot.json');project['LastBuildReceipt']=str(receipt.resolve())
before=load_baseline(receipt);evidence=dict(baseline=str(receipt),baseline_physics_sha256=before[3]['sha256'],scope='Native CAD inputs and immutable package contracts; live vehicle qualification is separate')
appearance=read(read(a.appearance_capture)['project']);render=copy.deepcopy(project)
changed=[]
for replacement in appearance['Components']:
    component=next(v for v in render['Components'] if v['Id']==replacement['Id'])
    component['AppearanceDirectory']=replacement['GeometryDirectory'];changed.append(component['Id'])
c.write(a.output/'appearance-project.json',render)
replace_appearance(render,changed,a.output/'appearance')
after=load_baseline(a.output/'appearance/static_frame_build.json')
assert after[3]==before[3], 'Appearance changed physics'
evidence['appearance']=dict(status='passed',replaced=changed,identical_physics=True,
    previous_mesh_counts={k:len(before[1]['component_meshes'][k]) for k in changed},
    new_mesh_counts={k:len(after[1]['component_meshes'][k]) for k in changed})

source=read(read(a.property_capture)['project']);replacement=next(v for v in source['Components'] if v['Id']=='engine')
properties=copy.deepcopy(project);index=next(i for i,v in enumerate(properties['Components']) if v['Id']=='engine')
properties['Components'][index]=properties['Components'][index]|{key:replacement[key] for key in ('GeometryDirectory','BodyIds','Selections','Configuration')}
c.write(a.output/'properties-project.json',properties)
recalibrate_component(properties,'engine',a.output/'properties')
fitted=load_baseline(a.output/'properties/static_frame_build.json')
assert topology(before[2])==topology(fitted[2]),'Property fit moved nodes or altered connectivity'
assert fitted[3]['sha256']!=before[3]['sha256'],'Property change did not affect physics'
old_mass=sum(before[1]['mass_allocations']['engine'].values());new_mass=c.read_geometry(replacement)[1][0]
assert abs(fitted[1]['expected_dry_mass_kg']-(before[1]['expected_dry_mass_kg']-old_mass+new_mass))<1e-6
evidence['properties']=dict(status='passed',old_engine_mass_kg=old_mass,native_engine_mass_kg=new_mass,topology_preserved=True,
    fit=fitted[1]['component_reports']['engine'])

fork=copy.deepcopy(project);identity=uuid.uuid4().hex;fork['Identity']=dict(id=identity,namespace='native_fork_'+identity[:12]);fork['PhysicsTemplateReceipt']=str(receipt.resolve())
c.write(a.output/'fork-project.json',fork);fork_baseline(fork,receipt,a.output/'fork')
forked=load_baseline(a.output/'fork/static_frame_build.json')
evidence['fork']=dict(status='passed',namespace=forked[1]['model'],parent_namespace=before[1]['model'])
assert load_baseline(receipt)[3]==before[3],'Baseline changed during revision tests'
evidence['baseline_unchanged']=True
c.write(a.output/'verification.json',evidence)
print('NATIVE_REVISION_CONTRACTS_PASSED '+str(a.output),flush=True)
