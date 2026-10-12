"""Owned native release fixtures using the production connector generator.

Analytic plate moments isolate attachment behavior. They are not CAD calibration
or real-hardware bolt-strength evidence. Never modifies a user's vehicle build.
"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import sys
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from attachment_contract import resolve,connect,audit_release
from planned_mounts import insert_mounts
from vehicle_templates import Structure
from prepare_frame import write_dae,dae_materials
from frame_harness.build import write_json,beam_table
from frame_harness.component_tests import run_components,compact_success
from frame_harness.models import HarnessProject
from frame_harness.session import DriveSession


def build(directory,linked):
    directory.mkdir(parents=True,exist_ok=False);model='cad_fastener_linked' if linked else 'cad_fastener_independent'
    vehicle=directory/'vehicles'/model;vehicle.mkdir(parents=True)
    corners=np.array(list(itertools.product([-.45,.45],[-.45,.45],[.4,.65])))
    frame=dict(slotType='main',nodes=[['id','posX','posY','posZ']]+[[f'f{i}',*p,dict(nodeWeight=2.,group=['frame'],collision=False)] for i,p in enumerate(corners)],
        beams=[['id1:','id2:']]+[[f'f{i}',f'f{j}',dict(beamSpring=15000,beamDamp=2,beamDeform=1e30,beamStrength=1e30)] for i,j in itertools.combinations(range(8),2)],
        refNodes=[['ref:','back:','left:','up:'],['f0','f2','f4','f1']],flexbodies=[['mesh','[group]:','nonFlexMaterials']])
    sites=[[-.3,-.3,.7],[.3,-.3,.7],[0,.3,.7]]
    project=dict(Components=[dict(Id='frame'),dict(Id='panel')],Anchors=[],Connections=[])
    for i,p in enumerate(sites):
        for owner in ('frame','panel'):project['Anchors'].append(dict(Id=owner+str(i),Name=owner,ComponentId=owner,Status='resolved',Position=p))
        project['Connections'].append(dict(Id='bolt'+str(i),Name='Fastener '+str(i+1),AnchorA='frame'+str(i),AnchorB='panel'+str(i),
            Template='breakable_fastener',ReleaseSet='panel_clips' if linked else '',AttachmentLength=.006,Spring=15000.,Damping=2.,Strength=40.+i*15))
    mounts=resolve(project)
    for i,m in enumerate(mounts):m['index']=i
    insert_mounts(frame,{'fastener_'+m['id']:dict(position=m['position'],mode='short',attachment_length_m=m['length']) for m in mounts})
    # All chassis/locator nodes are pinned only in the isolated load fixture.
    # Production package contains no pins; the harness inserts them in staging.
    for row in frame['beams'][1:]:
        if isinstance(row,list):row[-1].update(beamSpring=1000.,beamDamp=.2)
    graph=Structure(frame)
    mass=12.;center=np.array([0.,0.,.7]);size=np.array([.7,.7,.008]);inertia=np.diag([size[1]**2+size[2]**2,size[0]**2+size[2]**2,size[0]**2+size[1]**2])*mass/12
    with patch('components.read_geometry',return_value=([],(mass,center,inertia),{})):
        graph.rigid_component(dict(Id='panel'),{'panel_mount_'+str(i):p for i,p in enumerate(sites)})
    connect(graph,mounts,{})
    part=graph.finish();binding={'panel':['panel_structure']};audit=audit_release(part,graph.mounts,graph.owners,binding)
    verts=[[-.35,-.35,.7],[.35,-.35,.7],[.35,.35,.7],[-.35,.35,.7]]
    triangles=[[verts[i] for i in ids] for ids in ((0,1,2),(0,2,3),(2,1,0),(3,2,0))]
    write_dae(vehicle/'panel.dae',[(dict(Id='test_panel'),triangles)])
    part['flexbodies'].append(['test_panel',['panel_structure'],[]])
    part['information']=dict(name=model,authors='BeamNG CAD test',value=0)
    write_json(vehicle/'main.jbeam',{model:part});write_json(vehicle/'main.materials.json',dae_materials((vehicle/'panel.dae').read_bytes()))
    write_json(vehicle/'base.pc',dict(format=2,parts={model:model}));write_json(vehicle/'info.json',dict(Name='CAD fastener fixture',Type='Prop',default_pc='base'))
    manifest=dict(kind='exported_vehicle',version=1,model=model,config='base.pc',main_part=model,main_jbeam='main.jbeam',vehicle_directory='vehicles/'+model,
        capabilities=['structure','mounts'],nodes={n:dict(position=v['position'],mass_kg=v['options']['nodeWeight'],component=graph.owners[n]) for n,v in graph.nodes.items()},
        fixed_nodes=[],chassis_nodes=graph.frame_ids,expected_dry_mass_kg=sum(v['options']['nodeWeight'] for v in graph.nodes.values()),spawn_z=1.,
        explicit_beams=len(beam_table(part)),mounts=graph.mounts,component_meshes={'panel':['test_panel']},render_bindings=binding,release_audit=audit,
        qualification_scope='Analytic plate attachment fixture; not calibrated CAD or hardware strength',
        files={p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in vehicle.iterdir()})
    write_json(directory/'manifest.json',manifest);return directory/'manifest.json'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    parser.add_argument('--game',type=Path,default=Path('D:/SteamLibrary/steamapps/common/BeamNG.drive'))
    parser.add_argument('--profile',type=Path,default=Path('H:/BeamNGCadHarness/joints-v40-drive'))
    parser.add_argument('--offline',action='store_true');args=parser.parse_args()
    if args.output.exists():raise ValueError('Use a new fixture directory')
    paths=[build(args.output/name,linked) for name,linked in [('independent',False),('linked',True)]]
    if args.offline:return
    project=HarnessProject(game=args.game,userpath=args.profile,runs=args.output/'runs');results=[]
    with DriveSession(project,'vehicle') as session:
        for path in paths:
            project.runs=path.parent/'tests'
            for scenario in ('mount_release','mount_load_release'):
                result=run_components(path,scenario,session);results.append(result)
                write_json(args.output/'verification.json',dict(status='running',results=results))
                if result['status']!='passed':break
            if results[-1]['status']!='passed':break
    passed=len(results)==4 and all(r['status']=='passed' for r in results)
    write_json(args.output/'verification.json',dict(status='passed' if passed else 'failed',results=results,scope='Release semantics and synthetic force response; rendered review remains required'))
    if passed:
        for r in results:compact_success(r['directory'])
    raise SystemExit(0 if passed else 1)


if __name__=='__main__':main()
