"""Native rigid props for detailed meshes on a declared rigid CAD component."""
import copy
import numpy as np
from frame_harness.build import node_table
from coilover_visuals import PROP_HEADER,replace_rows


def render(owner,part,allocations,meshes,names,steering=None):
    if len(meshes)!=len(names) or len(set(names))!=len(names):raise ValueError('Rigid visual mesh names must be unique and complete')
    nodes=node_table(part);ids=sorted(n for n,m in allocations[owner].items() if m>0)
    if len(ids)<3:raise ValueError('Rigid visual needs three physical component nodes')
    xyz=np.array([nodes[n]['position'] for n in ids]);dist=np.linalg.norm(xyz[:,None]-xyz[None,:],axis=2)
    a,b=np.unravel_index(dist.argmax(),dist.shape);areas=np.linalg.norm(np.cross(xyz[b]-xyz[a],xyz-xyz[a]),axis=1);d=int(areas.argmax())
    if areas[d]<1e-8:raise ValueError('Rigid visual component nodes are collinear')
    zero=dict(x=0,y=0,z=0);props=[];output=[]
    animated=bool(steering and steering.get('Enabled'))
    if animated:
        from steering_visuals import transform
        pivot,basis,rotation=transform(steering,meshes)
    for (record,triangles),name in zip(meshes,names):
        mesh=(np.asarray(triangles)-pivot)@basis if animated else np.asarray(triangles)-xyz[a]
        output.append((copy.deepcopy(record)|dict(Id=name),mesh))
        options=(dict(baseTranslationGlobalRigid=dict(zip(('x','y','z'),map(float,pivot))),baseRotationGlobal=rotation,optional=False)
                 if animated else dict(baseTranslation=zero.copy(),baseRotationGlobal=zero.copy(),optional=False))
        props.append(['steering' if animated else 'constant',name,ids[a],ids[b],ids[d],zero.copy(),
                      dict(x=0,y=0,z=1) if animated else zero.copy(),zero.copy(),-10000 if animated else 0,10000 if animated else 0,0,1,options])
    replace_rows(part,names,props,[])
    report=dict(nodes=[ids[a],ids[b],ids[d]],scope='Rigid visual follows physical component nodes; mass and physics unchanged')
    if animated:report['steering']=copy.deepcopy(steering)|dict(electric='steering',meshes=list(names),basis=basis.tolist())
    return output,report
