"""Reject native motions that the selected template would silently replace."""
import numpy as np


def validate(project,definition):
    workspace=project['JointWorkspace'];joints={j['Id']:j for j in workspace['Joints']};consumed=set()
    active_requests=None
    if project.get('Driveline'):
        from joint_authoring import requests
        active_requests={r['id'] for r in requests(project)}
    for endpoint in (project.get('Driveline') or {}).get('endpoints',[]):
        if endpoint.get('joint'):consumed.add(endpoint['joint'])
    for binding in workspace['Bindings']:
        if active_requests is not None and binding['Request'] not in active_requests:continue
        if not binding.get('JointId'):continue
        joint=joints[binding['JointId']];request=binding['Request'];kind=joint['Kind'];consumed.add(joint['Id'])
        key=request.split('.',1)[-1];corner=request.split('.',1)[0]
        p=definition['hardpoints'].get(corner)
        if p is None:continue # Shaft endpoints have their own ordered-chain check.
        if key in ('upper_ball','lower_ball','tie_inner','tie_outer','carrier_ball','trailing_ball','radius_upper_inner','radius_upper_outer','radius_lower_inner','radius_lower_outer','shock_top','shock_bottom'):
            if kind!='spherical':raise ValueError(request+': this template needs a spherical attachment; the native '+kind+' joint would impose different motion')
        elif key.startswith('carrier_axis_'):
            if kind!='revolute':raise ValueError(request+': this template requires the native carrier hinge')
            a,b=np.asarray(p['carrier_axis_a']),np.asarray(p['carrier_axis_b']);axis=np.asarray(joint['Axis'],float);axis/=np.linalg.norm(axis)
            if np.linalg.norm(b-a)<.001 or max(np.linalg.norm(np.cross(q-joint['Center'],axis)) for q in (a,b))>1e-4:
                raise ValueError(request+': carrier sites must lie on its native hinge axis')
        elif key.endswith(('inner_front','inner_rear')) or key in ('hinge_inner','hinge_outer'):
            if kind not in ('spherical','revolute'):raise ValueError(request+': select a pivot point or reviewed hinge')
            if kind=='revolute':
                a,b=(p['hinge_inner'],p['hinge_outer']) if key.startswith('hinge') else (p[key.split('_')[0]+'_inner_front'],p[key.split('_')[0]+'_inner_rear'])
                axis=np.asarray(joint['Axis'],float);axis/=np.linalg.norm(axis);line=np.asarray(b)-a
                if np.linalg.norm(line)<1e-5 or np.linalg.norm(np.cross(line,axis))/np.linalg.norm(line)>1e-4 or np.linalg.norm(np.cross(np.asarray(a)-joint['Center'],axis))>1e-4:
                    raise ValueError(request+': bound pivot pair does not lie on its native hinge axis')
        elif key=='hub' and kind not in ('spherical','revolute','cylindrical'):
            raise ValueError(request+': choose the native wheel-bearing centre or a CAD point')
        if joint.get('HasLimits'):
            raise ValueError(joint['Name']+': this suspension template cannot yet preserve native mate travel limits; specify its physical travel/stops separately and mark that limit as positioning-only')
    rack=definition.get('steering')
    if rack:consumed.add(rack['joint_id'])
    members={m['Id']:m for m in workspace['Members']}
    for joint in joints.values():
        if joint.get('Status')=='positioning_only':continue
        # A rigid native placement supplies the intact assembled motion. Its
        # independent fasteners still own failure; it must not add a hidden weld.
        mounts=[m for m in definition.get('attachment_contract',[]) if {m['parent'],m['child']}=={joint.get('Parent'),joint.get('Child')}]
        if mounts:
            if joint['Kind']!='rigid':raise ValueError(joint['Name']+': fixed/fastener mounts would remove this native joint motion; use the articulated template binding instead')
            xyz=np.asarray([m['position'] for m in mounts],float)
            if len(xyz)<3 or np.linalg.matrix_rank(xyz-xyz[0],tol=1e-8)<2:
                raise ValueError(joint['Name']+': a rigid mounted pair needs three separated, non-collinear fastening sites')
            consumed.add(joint['Id'])
        a,b=members.get(joint.get('ParentMember')),members.get(joint.get('ChildMember'))
        if a and b and a['ComponentId']==b['ComponentId'] and {a['Kind'],b['Kind']}=={'housing','shaft'}:
            if joint['Kind'] not in ('prismatic','cylindrical') or joint.get('HasLimits'):
                raise ValueError(joint['Name']+': coilover internals require reviewed axial motion; configure physical bump/rebound stops in Coilover settings')
            comp=next(c for c in project['Components'] if c['Id']==a['ComponentId']);role=comp.get('MvpRole','')
            if not role.endswith('_spring_damper'):raise ValueError('Housing/shaft internals must belong to a coilover group')
            points=definition['hardpoints'][role[:2].upper()];line=np.asarray(points['shock_bottom'])-points['shock_top'];axis=np.asarray(joint['Axis'])
            if np.linalg.norm(np.cross(line,axis))/(np.linalg.norm(line)*np.linalg.norm(axis))>1e-4:raise ValueError(joint['Name']+': shock mounts differ from the internal sliding axis')
            consumed.add(joint['Id'])
        if joint['Id'] not in consumed:
            raise ValueError(joint['Name']+': bind this reviewed joint to its requested template hardpoint, or explicitly mark it positioning-only. Unused constraints are not exported.')
    return dict(status='passed',native_joints=sorted(consumed),scope='Supported template joint kinds, ownership and axes; native finite-motion sweep and hardware limits require separate verification')
