"""Small, independent render fixture on an unchanged accepted vehicle package.

Does not open SolidWorks, change the user's project or regenerate physics.
"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import vehicle_revisions as r
from prepare_frame import write_stl


def tube(path,radius,sides=12):
    path=np.asarray(path);rings=[]
    for i,p in enumerate(path):
        tangent=path[min(i+1,len(path)-1)]-path[max(i-1,0)];tangent/=np.linalg.norm(tangent)
        seed=np.eye(3)[np.argmin(abs(tangent))];u=np.cross(tangent,seed);u/=np.linalg.norm(u);v=np.cross(tangent,u)
        rings.append([p+radius*(np.cos(t)*u+np.sin(t)*v) for t in np.linspace(0,2*np.pi,sides,endpoint=False)])
    triangles=[]
    for i in range(len(rings)-1):
        for j in range(sides):
            a,b,c,d=rings[i][j],rings[i][(j+1)%sides],rings[i+1][j],rings[i+1][(j+1)%sides]
            triangles.extend([[a,c,b],[b,c,d]])
    return np.array(triangles)


def build(baseline,destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    record,manifest,assets,before=r.load_baseline(baseline)
    project=json.loads((Path(baseline).parent/'project.snapshot.json').read_text(encoding='utf-8-sig'))
    project['LastBuildReceipt']=str(Path(baseline).resolve());owners=[]
    for comp in project['Components']:
        role=comp.get('MvpRole','')
        if not role.endswith('_spring_damper'):continue
        owner=comp['Id'];owners.append(owner);corner=role[:2].upper()
        points=manifest['template_definition']['hardpoints'][corner]
        a=np.array(points['shock_top']);b=np.array(points['shock_bottom']);direction=b-a;length=np.linalg.norm(direction);axis=direction/length
        seed=np.eye(3)[np.argmin(abs(axis))];u=np.cross(axis,seed);u/=np.linalg.norm(u);v=np.cross(axis,u)
        inverted=corner=='FR';housing='bottom' if inverted else 'top'
        start,end=(b,a) if inverted else (a,b)
        housing_mesh=tube([start,start+(end-start)*.60],.023)
        shaft_mesh=tube([end,end+(start-end)*.58],.010)
        phase=np.linspace(0,16*np.pi,257);fractions=np.linspace(.13,.86,len(phase))
        spring_path=a+fractions[:,None]*direction+.037*(np.cos(phase)[:,None]*u+np.sin(phase)[:,None]*v)
        spring_mesh=tube(spring_path,.0035,8)
        comp['AppearanceCoilover']=dict(HousingMount=housing,Pieces=[])
        for kind,mesh,color in [('housing',housing_mesh,[.9,.12,.07,1]),('shaft',shaft_mesh,[.75,.8,.85,1]),('spring',spring_mesh,[1,.8,.05,1])]:
            folder=destination/'cad'/owner/kind;folder.mkdir(parents=True)
            write_stl(folder/'mesh.stl',mesh[:,:,[0,2,1]]*[1,1,-1])
            body=owner+'_'+kind
            geometry=dict(Meshes=[dict(Id=body,File='mesh.stl',AppearanceGroups=[dict(StartTriangle=0,TriangleCount=len(mesh),Appearance=dict(BaseColor=color,Roughness=.35,Metallic=.4))])])
            (folder/'geometry.json').write_text(json.dumps(geometry))
            comp['AppearanceCoilover']['Pieces'].append(dict(Kind=kind,BodyIds=[body],GeometryDirectory=str(folder.resolve())))
    if len(owners)!=4:raise ValueError('Expected four coilover groups in the vehicle fixture')
    r.replace_appearance(project,owners,destination/'package')
    _,result,_,after=r.load_baseline(destination/'package/static_frame_build.json')
    if before!=after:raise ValueError('Coilover appearance changed the physical graph')
    (destination/'verification.json').write_text(json.dumps(dict(status='offline_passed',physics_identical=True,physics_sha256=before['sha256'],coilover_render=result['coilover_render']),indent=2))
    return destination/'package/manifest.json'


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',required=True);p.add_argument('--output',required=True);p.add_argument('--live',action='store_true');a=p.parse_args()
    manifest=build(a.baseline,a.output);print(manifest,flush=True)
    if a.live:
        from frame_harness.vehicle import run_vehicle
        from frame_harness.models import HarnessProject
        result=run_vehicle(manifest,'articulation',project=HarnessProject(userpath=Path('H:/BeamNGCadHarness/drive')))
        print(json.dumps(result,indent=2),flush=True)
        if result['status']!='passed':sys.exit(1)
