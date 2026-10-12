"""Synthetic mechanism fixture, deliberately not inferred from the user's CAD."""
from pathlib import Path
import itertools
import numpy as np
from vehicle_wizard.project import VehicleProject,write_json,sha256


def fixture(root,frame=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);source=root/'synthetic_source.txt';source.write_text('Synthetic analytical and native runner fixture; not CAD measurements.')
    p=VehicleProject.create(root/'project.json',source);p.data['name']='Wizard Synthetic Test Fixture';p.data['model']='wizard_test_fixture'
    if frame is None:
        coords=list(itertools.product([-.28,.28],[.0,2.],[.2,.65]));nodes=[['id','posX','posY','posZ']]
        nodes.extend([[f'f{i}',*v,{'nodeWeight':4.35,'collision':True,'selfCollision':False,'group':'frame'}] for i,v in enumerate(coords)])
        beams=[['id1:','id2:']]+[[f'f{i}',f'f{j}',{'beamSpring':350000,'beamDamp':100,'beamDeform':120000,'beamStrength':240000}] for i,j in itertools.combinations(range(8),2)]
        path=root/'frame.jbeam';write_json(path,{'fixture':{'slotType':'main','refNodes':[['ref:','back:','left:','up:'],['f4','f6','f0','f5']],'nodes':nodes,'beams':beams}});p.data['frame']=str(path)
    else:p.data['frame']=str(frame)
    assets=root/'assets';assets.mkdir(exist_ok=True);objects=[]
    def box(key,lo,hi):
        vertices=np.array(list(itertools.product(*zip(lo,hi))),dtype=np.float32)
        faces=np.array([[0,1,3],[0,3,2],[4,6,7],[4,7,5],[0,4,5],[0,5,1],[2,3,7],[2,7,6],[0,2,6],[0,6,4],[1,5,7],[1,7,3]],dtype=np.int32)
        np.savez_compressed(assets/(key+'.npz'),vertices=vertices,faces=faces)
        objects.append({'id':key,'name':key,'collections':['Synthetic fixture'],'bounds':[list(lo),list(hi)],'vertices':8,'triangles':12,'color':[.45,.5,.55],'file':key+'.npz'})
    box('frame_mesh',[-.28,0,.2],[.28,2,.65]);box('engine_mesh',[-.12,1.6,.35],[.12,1.85,.6])
    for corner in ('FL','FR','RL','RR'):
        sign=1 if corner[1]=='L' else -1;y=.2 if corner[0]=='F' else 1.8
        def pos(x,dy,z):return np.array([x*sign,y+dy,z])
        if corner[0]=='F':
            points={'upper_inner_front':pos(.24,-.16,.4),'upper_inner_rear':pos(.24,.16,.4),'upper_ball':pos(.60,0,.4),
                    'lower_inner_front':pos(.24,-.16,.2),'lower_inner_rear':pos(.24,.16,.2),'lower_ball':pos(.64,0,.16),
                    'hub':pos(.7,0,.25),'hub_axis':pos(.8,0,.25),'tie_inner':pos(.24,.13,.3),'tie_outer':pos(.62,.13,.3),
                    'shock_top':pos(.28,0,.72),'shock_bottom':pos(.53,0,.17)}
        else:
            points={'trailing_pivot':pos(.50,-.6,.25),'hub':pos(.7,0,.25),'hub_axis':pos(.8,0,.25),
                    'shock_top':pos(.34,-.12,.72),'shock_bottom':pos(.65,-.13,.23)}
            for i,z in enumerate([.12,.38]):
                inner=corner+f'_link{i}_in';outer=corner+f'_link{i}_out'
                p.set_point(inner,pos(.2,0,z),source='synthetic');p.set_point(outer,pos(.64,0,z),source='synthetic')
                p.data['corners'][corner]['links'].append({'inner':inner,'outer':outer})
        for role,point in points.items():name=corner+'_'+role;p.set_point(name,point,source='synthetic');p.bind_point(corner,role,name)
        box('wheel_'+corner,[sign*.7-.08,y-.27,-.02],[sign*.7+.08,y+.27,.52])
    for name,pos in {'engine_center':[0,1.7,.48],'cvt_center':[.2,1.7,.48],'engine_mount_1':[-.23,1.55,.3],
                     'engine_mount_2':[.23,1.55,.3],'engine_mount_3':[0,1.9,.3]}.items():p.set_point(name,pos,source='synthetic')
    index={'version':1,'objects':objects,'triangles':72,'units':'metres','scale_m':1};write_json(assets/'index.json',index)
    p.data.update(asset_index='assets/index.json',assembly_sha256=sha256(source),alignment_confirmed=True,assumptions_accepted=True)
    p.assign('Synthetic frame','frame',['frame_mesh'],mass=34.8);p.assign('Synthetic engine','engine',['engine_mesh'],mass=30)
    for corner in ('FL','FR','RL','RR'):p.assign('Synthetic wheel '+corner,'wheel',['wheel_'+corner],corner,6)
    for c in p.data['corners'].values():c['confirmed']=True
    p.save();return p
