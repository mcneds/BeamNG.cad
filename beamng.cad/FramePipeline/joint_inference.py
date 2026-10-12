"""Conservative role/topology matching; no example skeleton coordinates."""
import copy
import numpy as np
from joint_authoring import proposals,requests


def rows(project):
    workspace=project.get('JointWorkspace') or {};joints=proposals(workspace)
    owners={c['Id']:c for c in project['Components']};bindings={b['Request'] for b in workspace.get('Bindings',[]) if b.get('GeneratedSource')!='joint_inference'}
    fixed={p['ComponentId'] for p in workspace.get('Placements',[]) if p['Fixed']}
    mates={m['Id']:m for m in workspace.get('Mates',[])}
    ball_rear=any(t['Category']=='rear_suspension' and t['Template']=='trailing_ball_radius_toe' for t in project.get('MvpTemplates',[]))
    result={j['Id']:dict(Id='joint:'+j['Id'],ComponentId=j['Child'],Name=j['Name'],Status='needs_input' if j.get('Issue') or j['Kind']=='unresolved' else 'ready',Issue=j.get('Issue') or '',Joint=j,Bindings=[],Anchors=[]) for j in joints}
    for request in requests(project):
        if request['id'] in bindings:continue
        role=request['role'];key=request['id'].split('.',1)[1];candidates=[c for c in owners.values() if c.get('MvpRole')==role]
        if len(candidates)!=1:continue
        owner=candidates[0]['Id'];corner=role[:2];match=[]
        for joint in joints:
            if joint.get('Issue') or owner not in (joint['Parent'],joint['Child']):continue
            other=joint['Child'] if joint['Parent']==owner else joint['Parent'];other_role=owners.get(other,{}).get('MvpRole','')
            if other==owner:continue
            is_chassis=other in fixed or other_role=='frame'
            wanted=(key in ('shock_top','radius_upper_inner','radius_lower_inner','hinge_inner','hinge_outer','trailing_ball') or key.endswith(('inner_front','inner_rear')))
            if wanted:ok=is_chassis
            elif key in ('hub','hub_axis'):
                upright=any(c.get('MvpRole')==corner+'_upright' for c in owners.values())
                ok=other_role==corner+('_upright' if upright else '_trailing_arm')
            elif key in ('radius_upper_outer','radius_lower_outer') and ball_rear:ok=other_role==corner+'_trailing_arm'
            elif key in ('upper_ball','lower_ball','tie_outer','carrier_ball','carrier_axis_a','carrier_axis_b','radius_upper_outer','radius_lower_outer'):ok=other_role==corner+'_upright'
            elif key=='tie_inner':ok=other_role=='steering_rack' if corner in ('fl','fr') else is_chassis
            elif key=='shock_bottom':ok=other_role in (corner+'_lower_wishbone',corner+'_trailing_arm')
            else:ok=False
            if ok:match.append(joint)
        if len(match)!=1:
            result['request:'+request['id']]=dict(Id='request:'+request['id'],ComponentId=owner,Name=request['label'],Status='needs_input',Issue='No unique supported joint matches this hardpoint');continue
        joint=match[0];row=result[joint['Id']]
        spherical=key in ('upper_ball','lower_ball','tie_inner','tie_outer','carrier_ball','trailing_ball','radius_upper_inner','radius_upper_outer','radius_lower_inner','radius_lower_outer','shock_top','shock_bottom')
        pivot=key.endswith(('inner_front','inner_rear')) or key.startswith(('hinge_','carrier_axis_'))
        if pivot and joint['Kind']=='spherical':
            result['request:'+request['id']]=dict(Id='request:'+request['id'],ComponentId=owner,Name=request['label'],Status='needs_input',Issue='Template requires two distinct pivot sites; the native joint supplies a single ball centre');continue
        if joint.get('HasLimits') or (spherical and joint['Kind']!='spherical') or (pivot and joint['Kind'] not in ('spherical','revolute')):
            result['request:'+request['id']]=dict(Id='request:'+request['id'],ComponentId=owner,Name=request['label'],Status='needs_input',Issue='Native joint motion/limits do not match this template hardpoint');continue
        if joint['Kind']=='spherical' and key!='hub_axis':
            row['Bindings'].append(dict(Request=request['id'],ComponentId=owner,JointId=joint['Id'],Point='center',Status='resolved'));continue
        # Distinct axial sites come only from separate native entity locations.
        if joint['Kind'] not in ('revolute','cylindrical'):continue
        axis=np.asarray(joint['Axis']);center=np.asarray(joint['Center'])
        sites=[np.asarray(e['Point']) for mid in joint.get('MateIds',[]) for e in mates[mid]['Entities'] if e['ComponentId']==owner]
        if key.startswith('carrier_axis_'):
            sites=[np.asarray(p) for mid in joint.get('MateIds',[]) for e in mates[mid]['Entities'] if e['ComponentId']==owner for p in (e.get('AxisSites') or [])]
        sites=[p for p in sites if np.linalg.norm(np.cross(p-center,axis))<=1e-4]
        if len(sites)<2 or np.ptp([p@axis for p in sites])<.001:
            result['request:'+request['id']]=dict(Id='request:'+request['id'],ComponentId=owner,Name=request['label'],Status='needs_input',Issue='Joint axis identified, but two distinct native bearing/pivot sites are required');continue
        # BeamNG forward is -Y; order wishbone pivots accordingly. Wheel sites
        # use lateral distance to the centreline rather than arbitrary axis sign.
        if key.startswith('carrier_axis_'):sites.sort(key=lambda p:float(p@axis));point=sites[0] if key.endswith('_a') else sites[-1]
        elif key.endswith(('inner_front','inner_rear')):sites.sort(key=lambda p:p[1]);point=sites[0] if key.endswith('front') else sites[-1]
        else:sites.sort(key=lambda p:abs(p[0]));point=sites[0] if key in ('hub','hinge_inner') else sites[-1]
        aid='inferred_'+request['id'];row['Anchors'].append(dict(Id=aid,Name=request['label'],ComponentId=owner,Kind='inferred_joint',Position=point.tolist(),LocalPosition=[float(point[0]),float(point[2]),float(-point[1])],CoordinateSpace='assembly',Offset=[0,0,0],References=[],BodyReferences=[],Status='resolved',GeneratedSource='joint_inference',GeometryHash=joint['SourceHash']))
        row['Bindings'].append(dict(Request=request['id'],ComponentId=owner,JointId=joint['Id'],AnchorId=aid,Point='anchor',Status='resolved'))
    # Shaft endpoints require physical joint centres. A cylindrical axis alone
    # does not locate a CV joint along that axis, so leave it for CAD capture.
    for component in owners.values():
        role=component.get('MvpRole','');owner=component['Id']
        if role.endswith('_halfshaft'):
            ends={'inner_joint':({'front_diff'} if role[:2] in ('fl','fr') else {'rear_diff','rear_final_drive'}),'outer_joint':{role[:2]+'_upright',role[:2]+'_wheel'}}
        elif role in ('front_propshaft','cvt_output_shaft'):
            ends={'input_joint':{'rear_final_drive'} if role=='front_propshaft' else {'cvt'},'output_joint':{'front_diff'} if role=='front_propshaft' else {'rear_diff','rear_final_drive'}}
        else:continue
        for suffix,other_roles in ends.items():
            key=owner+'.'+suffix
            if key in bindings:continue
            candidates=[]
            for joint in joints:
                if joint.get('Issue') or joint.get('HasLimits') or joint['Kind'] not in ('spherical','point_on_axis') or owner not in (joint['Parent'],joint['Child']):continue
                other=joint['Child'] if joint['Parent']==owner else joint['Parent']
                compatible=owners.get(other,{}).get('MvpRole') in other_roles
                # A grounded datum at the inner CV is equivalent to a datum on
                # its fixed differential housing. Require that housing to be
                # uniquely tagged and actually fixed in the native assembly.
                if suffix=='inner_joint' and other in fixed:
                    housings=[c for c in owners.values() if c.get('MvpRole') in other_roles]
                    compatible=compatible or (len(housings)==1 and housings[0]['Id'] in fixed)
                if compatible:candidates.append(joint)
            if len(candidates)==1:
                joint=candidates[0];result[joint['Id']]['Bindings'].append(dict(Request=key,ComponentId=owner,JointId=joint['Id'],Point='center',Status='resolved'))
            else:
                result['request:'+key]=dict(Id='request:'+key,ComponentId=owner,Name=component.get('Name',owner)+' '+suffix,Status='needs_input',Issue='Select an exact shaft joint centre; axial bearings or intermediate carriers require endpoint review')
    for row in result.values():
        for binding in row.get('Bindings',[]):binding['GeneratedSource']='joint_inference'
    return list(result.values())
