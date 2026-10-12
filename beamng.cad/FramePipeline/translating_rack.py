"""A CAD-owned rigid rack translating in a mounted housing.

Three rail locators constrain orientation; both tie rods retain fixed length.
Only rack translation is controlled, through two coupled opposed hydros.
Auxiliary locators are numerical supports,
not additional CAD material or inferred physical bolts.
"""
from __future__ import annotations
import copy
import math
import numpy as np
import components as c


def declaration(project,joints,points):
    rack=next((v for v in project['Components'] if v.get('MvpRole')=='steering_rack'),None)
    if rack is None:raise ValueError('Assign a steering rack group')
    members=[m for m in project['JointWorkspace'].get('Members',[]) if m['ComponentId']==rack['Id']]
    kinds={m['Kind']:m for m in members}
    if set(kinds)!={'housing','rack'} or len(members)!=2:raise ValueError('Classify the steering group into housing and rack members')
    ids=[m['Id'] for m in members]
    candidates=[j for j in joints if j['Kind']=='prismatic' and j['Status']=='approved' and {j.get('ParentMember'),j.get('ChildMember')}==set(ids)]
    if len(candidates)!=1:raise ValueError('Review one prismatic native mate arrangement between the rack and housing')
    j=candidates[0];u=np.asarray(j['Axis'],float)
    if u.shape!=(3,) or not np.isfinite(u).all() or np.linalg.norm(u)<1e-8:raise ValueError('Review the rack joint axis')
    u/=np.linalg.norm(u)
    if u[0]<0:u=-u
    if abs(u[0])<.5:raise ValueError('Rack axis is not predominantly lateral; review the selected CAD axis')
    parameters=project['JointWorkspace'].get('Parameters') or {}
    if isinstance(parameters,list):parameters={p['Key']:p['Value'] for p in parameters}
    travel=float(parameters.get('rack_half_travel_m',.04))
    if not math.isfinite(travel) or not .001<=travel<=.15:raise ValueError('Rack half travel must be between 1 and 150 mm')
    speed=travel_speed(parameters.get('rack_speed_m_s',.1))
    if j.get('HasLimits'):
        raise ValueError('Native rack limit distances need a reviewed zero reference; remove the limit mate from physical inference and set rack half travel explicitly')
    return dict(kind='translating_rack',component=rack['Id'],housing_member=kinds['housing']['Id'],rack_member=kinds['rack']['Id'],
                axis=u.tolist(),joint_id=j['Id'],half_travel_m=travel,speed_m_s=speed)


def travel_speed(value):
    value=float(value)
    if not math.isfinite(value) or not .005<=value<=.5:
        raise ValueError('Rack speed must be between 0.005 and 0.5 metres per second')
    return value


def member_component(project,owner,member_id):
    member=next(m for m in project['JointWorkspace']['Members'] if m['Id']==member_id)
    if not member.get('GeometryDirectory'):raise ValueError('Export moving-member CAD before generation: '+member['Name'])
    comp=next(v for v in project['Components'] if v['Id']==owner)
    result=comp|dict(Id=member_id,Name=member['Name'],Selections=member['Selections'],BodyIds=member['BodyIds'],GeometryDirectory=member['GeometryDirectory'],AppearanceDirectory=None,_VisualMass=member.get('_VisualMass',[]))
    if comp.get('MassPolicy')=='custom':
        from components import read_geometry
        whole=read_geometry(comp)[2]['custom_mass_measure'];portion=read_geometry(result)[2]['custom_mass_measure']
        result['CustomMassKg']=comp['CustomMassKg']*portion/whole
    return result


def control_direction(definition):
    """Positive BeamNG input steers right, independent of rack placement/axis.

    Solve both rigid linkages instead of assuming the tie rods are ahead of
    the axle. Use the change in toe so a reviewed static toe offset cannot
    reverse the inferred direction.
    """
    from vehicle_templates import TemplateModel,Mechanism
    model=TemplateModel(definition)
    step=min(.001,float(definition['steering']['half_travel_m'])*.1)
    if not math.isfinite(step) or step<=0:raise ValueError('Rack travel must be positive and finite')
    gains={}
    for corner in ('FL','FR'):
        linkage=Mechanism(model,corner);angles=[]
        for stroke in (-step,0.,step):
            _,pose=linkage.solve(0,stroke)
            axis=pose['hub_axis']-pose['hub'];axis*=1 if axis[0]>=0 else -1
            angles.append(math.atan2(axis[1],axis[0]))
        slopes=np.diff(np.unwrap(angles))/step
        if not np.isfinite(slopes).all() or min(abs(slopes))<1e-3 or slopes[0]*slopes[1]<=0:
            raise ValueError(corner+': rack steering direction is ambiguous; review the tie rod geometry')
        gains[corner]=float(np.mean(slopes))
    if gains['FL']*gains['FR']<=0:
        raise ValueError('Rack steers the front wheels in opposite directions; review the tie rod geometry')
    return dict(input_to_rack_sign=-1 if gains['FL']>0 else 1,toe_gain_rad_per_m=gains)


