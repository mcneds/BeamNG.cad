"""Make an isolated component fixture around an existing calibrated frame.

The panel and accessory are synthetic. This does not assert ownership of any
unreviewed hardware in the user's complete assembly.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
sys.path.insert(0,str(ROOT/'tests'))
import components as c
import component_worker as worker
from build_static_frame import customize
from test_components import box_geometry


def create(receipt,geometry,output,cgal):
    output.mkdir(parents=True,exist_ok=False)
    data=worker.read(geometry/'geometry.json');identity={'id':uuid.uuid4().hex,'namespace':'cad_mount_test_'+uuid.uuid4().hex[:8]}
    project={'Version':2,'Identity':identity,'Components':[],'Anchors':[],'Connections':[]}
    c.write(output/'profile.json',dict(Name='Synthetic mounting fixture',Brand='BeamNG CAD',Author='Test',Description='Controlled component fixtures around a copied frame artifact',Configuration='Fixture',PreviewImage=''))
    c.write(output/'project.json',project)
    customize(receipt,output/'profile.json',output/'frame',output/'project.json')
    project['FrameBuildReceipt']=str(output/'frame/static_frame_build.json')
    frame={'Id':data['Assignment']['Id'],'Name':'Archived frame','Template':'calibrated_frame','GeometryDirectory':str(geometry),'BodyIds':[b['Id'] for b in data['Meshes']]}
    project['Components'].append(frame)
    definitions=[('panel',(.003,.65,.45),(.55,.65,.70),2.,'panel',[[-0.,-.25,-.15],[0,.25,-.15],[0,0,.17]]),
                 ('accessory',(.35,.35,.3),(0,1.55,.55),15.,'bulk',[[-.12,-.12,-.15],[.12,-.12,-.15],[0,.12,-.15]])]
    for name,extent,center,mass,template,mounts in definitions:
        box_geometry(output/name,extent,center,mass)
        comp={'Id':name,'Name':'Synthetic '+name,'Template':template,'Method':'alpha_wrap' if cgal and template=='bulk' else 'convex','GeometryDirectory':str(output/name),'BodyIds':[name],'Spacing':.13,'Alpha':.18,'WrapOffset':.001}
        project['Components'].append(comp)
        for i,offset in enumerate(mounts):
            position=[a+b for a,b in zip(center,offset)]
            parent=list(position)
            if template=='panel':parent[0]=.45
            else:parent[2]=.35
            aid=name+'_frame_'+str(i);bid=name+'_part_'+str(i)
            project['Anchors'].extend([dict(Id=aid,Name=aid,ComponentId=frame['Id'],Status='resolved',Position=parent),dict(Id=bid,Name=bid,ComponentId=name,Status='resolved',Position=position)])
            project['Connections'].append(dict(Id=name+'_'+str(i),Name=name+' mount '+str(i),AnchorA=aid,AnchorB=bid,Template='breakable_fastener',Spring=0,Damping=0,Strength=4000))
    c.write(output/'project.json',project)
    worker.build(output/'project.json',output/'build',cgal)
    print('FIXTURE_MANIFEST '+str(output/'build/manifest.json'),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--receipt',type=Path,required=True);p.add_argument('--geometry',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cgal');a=p.parse_args()
    create(a.receipt,a.geometry,a.output,a.cgal)
