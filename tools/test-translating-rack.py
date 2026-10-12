"""Native sweep of production rack geometry with an isolated fixed housing.

Uses declared analytic component moments to isolate the rail/actuator behavior.
It does not qualify the steering loads or handling of a completed vehicle.
"""
import argparse
import hashlib
import itertools
from pathlib import Path
import sys
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from vehicle_templates import Structure
from translating_rack import generate
from prepare_frame import write_dae,dae_materials
from frame_harness.build import write_json,beam_table
from frame_harness.component_tests import run_components,compact_success
from frame_harness.models import HarnessProject
from frame_harness.session import DriveSession


def build(directory,travel):
    directory.mkdir(parents=True,exist_ok=False);model='cad_rack_'+str(round(travel*1000));vehicle=directory/'vehicles'/model;vehicle.mkdir(parents=True)
    points=np.array(list(itertools.product([-.5,.5],[-.12,.12],[.4,.8])))
    frame=dict(slotType='main',nodes=[['id','posX','posY','posZ']]+[[f'f{i}',*p,dict(nodeWeight=2.,collision=False)] for i,p in enumerate(points)],
               beams=[['id1:','id2:']],refNodes=[['ref:','back:','left:','up:'],['f0','f2','f4','f1']],flexbodies=[['mesh','[group]:','nonFlexMaterials']])
    project=dict(Components=[dict(Id='rack',Name='Rack')],JointWorkspace=dict(Members=[dict(Id=i,Kind=k,ComponentId='rack',Name=i,GeometryDirectory='analytic',Selections=[],BodyIds=[i]) for i,k in [('housing','housing'),('slider','rack')]]))
    declaration=dict(component='rack',housing_member='housing',rack_member='slider',axis=[1.,0,0],half_travel_m=travel)
    spec=dict(steering=declaration,hardpoints=dict(FL=dict(tie_inner=[.3,0,.7]),FR=dict(tie_inner=[-.3,0,.7])))
    center=np.array([0.,0.,.7]);moments={}
    for owner,mass,size in [('housing',4.,[.45,.09,.09]),('slider',2.,[.65,.035,.035])]:
        x,y,z=size;moments[owner]=(mass,center,np.diag([y*y+z*z,x*x+z*z,x*x+y*y])*mass/12)
    moments['rack']=(6.,center,moments['housing'][2]+moments['slider'][2])
    graph=Structure(frame);hydros=[]
    with patch('components.read_geometry',side_effect=lambda c:([],moments[c['Id']],{})):
        generate(graph,project,spec,[[-.15,-.04,.7],[.15,-.04,.7],[0,.04,.7]],hydros)
    graph.part['hydros']=[['id1:','id2:']]+hydros
    part=graph.finish();part['information']=dict(name=model,authors='CAD rack fixture',value=0)
    part['controller']=[['fileName'],['dummy',{}]]
    meshes={}
    for owner,length,width,z in [('housing',.45,.09,.71),('slider',.65,.025,.765)]:
        verts=[[-length/2,-width/2,z],[length/2,-width/2,z],[length/2,width/2,z],[-length/2,width/2,z]]
        triangles=[[verts[i] for i in face] for face in ((0,1,2),(0,2,3),(2,1,0),(3,2,0))]
        name=model+'_'+owner;write_dae(vehicle/(owner+'.dae'),[(dict(Id=name),triangles)])
        part['flexbodies'].append([name,[owner+'_structure'],[]]);meshes[owner]=[name]
    materials={}
    for file in vehicle.glob('*.dae'):materials.update(dae_materials(file.read_bytes()))
    write_json(vehicle/'main.materials.json',materials);write_json(vehicle/'main.jbeam',{model:part})
    write_json(vehicle/'base.pc',dict(format=2,parts={model:model}));write_json(vehicle/'info.json',dict(Name='CAD rack fixture',Type='Prop',default_pc='base'))
    manifest=dict(kind='exported_vehicle',version=1,model=model,config='base.pc',main_part=model,main_jbeam='main.jbeam',vehicle_directory='vehicles/'+model,
        capabilities=['structure','mounts'],nodes={n:dict(position=v['position'],mass_kg=v['options']['nodeWeight'],component=graph.owners[n]) for n,v in graph.nodes.items()},
        fixed_nodes=[],chassis_nodes=graph.frame_ids+graph.steering_contract['housing_nodes'],expected_dry_mass_kg=sum(v['options']['nodeWeight'] for v in graph.nodes.values()),spawn_z=1.,
        explicit_beams=len(beam_table(part)),mounts=[],component_meshes=meshes,steering_contract=graph.steering_contract,
        qualification_scope='Isolated rack sweep; analytic moments and fixed housing, not complete-vehicle handling',
        files={p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in vehicle.iterdir()})
    write_json(directory/'manifest.json',manifest);return directory/'manifest.json'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);p.add_argument('--offline',action='store_true')
    p.add_argument('--game',type=Path,default=Path('D:/SteamLibrary/steamapps/common/BeamNG.drive'));p.add_argument('--profile',type=Path,default=Path('H:/BeamNGCadHarness/joints-v40-drive'));a=p.parse_args()
    if a.output.exists():raise FileExistsError('Use a fresh fixture directory')
    paths=[build(a.output/str(mm),mm/1000) for mm in (10,40)]
    if a.offline:return
    project=HarnessProject(game=a.game,userpath=a.profile,runs=a.output/'runs');results=[]
    with DriveSession(project,'vehicle') as session:
        for path in paths:
            project.runs=path.parent/'tests';results.append(run_components(path,'rack_sweep',session))
            write_json(a.output/'verification.json',dict(status='running',results=results))
            if results[-1]['status']!='passed':break
    passed=len(results)==len(paths) and all(r['status']=='passed' for r in results)
    write_json(a.output/'verification.json',dict(status='passed' if passed else 'failed',results=results))
    if passed:
        for result in results:compact_success(result['directory'])
    raise SystemExit(0 if passed else 1)


if __name__=='__main__':main()