def generate(graph,project,definition,mount_points,hydros):
    declaration=definition['steering'];owner=declaration['component'];u=np.array(declaration['axis']);travel=declaration['half_travel_m']
    control=control_direction(definition)
    speed=travel_speed(declaration.get('speed_m_s',.1))
    housing=member_component(project,owner,declaration['housing_member']);slider=member_component(project,owner,declaration['rack_member'])
    logical=next(v for v in project['Components'] if v['Id']==owner)
    total=c.read_geometry(logical)[1][0];parts=[c.read_geometry(comp)[1][0] for comp in (housing,slider)]
    if min(parts)<=0 or abs(sum(parts)-total)>max(1e-6,total*1e-6):raise ValueError('Rack member masses do not partition the complete CAD group')
    left=np.array(definition['hardpoints']['FL']['tie_inner']);right=np.array(definition['hardpoints']['FR']['tie_inner'])
    center=(left+right)/2
    # The third locator prevents free rotation about the rack axis. Its offset
    # is derived from the CAD inertia extent and owns only fitted existing mass.
    _,_,inertia=c.read_geometry(slider)[1];eigen,vectors=np.linalg.eigh(inertia)
    side=max((v-u*(u@v) for v in vectors.T),key=np.linalg.norm);side/=np.linalg.norm(side)
    offset=max(.01,min(.04,math.sqrt(max(eigen)/parts[1])))
    slider_points={'FL_tie_inner':left,'FR_tie_inner':right,owner+'_rack_roll':center+side*offset}
    housing_points={owner+'_mount_'+str(i):np.array(p) for i,p in enumerate(mount_points)}
    rails={}
    for index,(name,p) in enumerate(slider_points.items()):
        rail=owner+'_rail_'+str(index);a=rail+'_a';b=rail+'_b';rails[name]=(rail,a,b)
        housing_points[a]=p-u*(travel+.005);housing_points[b]=p+u*(travel+.005)
    actuator_parent=owner+'_rack_actuator_base'
    actuator_opposite=owner+'_rack_actuator_opposite'
    actuator_slider=owner+'_rack_actuator'
    # Apply the numerical actuator at the midpoint of the two rack endpoints.
    # A single-ended drive unnecessarily sends all control force through one
    # tie-rod node. This point stays on the same force line, introduces no extra
    # rail or control DOF, and receives only redistributed CAD member mass.
    slider_points[actuator_slider]=center
    actuator_length=max(.12,travel*3)
    housing_points[actuator_parent]=center-u*actuator_length
    housing_points[actuator_opposite]=center+u*actuator_length
    housing_nodes,housing_mesh=graph.rigid_component(housing,housing_points)
    slider_nodes,slider_mesh=graph.rigid_component(slider,slider_points,shared=['FL_tie_inner','FR_tie_inner'])
    graph.part.setdefault('rails',{})
    rows=graph.part.setdefault('slidenodes',[['id:','railName']])
    for name,(rail,a,b) in rails.items():
        graph.part['rails'][rail]={'links:':[a,b],'looped':False,'capped':True}
        # The assembled budget includes these transverse guides and their end
        # stops with the actual endpoint masses. A separate local frequency /
        # neighbour-count cap discards available stiffness before that solve,
        # allowing road loads to tilt/translate the rack unnecessarily.
        rows.append([name,rail,dict(attached=True,fixToRail=True,tolerance=0,spring=2e6,strength=1e30,capStrength=1e30)])
    # Native rates advance relative beam length per second. Specify physical
    # rack speed so changing the numerical actuator length cannot change slew.
    # Opposed supports avoid an arbitrary actuator side breaking the numerical
    # housing symmetry. Both target the SAME rack coordinate; each receives half
    # the existing holding stiffness/damping, with no added material or DOF.
    actuators=[]
    for parent,sign in ((actuator_parent,1),(actuator_opposite,-1)):
        hydros.append([parent,actuator_slider,dict(inputSource='steering_input',factor=sign*control['input_to_rack_sign']*travel/actuator_length,
                      inRate=speed/actuator_length,outRate=speed/actuator_length,autoCenterRate=speed/actuator_length,
                      beamSpring=750000,beamDamp=30,beamDeform=1e30,beamStrength=1e30)])
        actuators.append(dict(nodes=[parent,actuator_slider],rest_length_m=actuator_length,rack_motion_sign=sign))
    # The two halves represent one actuator. Budget their holding response as
    # one physical setting even when the surrounding vehicle is asymmetric.
    graph.part.setdefault('cadConstraintGroups',{})[owner+'_rack_hold']={'hydros':[a['nodes'] for a in actuators]}
    allocations={}
    for member,names in ((housing,housing_nodes),(slider,slider_nodes)):
        weights=graph.mass_allocations.pop(member['Id'])
        graph.rigid_member_allocations[member['Id']]=dict(owner=owner,weights=weights)
        for name,weight in weights.items():allocations[name]=allocations.get(name,0)+weight
        for name in names:
            if graph.owners[name]==member['Id']:graph.owners[name]=owner
    graph.mass_allocations[owner]=allocations;graph.groups[owner]=list(dict.fromkeys(housing_nodes+slider_nodes))
    graph.reports[owner]=dict(target_mass_kg=total,actual_mass_kg=sum(allocations.values()),representation='native CAD housing and translating rack',
                             housing_mass_kg=parts[0],rack_mass_kg=parts[1])
    graph.moving_render=getattr(graph,'moving_render',{})
    graph.moving_render[owner]=[dict(meshes=housing_mesh,group=housing['Id']+'_structure'),dict(meshes=slider_mesh,group=slider['Id']+'_structure')]
    graph.steering_contract=dict(kind='translating_rack',axis=u.tolist(),half_travel_m=travel,speed_m_s=speed,**control,
                                actuator_nodes=[actuator_parent,actuator_slider],actuator_rest_length_m=actuator_length,
                                actuators=actuators,
                                actuation_location='rack_endpoint_midpoint',
                                slider_nodes=slider_nodes,housing_nodes=housing_nodes,
                                rail_nodes={rail:[a,b] for rail,a,b in rails.values()},
                                rail_sliders={name:rail for name,(rail,a,b) in rails.items()})
    return graph.groups[owner],housing_mesh+slider_mesh
