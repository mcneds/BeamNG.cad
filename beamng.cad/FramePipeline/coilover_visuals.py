"""Split coilover skin on an existing physical graph; no added nodes or forces.

Native rigid props follow opposing eye nodes. The spring alone uses a flexbody.
The captured CAD mesh is expressed about its own mount, with the native global
rotation override preserving its authored rest orientation. No runtime Lua.
"""
from __future__ import annotations
import copy
import numpy as np
from frame_harness.build import node_table

KINDS=('housing','shaft','spring')
PROP_HEADER=['func','mesh','idRef:','idX:','idY:','baseRotation','rotation','translation','min','max','offset','multiplier']


def active(component):
    return bool((component.get('AppearanceCoilover') or {}).get('Pieces'))


def inputs(component):
    from vehicle_revisions import appearance_meshes
    value=component.get('AppearanceCoilover') or {}
    pieces=value.get('Pieces',[])
    if not component.get('MvpRole','').endswith('_spring_damper'):
        raise ValueError('Split coilover visuals require a spring/damper role')
    if len(pieces)!=3 or sorted(p.get('Kind','') for p in pieces)!=sorted(KINDS):
        raise ValueError('Assign all three coilover pieces: housing, shaft and spring')
    mount=value.get('HousingMount','top')
    if mount not in ('top','bottom'):raise ValueError('Choose the coilover housing mount: top or bottom')
    result={};sources={};seen=set()
    for piece in pieces:
        if not piece.get('GeometryDirectory'):raise ValueError('Export saved coilover pieces before packaging')
        meshes,source=appearance_meshes(dict(GeometryDirectory=piece['GeometryDirectory'],AppearanceTransform=component.get('AppearanceTransform')))
        ids={item['Id'] for item,_ in meshes}
        if len(ids)!=len(meshes) or ids & seen:raise ValueError('Coilover bodies cannot be assigned to more than one moving piece')
        if piece.get('BodyIds') and ids!=set(piece['BodyIds']):raise ValueError('Coilover body ownership changed; reassign '+piece['Kind'])
        seen.update(ids);result[piece['Kind']]=meshes;sources[piece['Kind']]=source
    return result,dict(housing_mount=mount,pieces=sources)


def contract(component,part,manifest,groups):
    """Resolve mounts from reviewed hardpoints, never a world-Z guess."""
    owner=component['Id'];corner=component.get('MvpRole','')[:2].upper()
    points=manifest.get('template_definition',{}).get('hardpoints',{}).get(corner)
    nodes=node_table(part)
    if not points:raise ValueError('Coilover animation requires a packaged vehicle with reviewed shock hardpoints')
    allocated=manifest.get('mass_allocations',{}).get(owner,{})
    ends={}
    for end in ('top','bottom'):
        matches=[n for n in allocated if n in nodes and np.allclose(nodes[n]['position'],points['shock_'+end],atol=1e-7,rtol=0)]
        if len(matches)!=1:raise ValueError('Cannot uniquely resolve coilover '+end+' mount in the packaged physics')
        ends[end]=matches[0]
    a=np.array(nodes[ends['top']]['position']);b=np.array(nodes[ends['bottom']]['position']);axis=b-a
    length=np.linalg.norm(axis)
    if length<.001:raise ValueError('Coilover mounting points must be distinct')
    axis/=length
    candidates=[]
    for name,node in nodes.items():
        ng=node['options'].get('group',[]);ng=[ng] if isinstance(ng,str) else ng
        if not set(groups)&set(ng) or name in ends.values():continue
        offset=np.asarray(node['position'])-a
        perpendicular=np.linalg.norm(np.cross(offset,axis))
        if perpendicular>.001:candidates.append((perpendicular/max(np.linalg.norm(offset),.001),name))
    if not candidates:raise ValueError('Coilover needs a non-collinear suspension node to orient its rigid meshes')
    # This node only defines roll. It adds no mass, constraints or hardpoints.
    roll=max(candidates)[1]
    return dict(top=ends['top'],bottom=ends['bottom'],roll=roll,rest_length_m=float(length),spring_groups=list(groups))


def render(component,part,manifest,groups,prefix):
    pieces,source=inputs(component);binding=contract(component,part,manifest,groups)
    nodes=node_table(part);meshes=[];names=[];props=[];flex=[];by_kind={}
    housing=source['housing_mount'];ends={'housing':housing,'shaft':'bottom' if housing=='top' else 'top'}
    zero=dict(x=0,y=0,z=0)
    for kind in KINDS:
        by_kind[kind]=[]
        for index,(item,triangles) in enumerate(pieces[kind]):
            name=prefix+'_'+kind+'_'+str(index);names.append(name);by_kind[kind].append(name)
            record=copy.deepcopy(item);record['Id']=name
            if kind=='spring':
                flex.append([name,groups,[]]);mesh=np.asarray(triangles)
            else:
                end=ends[kind];ref=binding[end];other=binding['bottom' if end=='top' else 'top']
                origin=np.asarray(nodes[ref]['position'])
                mesh=np.asarray(triangles)-origin
                options=dict(baseTranslation=zero.copy(),baseRotationGlobal=zero.copy(),optional=False)
                props.append(['constant',name,ref,other,binding['roll'],zero.copy(),zero.copy(),zero.copy(),0,0,0,1,options])
            meshes.append((record,mesh))
    return meshes,names,props,flex,source,binding|dict(meshes=by_kind,housing_mount=housing)


def replace_rows(part,owned,props,flex):
    """Replace both native mesh sections; repeated packaging must not duplicate props."""
    owned=set(owned or [])
    for section,column,new,header in [('props',1,props,PROP_HEADER),('flexbodies',0,flex,['mesh','[group]:','nonFlexMaterials'])]:
        current=part.get(section,[header]);actual=current[0]
        if new and actual!=header:raise ValueError('Unsupported '+section+' header in coilover baseline')
        kept=[r for r in current[1:] if not isinstance(r,list) or len(r)<=column or r[column] not in owned]
        if new or section in part:part[section]=[actual]+kept+new
