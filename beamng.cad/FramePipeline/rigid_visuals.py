"""Native rigid props for detailed meshes on a declared rigid CAD component."""
import copy
import numpy as np
from frame_harness.build import node_table
from coilover_visuals import PROP_HEADER,replace_rows


def render(owner,part,allocations,meshes,names):
    if len(meshes)!=len(names) or len(set(names))!=len(names):raise ValueError('Rigid visual mesh names must be unique and complete')
    nodes=node_table(part);ids=sorted(n for n,m in allocations[owner].items() if m>0)
    if len(ids)<3:raise ValueError('Rigid visual needs three physical component nodes')
    xyz=np.array([nodes[n]['position'] for n in ids]);dist=np.linalg.norm(xyz[:,None]-xyz[None,:],axis=2)
    a,b=np.unravel_index(dist.argmax(),dist.shape);areas=np.linalg.norm(np.cross(xyz[b]-xyz[a],xyz-xyz[a]),axis=1);d=int(areas.argmax())
    if areas[d]<1e-8:raise ValueError('Rigid visual component nodes are collinear')
    zero=dict(x=0,y=0,z=0);props=[];output=[]
    for (record,triangles),name in zip(meshes,names):
        output.append((copy.deepcopy(record)|dict(Id=name),np.asarray(triangles)-xyz[a]))
        props.append(['constant',name,ids[a],ids[b],ids[d],zero.copy(),zero.copy(),zero.copy(),0,0,0,1,
                      dict(baseTranslation=zero.copy(),baseRotationGlobal=zero.copy(),optional=False)])
    replace_rows(part,names,props,[])
    return output,dict(nodes=[ids[a],ids[b],ids[d]],scope='Rigid visual follows physical component nodes; mass and physics unchanged')
