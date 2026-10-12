"""Reviewable CAD connection proposals. Never modifies the input project."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
from collections import Counter,defaultdict
import numpy as np
import components as c
from component_representation import visual


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()


def geometry_hash(component):
    root=Path(component['GeometryDirectory']);data=json.loads((root/'geometry.json').read_text(encoding='utf-8-sig'))
    hashes={}
    for name in ['geometry.json']+[m['File'] for m in data['Meshes']]:
        path=(root/name).resolve()
        if path.parent!=root.resolve():raise ValueError('Geometry path escapes component')
        hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    return digest(hashes)


def moving_role(role):
    return any(role.endswith(s) for s in ('wishbone','upright','trailing_arm','radius_rod','toe_link','tie_rod','wheel','halfshaft','spring_damper')) or role in ('front_propshaft','cvt_output_shaft','steering_rack','steering_wheel')


def panel_sites(triangles,inset=.01):
    """Outer projected boundary; duplicate front/back triangles and holes ignored."""
    t=np.asarray(triangles,float);points=t.reshape(-1,3);origin=points.mean(axis=0)
    _,_,basis=np.linalg.svd(np.unique(points,axis=0)-origin,full_matrices=False)
    # Closed thin solids have two differently tessellated skins. Project only
    # one oriented skin; counting both makes genuine outer edges disappear.
    _,native=np.unique(np.round(points,7),axis=0,return_inverse=True)
    edge_counts=Counter(tuple(sorted((int(f[i]),int(f[(i+1)%3])))) for f in native.reshape(-1,3) for i in range(3))
    if edge_counts and all(n==2 for n in edge_counts.values()):
        normals=np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]);side=normals@basis[2]
        t=t[side>1e-12];points=t.reshape(-1,3)
        if len(t)==0:raise ValueError('Closed panel has no usable outward skin')
    uv=(points-origin)@basis[:2].T;keys=np.round(uv,7)
    vertices,inverse=np.unique(keys,axis=0,return_inverse=True)
    faces=inverse.reshape(-1,3);faces=np.unique(np.sort(faces,axis=1),axis=0)
    # Explicit 2D determinant: NumPy 2.4 no longer accepts 2D np.cross inputs.
    def area2(f):
        a,b=vertices[f[1]]-vertices[f[0]],vertices[f[2]]-vertices[f[0]]
        return a[0]*b[1]-a[1]*b[0]
    faces=[f for f in faces if abs(area2(f))>1e-12]
    counts=Counter(tuple(sorted((int(f[i]),int(f[(i+1)%3])))) for f in faces for i in range(3))
    adjacency=defaultdict(list)
    for (a,b),n in counts.items():
        if n==1:adjacency[a].append(b);adjacency[b].append(a)
    if not adjacency or any(len(v)!=2 for v in adjacency.values()):raise ValueError('Panel boundary is ambiguous; use manual fasteners')
    remaining=set(adjacency);loops=[]
    while remaining:
        start=min(remaining);loop=[start];previous=None;current=start
        while True:
            following=next(v for v in adjacency[current] if v!=previous)
            if following==start:break
            if following in loop:raise ValueError('Self-intersecting panel boundary')
            loop.append(following);previous,current=current,following
        remaining.difference_update(loop);loops.append(vertices[loop])
    def area(poly):return abs(sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(poly,np.roll(poly,-1,axis=0)))/2)
    boundary=max(loops,key=area)
    # Collapse collinear/tiny boundary details while preserving concave corners.
    tolerance=max(.001,np.linalg.norm(np.ptp(boundary,axis=0))*.003)
    while len(boundary)>3:
        errors=[]
        for i,p in enumerate(boundary):
            a,b=boundary[i-1],boundary[(i+1)%len(boundary)];d=b-a
            errors.append(np.linalg.norm(p-(a+np.clip((p-a)@d/max(d@d,1e-20),0,1)*d)))
        if min(errors)>tolerance:break
        boundary=np.delete(boundary,int(np.argmin(errors)),axis=0)
    if len(boundary)>12:
        # Rounded outlines: four perimeter extremes, not four box corners.
        ids={int(np.argmax(boundary@direction)) for direction in (np.array([1,0]),np.array([-1,0]),np.array([0,1]),np.array([0,-1]))}
        boundary=boundary[sorted(ids)]
    if len(boundary)<3:raise ValueError('At least three non-collinear bolt sites are required')
    sites=[]
    for corner in boundary:
        direction=uv.mean(axis=0)-corner;length=np.linalg.norm(direction)
        if length<=inset:raise ValueError('Panel too small for the selected corner inset')
        point=corner+direction/length*inset
        best=None
        # Recover each site's local surface position and normal, including bends.
        for face in t:
            local=(face-origin)@basis[:2].T;matrix=np.column_stack((local[1]-local[0],local[2]-local[0]))
            if abs(np.linalg.det(matrix))<1e-12:continue
            weights=np.linalg.solve(matrix,point-local[0])
            if min(weights)>=-1e-7 and sum(weights)<=1+1e-7:
                normal=np.cross(face[1]-face[0],face[2]-face[0]);normal/=np.linalg.norm(normal)
                location=face[0]+weights[0]*(face[1]-face[0])+weights[1]*(face[2]-face[0])
                best=(location,normal);break
        if best is None:raise ValueError('Corner inset falls outside panel material; reduce inset or add manual points')
        sites.append(best)
    if np.linalg.matrix_rank(np.array([p for p,n in sites])-sites[0][0],tol=1e-7)<2:raise ValueError('Bolt sites are collinear')
    return sorted(sites,key=lambda site:tuple(np.round(site[0],6)))


def ray_hit(point,direction,triangles,maximum):
    t=np.asarray(triangles);a=t[:,1]-t[:,0];b=t[:,2]-t[:,0]
    h=np.cross(np.broadcast_to(direction,b.shape),b);det=np.einsum('ij,ij->i',a,h)
    mask=np.abs(det)>1e-12;inv=np.divide(1.,det,out=np.zeros_like(det),where=mask)
    s=point-t[:,0];u=inv*np.einsum('ij,ij->i',s,h);q=np.cross(s,a);v=inv*(q@direction);distance=inv*np.einsum('ij,ij->i',b,q)
    valid=mask&(u>=-1e-7)&(v>=-1e-7)&(u+v<=1+1e-7)&(distance>=-1e-6)&(distance<=maximum)
    if not valid.any():return None
    distance=max(0.,float(distance[valid].min()));return distance,point+direction*distance


def connection_hash(connection):
    value={k:v for k,v in connection.items() if k not in ('GeneratedHash','UserEdited')}
    # DataContract JSON writes integral doubles as integers. Hash the semantic
    # values so a save/reload does not incorrectly label every bolt as edited.
    def number(v):return 0. if float(v)==0 else float(v)
    for key in ('Spring','Damping','Strength','AttachmentLength'):
        if key in value:value[key]=number(value[key])
    for key in ('SupportPosition','Normal'):
        if value.get(key) is not None:value[key]=[number(v) for v in value[key]]
    return digest(value)


def proposals(project,inset=.01,search=.05):
    if not .0<=inset<=.1 or not 0<search<=1:raise ValueError('Invalid corner inset or support search distance')
    project=copy.deepcopy(project);rows=[];geometry={};hashes={};owners={x['Id']:x for x in project['Components']}
    frames=[x for x in project['Components'] if x.get('MvpRole')=='frame' or x['Template']=='calibrated_frame']
    if len(frames)!=1:raise ValueError('Assign exactly one physical frame before Auto-connect')
    frame=frames[0]
    for owner,component in owners.items():
        try:
            meshes,moments,_=c.read_geometry(component)
            if moments[0]<=0:
                from component_representation import acknowledgement
                if not visual(component):raise ValueError('Zero mass: supply mass, or explicitly choose Visual only and acknowledge excluded mass')
                if component.get('MassAcknowledgement')!=acknowledgement(component):raise ValueError('Visual only, mass excluded: acknowledge this for the current geometry')
            geometry[owner]=meshes;hashes[owner]=geometry_hash(component)
        except Exception as error:rows.append(dict(Id=owner,ComponentId=owner,Name=component['Name'],Status='needs_input',Issue=str(error)))
    if frame['Id'] not in geometry:return dict(Rows=rows,Project=project)
    points=np.concatenate([t.reshape(-1,3) for r,t in geometry[frame['Id']]])
    center=(points.min(axis=0)+points.max(axis=0))/2
    placements=(project.get('JointWorkspace') or {}).get('Placements',[])
    fixed={o for o in owners if any(p['ComponentId']==o for p in placements) and all(p['Fixed'] for p in placements if p['ComponentId']==o)}
    panels={o for o,comp in owners.items() if comp['Template']=='panel' or comp.get('MvpRole','').startswith('panel')}
    structural={o for o in fixed|{frame['Id']} if o not in panels and not visual(owners[o]) and not moving_role(owners[o].get('MvpRole','')) and o in geometry}
    supports={o:np.concatenate([t for r,t in geometry[o]]) for o in structural}
    for owner,component in owners.items():
        if owner not in geometry or owner==frame['Id']:continue
        if visual(component):
            rows.append(dict(Id=owner,ComponentId=owner,Name=component['Name'],Status='visual_only',Issue='Follows physical parent; no independent bolts, collision or breakaway'));continue
        if owner in fixed and moving_role(component.get('MvpRole','')):
            rows.append(dict(Id=owner,ComponentId=owner,Name=component['Name'],Status='needs_input',Issue='Fixed component has a moving role; resolve native placement before inference'));continue
        if owner not in panels and owner not in fixed:continue
        # Never supplement or replace manually authored mounts automatically.
        anchors={a['Id']:a for a in project.get('Anchors',[])}
        existing=[v for v in project.get('Connections',[]) if anchors.get(v['AnchorB'],{}).get('ComponentId')==owner]
        if any(not v.get('GeneratedSource') or v.get('UserEdited') or v.get('GeneratedHash')!=connection_hash(v) for v in existing):
            rows.append(dict(Id=owner,ComponentId=owner,Name=component['Name'],Status='manual',Issue='Existing manual or edited fasteners retained; add any further bolts manually'));continue
        try:
            sites=[]
            for record,triangles in geometry[owner]:
                if owner in panels:sites.extend((record['Id'],i,p,n) for i,(p,n) in enumerate(panel_sites(triangles,inset)))
            if owner not in panels:
                xyz=np.concatenate([t.reshape(-1,3) for r,t in geometry[owner]]);a=xyz[0];b=xyz[np.argmax(np.linalg.norm(xyz-a,axis=1))];cross=np.linalg.norm(np.cross(xyz-a,b-a),axis=1);d=xyz[np.argmax(cross)]
                if max(cross)<1e-8:raise ValueError('Rigid attachment needs three separated sites')
                sites=[('rigid',i,p,np.zeros(3)) for i,p in enumerate((a,b,d))]
            connections=[];new_anchors=[];preview=[]
            for body,index,point,normal in sites:
                if owner in panels:
                    towards=center-point;projection=normal@towards
                    if abs(projection)<1e-6 and not component.get('AutoConnectNormalFlip'):raise ValueError('Inward normal is ambiguous; choose manual points or flip the panel direction')
                    normal=normal*(np.sign(projection) if abs(projection)>=1e-6 else 1)*(-1 if component.get('AutoConnectNormalFlip') else 1);hits=[]
                    for parent,tri in supports.items():
                        hit=ray_hit(point,normal,tri,search)
                        if hit is not None:hits.append((hit[0],parent,hit[1]))
                    hits.sort(key=lambda h:h[0])
                    if not hits:raise ValueError('No inward structural support within '+str(round(search*1000))+' mm at corner '+str(index+1))
                    if len(hits)>1 and abs(hits[0][0]-hits[1][0])<.001:raise ValueError('Two supports overlap at a corner; choose the parent manually')
                    _,parent,support=hits[0]
                else:parent=frame['Id'];support=point
                key=owner+'|'+body+'|'+str(index);identity=digest(key)[:32];a=identity+'a';b=identity+'b'
                provenance=digest([hashes[owner],hashes[parent]])
                for aid,part in ((a,parent),(b,owner)):
                    new_anchors.append(dict(Id=aid,Name=component['Name']+' '+str(index+1),ComponentId=part,Kind='generated',References=[],BodyReferences=[],Position=point.tolist(),LocalPosition=[float(point[0]),float(point[2]),float(-point[1])],CoordinateSpace='assembly',Offset=[0,0,0],Status='resolved',GeneratedSource='auto_connect',GeometryHash=hashes[part]))
                connection=dict(Id=identity,Name=component['Name']+' '+('bolt ' if owner in panels else 'rigid support ')+str(index+1),AnchorA=a,AnchorB=b,Template='breakable_fastener' if owner in panels else 'fixed',Spring=0.,Damping=0.,Strength=4000.,ReleaseSet='',AttachmentLength=.006,GeneratedSource='auto_connect',GeneratedKey=key,UserEdited=False,SupportPosition=support.tolist(),Normal=normal.tolist())
                connection['GeneratedHash']=connection_hash(connection);connections.append(connection);preview.append(dict(position=point.tolist(),support=support.tolist(),normal=normal.tolist(),parent=parent))
            rows.append(dict(Id=owner,ComponentId=owner,Name=component['Name'],Status='ready',Issue='',Anchors=new_anchors,Connections=connections,Preview=preview,GeometryHash=hashes[owner]))
        except ValueError as error:rows.append(dict(Id=owner,ComponentId=owner,Name=component['Name'],Status='needs_input',Issue=str(error)))
    from joint_inference import rows as infer_joints
    rows.extend(infer_joints(project))
    return dict(Rows=rows,Project=project)


def apply(project,rows):
    result=copy.deepcopy(project)
    for row in rows:
        if row['Status']!='ready':continue
        owner=row['ComponentId'];ids={a['Id'] for a in result.get('Anchors',[]) if a['ComponentId']==owner}
        old=[v for v in result.get('Connections',[]) if v['AnchorB'] in ids]
        if any(v.get('GeneratedSource')!='auto_connect' or v.get('UserEdited') or v.get('GeneratedHash')!=connection_hash(v) for v in old):raise ValueError('Manual/edited mounts changed; preview again')
        remove={a for v in old for a in (v['AnchorA'],v['AnchorB'])}
        result['Connections']=[v for v in result.get('Connections',[]) if v not in old]+row['Connections']
        used={a for v in result['Connections'] for a in (v['AnchorA'],v['AnchorB'])}
        result['Anchors']=[a for a in result.get('Anchors',[]) if a['Id'] not in remove or a['Id'] in used]
        newids={a['Id'] for a in row['Anchors']};result['Anchors']=[a for a in result['Anchors'] if a['Id'] not in newids]+row['Anchors']
    return result
