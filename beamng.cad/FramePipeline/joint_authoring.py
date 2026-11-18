"""Native mate snapshots -> reviewed semantic joints -> vehicle inputs.

No CAD COM objects cross the worker boundary. Example skeleton coordinates are
never inputs here. Native constraints are combined, not translated one-to-one
into beams, and a classification remains a proposal until explicitly reviewed.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.linalg import null_space
import attachment_contract


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def point(value):
    p=np.asarray(value,float)
    if p.shape!=(3,) or not np.isfinite(p).all():raise ValueError('Expected three finite coordinates')
    return p


def axis(value):
    p=point(value);length=np.linalg.norm(p)
    if length<1e-10:raise ValueError('Joint axis has no direction')
    return p/length


def cross(p):
    x,y,z=p
    return np.array([[0,-z,y],[z,0,-x],[-y,x,0]])


def basis(direction):
    return null_space(axis(direction)[None,:]).T


def classify(records):
    """Linearized relative constraints with a geometric interpretation.

    A point fixes three translations at that point. Concentric axes fix two
    translations and two rotations. Plane coincidence fixes one translation
    and two rotations. Rank alone never turns an arbitrary mate into a hinge.
    """
    active=[]
    for r in records:
        if r.get('Suppressed') or r.get('PositioningOnly'):continue
        if r.get('Type','').upper()=='HINGE' and len(r.get('Entities',[]))==4:
            active.extend([r|dict(Type='CONCENTRIC',Entities=r['Entities'][:2]),r|dict(Type='COINCIDENT',Entities=r['Entities'][2:])])
        else:active.append(r)
    if not active:return dict(Kind='ignored',Issue='No active physical mates')
    entities=[e for r in active for e in r.get('Entities',[])]
    if any(r.get('Issue') for r in active):return dict(Kind='unresolved',Issue='; '.join(r['Issue'] for r in active if r.get('Issue')))
    if not entities:return dict(Kind='unresolved',Issue='Native mate contains no resolved owned geometry')
    centers=[point(e['Point']) for e in entities];center=np.mean(centers,axis=0)
    rows=[];limits=[];known=True
    for record in active:
        es=record['Entities'];kind=record['Type'].upper().replace('SWMATE','').replace('_','')
        if len(es)!=2:known=False;continue
        a,b=es;pa,pb=point(a['Point']),point(b['Point']);p=(pa+pb)/2
        translation=np.column_stack((np.eye(3),-cross(p-center)))
        rotation=np.column_stack((np.zeros((3,3)),np.eye(3)))
        types={a['Kind'],b['Kind']}
        if kind in ('LOCK','RIGID'):
            rows.extend(np.eye(6));continue
        if kind=='HINGE':
            u=axis(a['Axis']);rows.extend(translation);rows.extend(basis(u)@rotation)
        elif (kind=='COINCIDENT' and types=={'point'}) or (kind=='CONCENTRIC' and types<= {'point','sphere'} and 'sphere' in types):
            if np.linalg.norm(pa-pb)>1e-4:raise ValueError(record['Name']+': point mate is not solved')
            rows.extend(translation)
        elif kind=='CONCENTRIC' and types<={'cylinder','line','circle'} or kind=='COINCIDENT' and types=={'line'}:
            u=axis(a['Axis']);v=axis(b['Axis'])
            if abs(u@v)<1-1e-6 or np.linalg.norm(np.cross(pa-pb,u))>1e-4:raise ValueError(record['Name']+': concentric mate is not solved')
            rows.extend(basis(u)@translation);rows.extend(basis(u)@rotation)
            if record.get('LockRotation'):rows.append(u@rotation)
        elif kind=='COINCIDENT' and types=={'point','line'}:
            line=a if a['Kind']=='line' else b;vertex=b if a['Kind']=='line' else a
            u=axis(line['Axis']);p=point(vertex['Point'])
            if np.linalg.norm(np.cross(p-point(line['Point']),u))>1e-4:raise ValueError(record['Name']+': point is not on axis')
            rows.extend(basis(u)@np.column_stack((np.eye(3),-cross(p-center))))
        elif kind in ('COINCIDENT','DISTANCE','PARALLEL') and (types=={'plane'} or kind=='COINCIDENT' and types=={'plane','circle'}):
            u=axis(a['Axis']);v=axis(b['Axis'])
            if abs(u@v)<1-1e-6:raise ValueError(record['Name']+': plane mate is not solved')
            rows.extend(basis(u)@rotation)
            if kind!='PARALLEL':rows.append(u@translation)
        elif kind=='PARALLEL' and all(e.get('Axis') is not None for e in es):
            rows.extend(basis(a['Axis'])@rotation)
        elif kind in ('LIMITDISTANCE','LIMITANGLE') or record.get('HasLimits'):
            limits.append(record)
        else:known=False
    if not known:return dict(Kind='unresolved',Issue='Unsupported mate geometry; define/review this connection manually')
    if not rows:return dict(Kind='unresolved',Issue='Limits alone do not define a joint')
    matrix=np.asarray(rows);free=null_space(matrix,rcond=1e-8);dof=free.shape[1]
    kind='unresolved';direction=None;location=center
    if dof==0:kind='rigid'
    elif dof==1:
        t,w=free[:3,0],free[3:,0]
        if np.linalg.norm(w)<1e-7:kind='prismatic';direction=axis(t)
        elif abs(t@w)<1e-7:
            kind='revolute';direction=axis(w);location=center+np.cross(w,t)/(w@w)
    elif dof==2:
        t,w=free[:3],free[3:]
        if np.linalg.matrix_rank(w,tol=1e-7)==1:
            direction=np.linalg.svd(w)[0][:,0]
            # Both modes must preserve one common axis; screw/planar constraints
            # are not silently treated as a cylindrical joint.
            loc=np.linalg.lstsq(np.vstack([cross(w[:,i]) for i in range(dof)]),-t.T.reshape(-1),rcond=None)[0]
            if all(np.linalg.norm(np.cross(t[:,i]+cross(w[:,i])@loc,direction))<1e-6 for i in range(dof)):
                kind='cylindrical';location=center+loc
    elif dof==3:
        w=free[3:]
        if np.linalg.matrix_rank(w,tol=1e-7)==3:
            loc=np.linalg.lstsq(np.vstack([cross(w[:,i]) for i in range(dof)]),-free[:3].T.reshape(-1),rcond=None)[0]
            if np.linalg.norm(free[:3]+np.column_stack([cross(w[:,i])@loc for i in range(dof)]))<1e-6:
                kind='spherical';location=center+loc
    elif dof==4:
        # A ball centre constrained to a shaft axis retains all three rotations
        # and one axial translation. Do not collapse this into a ball joint.
        slides=[]
        for record in active:
            es=record['Entities']
            if record['Type'].upper()!='COINCIDENT' or {e['Kind'] for e in es}!={'point','line'}:break
            vertex=next(e for e in es if e['Kind']=='point');line=next(e for e in es if e['Kind']=='line')
            slides.append((point(vertex['Point']),axis(line['Axis'])))
        else:
            if slides and all(np.linalg.norm(p-slides[0][0])<1e-6 and abs(u@slides[0][1])>1-1e-6 for p,u in slides):
                kind='point_on_axis';location,direction=slides[0]
    result=dict(Kind=kind,Center=location.tolist(),Axis=None if direction is None else direction.tolist(),
                Issue=None if kind!='unresolved' else 'Combined constraints do not match a supported joint',DegreesOfFreedom=dof,
                HasLimits=bool(limits))
    if limits:
        if len(limits)!=1 or kind not in ('prismatic','revolute'):return dict(Kind='unresolved',Issue='Review limits against one supported translation or rotation axis')
        lo,hi=limits[0]['Minimum'],limits[0]['Maximum']
        if not np.isfinite([lo,hi]).all() or lo>=hi:raise ValueError('Invalid joint limits')
        result.update(Minimum=lo,Maximum=hi)
    return result


def proposals(workspace):
    groups={};result=[]
    for mate in workspace.get('Mates',[]):
        if mate.get('Suppressed') or mate.get('PositioningOnly'):continue
        entities=mate.get('Entities',[])
        pair=tuple(sorted({(e['ComponentId'],e.get('MemberId') or e['ComponentId']) for e in entities if e.get('ComponentId')}))
        if len(pair)!=2 or any(not e.get('ComponentId') for e in entities):
            pair=(('unresolved',mate['Id']),('unresolved',mate['Id']))
            mate=mate|dict(Issue=mate.get('Issue') or 'Mate must connect two identified groups or classified moving members')
        groups.setdefault(pair,[]).append(mate)
    previous={tuple(sorted(j.get('MateIds',[]))):j for j in workspace.get('Joints',[]) if j.get('Source')=='mates'}
    for pair,records in sorted(groups.items()):
        records=sorted(records,key=lambda r:r['Id']);ids=[r['Id'] for r in records];signature=fingerprint(records)
        try:analysis=classify(records)
        except ValueError as e:analysis=dict(Kind='unresolved',Issue=str(e))
        old=previous.get(tuple(ids));unchanged=old is not None and old.get('SourceHash')==signature
        proposal=dict(Id=old['Id'] if old else fingerprint(ids)[:32],Name=' + '.join(r['Name'] for r in records),
                      Parent=pair[0][0],Child=pair[1][0],ParentMember=pair[0][1],ChildMember=pair[1][1],
                      Status=old.get('Status','review') if unchanged else 'review',Source='mates',SourceHash=signature,MateIds=ids,**analysis)
        if old and not unchanged:proposal['Status']='needs_repair'
        result.append(proposal)
    found={j['Id'] for j in result}
    regrouped={mid for j in result for mid in j.get('MateIds',[])}
    for old in workspace.get('Joints',[]):
        if old.get('Source')!='mates':result.append(copy.deepcopy(old))
        elif old['Id'] not in found:
            # Ownership repairs can merge/split native constraint groups. The
            # replacement proposals already represent these active mates;
            # retaining their old unresolved groups invents missing joints.
            if old.get('MateIds') and set(old['MateIds'])<=regrouped:continue
            saved={m['Id']:m for m in workspace.get('Mates',[])}
            ignored=bool(old.get('MateIds')) and all(saved.get(i,{}).get('PositioningOnly') for i in old['MateIds'])
            result.append(old|dict(Status='positioning_only' if ignored else 'needs_repair',Issue=None if ignored else 'Native mates are missing or suppressed'))
    return result


def requests(project):
    from mvp_inventory import configuration
    catalog=json.loads(Path(__file__).with_name('template_catalog.json').read_text())
    selected,_,_=configuration(catalog,project);result=[]
    for category in catalog['mvp_template_sets']:
        option=next(o for o in category['options'] if o['id']==selected[category['id']]['id'])
        result.extend(copy.deepcopy(option.get('joint_requests',[])))
    return result


def resolve_bindings(project):
    workspace=project.get('JointWorkspace') or {};anchors={a['Id']:a for a in project.get('Anchors',[])}
    joints={j['Id']:j for j in workspace.get('Joints',[])};values={}
    active_requests={r['id'] for r in requests(project)} if project.get('Driveline') else None
    for binding in workspace.get('Bindings',[]):
        key=binding['Request']
        if active_requests is not None and key not in active_requests:continue
        if key in values:raise ValueError('Duplicate hardpoint binding: '+key)
        if binding.get('Status')!='resolved':raise ValueError('Repair '+key)
        if binding.get('JointId'):
            j=joints.get(binding['JointId'])
            if not j or j.get('Status')!='approved':raise ValueError('Review joint for '+key)
            if binding.get('ComponentId') not in (j['Parent'],j['Child']):raise ValueError('Joint does not belong to requested component')
            mode=binding.get('Point','center')
            if mode=='anchor':
                a=anchors.get(binding.get('AnchorId'))
                if not a or a.get('Status')!='resolved' or a['ComponentId']!=binding['ComponentId']:
                    raise ValueError('Repair CAD point for '+key)
                if a.get('GeneratedSource')=='joint_inference' and a.get('GeometryHash')!=j.get('SourceHash'):raise ValueError('Inferred joint site changed; preview again: '+key)
                p=a['Position']
                delta=point(p)-point(j['Center'])
                if j['Kind'] in ('revolute','cylindrical','prismatic'):
                    error=np.linalg.norm(np.cross(delta,axis(j['Axis'])))
                elif j['Kind']=='spherical':error=np.linalg.norm(delta)
                else:raise ValueError('Captured joint points require a spherical or axial joint')
                if error>1e-4:raise ValueError(key+': captured CAD point does not lie on the reviewed joint')
            elif mode=='center':p=j.get('Center')
            else:raise ValueError('Unknown joint point binding: '+mode)
        else:
            a=anchors.get(binding.get('AnchorId'))
            if not a or a.get('Status')!='resolved' or a['ComponentId']!=binding['ComponentId']:raise ValueError('Repair CAD point for '+key)
            p=a['Position']
        values[key]=point(p).tolist()
    return values


def definition(project):
    """Only reviewed, current CAD bindings enter generated template data."""
    from mvp_inventory import configuration
    workspace=project.get('JointWorkspace') or {}
    if workspace.get('Mode')!='authored':raise ValueError('Select authored joints before generating their template')
    catalog=json.loads(Path(__file__).with_name('template_catalog.json').read_text());chosen,_,_=configuration(catalog,project)
    templates={k:v['id'] for k,v in chosen.items()}
    if templates['front_suspension']!='double_wishbone':raise ValueError('Front suspension template is not implemented')
    required=requests(project)
    bindings={b['Request']:b for b in workspace.get('Bindings',[])}
    for request in required:
        owners=[c['Id'] for c in project['Components'] if c.get('MvpRole')==request['role']]
        if len(owners)!=1:raise ValueError(request['id']+': assign exactly one '+request['role']+' group')
        if request['id'] in bindings and bindings[request['id']].get('ComponentId')!=owners[0]:
            raise ValueError(request['id']+': hardpoint is bound to the wrong component; select '+request['role'])
    for component in project['Components']:
        if project.get('Driveline'):continue
        role=component.get('MvpRole','')
        ends=('inner_joint','outer_joint') if role.endswith('_halfshaft') else ('input_joint','output_joint') if role in ('front_propshaft','cvt_output_shaft') else ()
        for end in ends:
            key=component['Id']+'.'+end
            if key in bindings and bindings[key].get('ComponentId')!=component['Id']:
                raise ValueError(key+': shaft endpoint is bound to the wrong component')
    values=resolve_bindings(project);missing=[r['id'] for r in required if r['id'] not in values]
    if missing:raise ValueError('Bind required CAD hardpoints: '+', '.join(missing))
    parameters=workspace.get('Parameters') or {}
    if isinstance(parameters,list):parameters={p['Key']:p['Value'] for p in parameters}
    parameters=copy.deepcopy(parameters)
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v) for v in parameters.values()):
        raise ValueError('Physical parameters must be finite numbers')
    if 'tire_rays' in parameters:
        if parameters['tire_rays']!=int(parameters['tire_rays']):raise ValueError('Tire ray count must be an integer')
        parameters['tire_rays']=int(parameters['tire_rays'])
    pending=[j['Name'] for j in workspace.get('Joints',[]) if j.get('Status') not in ('approved','positioning_only') or j.get('Issue')]
    if pending:raise ValueError('Review or explicitly mark positioning-only native constraints before generation: '+', '.join(pending))
    frame=next(c['Id'] for c in project['Components'] if c.get('Template')=='calibrated_frame' or c.get('MvpRole')=='frame')
    result=dict(kind='vehicle_template',version=1,templates=templates,hardpoints={c:{} for c in ('FL','FR','RL','RR')},
                parameters=copy.deepcopy(parameters),fixed_mounts={},halfshafts={},shafts={},frame_component=frame,
                attachment_contract=attachment_contract.resolve(project),joint_authoring_sha256=fingerprint(workspace))
    for r in requests(project):
        corner,key=r['id'].split('.',1);result['hardpoints'][corner][key]=values[r['id']]
    from translating_rack import declaration
    result['steering']=declaration(project,workspace.get('Joints',[]),values)
    for mount in result['attachment_contract']:
        points=result['fixed_mounts'].setdefault(mount['child'],[])
        mount['index']=len(points);points.append(mount['position'])
    # Shaft endpoints are captured in the same editor and are never guessed from
    # bounds. Ordered multi-section chains are supplied as reviewed joint links.
    for comp in ([] if project.get('Driveline') else project['Components']):
        role=comp.get('MvpRole','');owner=comp['Id']
        if role.endswith('_halfshaft'):
            a,b=values.get(owner+'.inner_joint'),values.get(owner+'.outer_joint')
            if a is None or b is None:raise ValueError(comp['Name']+': bind both shaft endpoints')
            result['halfshafts'][owner]=dict(inner=a,outer=b,corner=role[:2].upper())
        elif role in ('front_propshaft','cvt_output_shaft'):
            if sum(c.get('MvpRole')==role for c in project['Components'])>1:continue
            a,b=values.get(owner+'.input_joint'),values.get(owner+'.output_joint')
            if a is None or b is None:raise ValueError(comp['Name']+': bind both shaft endpoints')
            result['shafts'][owner]=dict(inner=a,outer=b,inner_role='rear_final_drive' if role=='front_propshaft' else 'cvt',
                                       outer_role='front_diff' if role=='front_propshaft' else 'rear_final_drive' if templates['drivetrain']=='cvt_rear_front_output' else 'rear_diff')
    from authored_shafts import compile_chains
    result['shaft_chains']={} if project.get('Driveline') else compile_chains(project,result,values,parameters)
    if project.get('Driveline'):
        from driveline import resolve
        result.update(version=2,driveline=resolve(project))
    from joint_contract import validate
    result['joint_contract']=validate(project,result)
    return result
