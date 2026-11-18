"""Template graphs from CAD-owned components and explicit semantic hardpoints.

This module has no synthetic-case or vehicle-specific branch. The native recipe
harness supplies the same declarations and geometry used by a tagged CAD project.
"""
from __future__ import annotations
import copy
import itertools
import math
from pathlib import Path
import sys
import tempfile
import numpy as np
from scipy.spatial import Delaunay
import components as c
import shaft_chains
from frame_harness.build import node_table, beam_table
from frame_harness.calibration import fit_masses
from frame_harness.projection import axial_columns, project_springs, reduced_mass_damping

for root in (Path(__file__).parent/'calibration/Vehicle Wizard',Path(__file__).resolve().parents[2]/'dependencies/cad-calibration/Vehicle Wizard'):
    if root.is_dir():sys.path.insert(0,str(root));break
from vehicle_wizard.kinematics import Mechanism


class TemplateModel:
    def __init__(self,definition):
        self.definition=definition
        self.data={'parameters':dict(travel_m=.16,steer_degrees=28)|definition.get('parameters',{}),
                   'steering':definition.get('steering',{}),
                   'corners':{corner:dict(template=definition['templates']['front_suspension' if corner[0]=='F' else 'rear_suspension'],links=[]) for corner in definition['hardpoints']}}
    def corner_points(self,corner):return {name:np.asarray(value,float) for name,value in self.definition['hardpoints'][corner].items()}


def frame_mounts(definition):
    mounts={}
    for corner,points in definition['hardpoints'].items():
        template=definition['templates']['front_suspension' if corner[0]=='F' else 'rear_suspension']
        keys=['shock_top']
        if template=='double_wishbone':keys+=['upper_inner_front','upper_inner_rear','lower_inner_front','lower_inner_rear','tie_inner']
        elif template=='trailing_arm':keys+=['hinge_inner','hinge_outer']
        elif template=='trailing_radius_toe':keys+=['hinge_inner','hinge_outer','radius_upper_inner','radius_lower_inner','tie_inner']
        elif template=='trailing_ball_radius_toe':keys+=['trailing_ball','radius_upper_inner','radius_lower_inner','tie_inner']
        else:raise ValueError('Unsupported suspension template '+template)
        if corner.startswith('F') and definition.get('steering',{}).get('kind')=='translating_rack':keys.remove('tie_inner')
        for key in keys:mounts[corner+'_'+key]=points[key]
    if 'attachment_contract' in definition:
        for mount in definition['attachment_contract']:
            if mount['parent']==definition['frame_component']:mounts['fastener_'+mount['id']]=mount['position']
    else:
        for owner,points in definition.get('fixed_mounts',{}).items():
            for index,point in enumerate(points):mounts[owner+'_'+str(index)]=point
    return mounts


def resolved_wheel_datums(definition):
    """Unbound v2 wheel ports use the suspension's declared hub and positive axis."""
    spec = definition['driveline']
    if spec.get('version') != 2:
        return spec
    spec = copy.deepcopy(spec)
    endpoints = {e['id']: e for e in spec['endpoints']}
    for device in spec['devices']:
        if device['type'] != 'wheel':
            continue
        for port in device['ports']:
            endpoint = endpoints.get(port['endpoint'])
            if endpoint is not None and endpoint.get('axis') is None:
                points = definition['hardpoints'][device['wheel']]
                axis = np.asarray(points['hub_axis']) - points['hub']
                if np.linalg.norm(axis) < 1e-8:
                    raise ValueError(device['id'] + ': suspension hub axis is undefined')
                if endpoint.get('position') is None:endpoint['position']=list(points['hub'])
                endpoint['axis']=(axis / np.linalg.norm(axis)).tolist()
    return spec


def frame_mount_plan(definition,components):
    """Only release mounts need a short, separate parent-node patch.

    Structural point constraints already connect to the frame's existing nodes;
    unused locator cages must not consume CAD mass or the calibration budget.
    """
    if definition.get('driveline'):
        if any(definition.get(key) for key in ('shafts','halfshafts','shaft_chains','fixed_shafts')):raise ValueError('A driveline graph cannot also declare earlier shaft representations; migrate their ownership explicitly')
        from driveline import validate
        resolved=resolved_wheel_datums(definition)
        validate(resolved,dict(Components=components))
        shaft_owners={s['component'] for s in definition['driveline']['shafts']}
        housing_owners={d['component'] for d in definition['driveline']['devices'] if d['type']!='wheel'}
        endpoints={e['id']:e for e in resolved['endpoints']}
        for device in definition['driveline']['devices']:
            if device['type']!='wheel':continue
            endpoint=endpoints[device['ports'][0]['endpoint']];points=definition['hardpoints'][device['wheel']]
            hub=np.asarray(points['hub'],float);axis=np.asarray(points['hub_axis'],float)-hub
            if np.linalg.norm(axis)<1e-8:raise ValueError(device['id']+': suspension hub axis is undefined')
            axis/=np.linalg.norm(axis);declared=np.asarray(endpoint['axis'],float);declared/=np.linalg.norm(declared)
            if np.linalg.norm(np.cross(np.asarray(endpoint['position'])-hub,axis))>1e-4 or abs(axis@declared)<.999:
                raise ValueError(device['id']+': wheel port centre and axis must lie on its declared suspension hub axis')
        shaft_ends={e for s in definition['driveline']['shafts'] for e in (s['a'],s['b'])}
        housing_owners.update(endpoints[l['b'] if l['a'] in shaft_ends else l['a']]['component'] for l in definition['driveline']['connections'] if l['kind']=='bearing')
        fixed=set(definition.get('fixed_mounts',{}))
        if shaft_owners&fixed:raise ValueError('Shaft bodies cannot also be rigidly mounted to the chassis')
        if not housing_owners<=fixed:raise ValueError('Every driveline housing needs explicit reviewed mounts before calibration')
        for owner in housing_owners:
            points=np.asarray(definition['fixed_mounts'][owner],float)
            if points.ndim!=2 or points.shape[1]!=3 or len(points)<3 or not np.isfinite(points).all() or np.linalg.matrix_rank(points-points[0],tol=1e-8)<2:
                raise ValueError(owner+': driveline housing/carrier needs three finite, separated, non-collinear mounting sites')
    else:shaft_chains.validate(definition,components)
    fixed=definition.get('fixed_mounts',{})
    panel_owners={v['Id'] for v in components if v.get('Template')=='panel'}
    rigid_panels=set(definition.get('fixed_panel_components',[]))
    if not rigid_panels<=panel_owners&set(fixed):raise ValueError('Rigid panel declarations need existing panel components and fixed mount sites')
    short={owner+'_'+str(i) for owner,points in fixed.items() if owner in panel_owners-rigid_panels for i in range(len(points))}
    plan={name:dict(position=point,mode='short' if name in short else 'direct') for name,point in frame_mounts(definition).items()}
    for corner,points in definition['hardpoints'].items():
        for key in points:
            name=corner+'_'+key
            if name not in plan:continue
            plan[name]['mode']='joint'
            if key.startswith('hinge_'):plan[name]['reference_pair']=corner+'_hinge'
            elif key.endswith(('inner_front','inner_rear')):plan[name]['reference_pair']=corner+'_'+key.split('_')[0]
    for mount in definition.get('attachment_contract',[]):
        name='fastener_'+mount['id']
        if name in plan and mount['group']:plan[name].update(mode='short',attachment_length_m=mount['length'])
    return plan


def moment_points(moments):
    mass,center,inertia=moments
    covariance=(np.trace(inertia)/2*np.eye(3)-inertia)/mass
    eigen,axes=np.linalg.eigh(covariance)
    if min(eigen)<-1e-9:raise ValueError('CAD inertia is not physically realizable')
    # Off-axis samples span the covariance; principal-axis samples give the
    # positive fitter room to include loaded hardpoints of slender components.
    result=[center]
    # Off-axis samples permit mixed inertia terms from positive-mass hardpoints
    # to be balanced. Axis samples alone can force an off-axis node to zero mass.
    for signs in itertools.product((-1,1),repeat=3):
        result.append(center+axes@(np.sqrt(np.maximum(eigen,1e-10))*np.array(signs)*math.sqrt(2)))
    for axis,value in zip(axes.T,eigen):
        for scale in (math.sqrt(3),math.sqrt(6)):
            for sign in (-1,1):result.append(center+axis*max(math.sqrt(max(value,0)),.0003)*scale*sign)
    return result


def rigid_mass_points(moments,hardpoints):
    """Symmetric residual quadrature plus the mechanically required nodes.

    Subtract positive masses at the hardpoints from the CAD moments, then map a
    three opposite point pairs to the remaining covariance. This is a mass quadrature,
    not a collision hull. It avoids dozens of almost massless internal nodes.
    The residual covariance must retain margin in every principal direction.
    """
    mass,center,inertia=moments;points=np.asarray(hardpoints,float)
    covariance=(np.trace(inertia)/2*np.eye(3)-inertia)/mass
    eigen,axes=np.linalg.eigh(covariance)
    if mass<=0 or min(eigen)<=0:raise ValueError('Rigid CAD mass distribution must have positive volume')
    if not len(points):
        return np.asarray(center)+np.vstack((np.eye(3),-np.eye(3)))*np.sqrt(3*eigen)@axes.T,np.full(6,mass/6)
    inverse=(axes/np.sqrt(eigen))@axes.T
    share=.6
    for _ in range(80):
        weights=np.full(len(points),mass*share/len(points))
        remaining=mass-weights.sum();offset=points-center
        residual_center=-(weights@offset)/remaining
        residual=(mass*covariance-(offset.T*weights)@offset)/remaining-np.outer(residual_center,residual_center)
        if np.linalg.eigvalsh(inverse@residual@inverse)[0]>.15:break
        share*=.8
    else:raise ValueError('Hardpoints cannot carry positive mass within the CAD inertia')
    # Equal endpoint masses are a feasible starting point, but a remote ball
    # can otherwise starve every wheel-axis point. Increase individual masses
    # within the exact CAD moment cone, retaining every starting allocation.
    seed=weights/mass
    q=np.column_stack((np.ones(len(points)),(points-center)@inverse))
    def moment_residual(fractions):return np.eye(4)-(q.T*fractions)@q
    margin=min(.05,float(np.linalg.eigvalsh(moment_residual(seed))[0])*.75)
    # Smooth log-det barrier avoids differentiating repeated eigenvalues.
    # The old eigenvalue-constrained SLSQP could stop at different feasible
    # points for mirrored bodies, yielding different wheel-bearing masses.
    fractions=seed*1.00001
    def barrier(x,mu):
        residual=moment_residual(x)-margin*np.eye(4)
        if min(x-seed)<=0 or np.linalg.eigvalsh(residual)[0]<=0:return -np.inf
        return np.log(x).sum()+mu*(np.linalg.slogdet(residual)[1]+np.log(x-seed).sum())
    for mu in (1.,.1,.01,.001,.0001,.00001):
        for _ in range(100):
            residual=moment_residual(fractions)-margin*np.eye(4)
            influence=q@np.linalg.solve(residual,q.T)
            slope=1/fractions+mu/(fractions-seed)-mu*np.diag(influence)
            curvature=np.diag(1/fractions**2+mu/(fractions-seed)**2)+mu*influence**2
            direction=np.linalg.solve(curvature,slope)
            if slope@direction<1e-13:break
            step=1.;value=barrier(fractions,mu)
            while step>1e-14:
                candidate=fractions+step*direction
                if barrier(candidate,mu)>=value+1e-4*step*(slope@direction):break
                step*=.5
            if step<=1e-14:break
            fractions=candidate
    weights=fractions*mass
    remaining=mass-weights.sum();offset=points-center
    residual_center=-(weights@offset)/remaining
    residual=(mass*covariance-(offset.T*weights)@offset)/remaining-np.outer(residual_center,residual_center)
    eigen,axes=np.linalg.eigh(residual)
    pairs=np.vstack((np.eye(3),-np.eye(3)))*np.sqrt(3)
    extra=center+residual_center+(pairs*np.sqrt(eigen))@axes.T
    return np.vstack((points,extra)),np.r_[weights,np.full(6,remaining/6)]


def reaction_nodes(graph,owner,cvt_owner):
    """Use a broad triangle, independent of triangulator vertex ordering.

    The first pair defines the provisional crank axis toward the CVT. The third
    node must provide a real moment arm; adjacent wrap vertices can amplify a
    modest torque into thousands of newtons on tiny endpoint masses.
    """
    declared=getattr(graph,'drive_reaction_nodes',{}).get(owner)
    if declared:return declared
    names=sorted(graph.groups[owner]);xyz=np.array([graph.point(n) for n in names])
    mass=np.array([graph.nodes[n]['options']['nodeWeight'] for n in names])
    cvt_names=graph.groups[cvt_owner]
    cvt=np.average([graph.point(n) for n in cvt_names],axis=0,weights=[graph.nodes[n]['options']['nodeWeight'] for n in cvt_names])
    axis=np.array(getattr(graph,'drive_axes',{}).get(owner,cvt-np.average(xyz,axis=0,weights=mass)),float)
    if np.linalg.norm(axis)<1e-6:raise ValueError('Engine and CVT centers do not define a torque axis')
    axis/=np.linalg.norm(axis)
    pairs=np.array(list(itertools.combinations(range(len(names)),2)))
    delta=xyz[pairs[:,1]]-xyz[pairs[:,0]];length=np.linalg.norm(delta,axis=1)
    alignment=abs(delta@axis)/np.maximum(length,1e-12)
    score=np.where(alignment>.995,length**2*np.minimum(mass[pairs[:,0]],mass[pairs[:,1]]),0.)
    if score.max()<=0:raise ValueError('Engine representation has no separated node pair along its crank axis toward the CVT')
    a,b=map(int,pairs[np.argmax(score)])
    if np.dot(xyz[b]-xyz[a],axis)<0:a,b=b,a
    line=xyz[b]-xyz[a]
    area=np.linalg.norm(np.cross(line,xyz-xyz[a]),axis=1)
    third=int(np.argmax(area**2*mass))
    if area[third]<np.linalg.norm(np.ptp(xyz,axis=0))**2*.01:raise ValueError('Engine representation has no usable torque reaction triangle')
    return [names[a],names[b],names[third]]


def joint_supports(graph,owner,position):
    names=graph.groups[owner];delta=np.array([graph.point(n)-position for n in names])
    distance=np.linalg.norm(delta,axis=1);keep=np.flatnonzero(distance>1e-5)
    candidates=keep[np.argsort(distance[keep])[:24]]
    preferred=set(getattr(graph,'preferred_joint_supports',{}).get(owner,()))
    if preferred:
        candidates=np.unique(np.r_[candidates,[i for i in keep if names[i] in preferred]]).astype(int)
    triples=np.array(list(itertools.combinations(candidates,3)))
    unit=delta/np.maximum(distance[:,None],1e-12)
    score=np.abs(np.linalg.det(unit[triples]))/np.mean(distance[triples],axis=1)
    best=int(np.argmax(score))
    if abs(np.linalg.det(unit[triples[best]]))<.01:raise ValueError('No volumetric joint support on '+owner)
    if preferred:
        # Reuse already loaded mechanical sites when their support geometry is
        # comparable. Loading three new tessellation nodes otherwise requires
        # three additional numerical mass floors on an unchanged rigid body.
        viable=np.flatnonzero((score>=score[best]*.5)&(np.abs(np.linalg.det(unit[triples]))>=.01))
        best=min(viable,key=lambda i:(sum(names[j] not in preferred for j in triples[i]),-score[i],tuple(sorted(names[j] for j in triples[i]))))
    return [names[i] for i in triples[best]]


def wheel_reaction_nodes(graph,owner,axis_direction=1):
    """Maximize complete transverse recoil inertia using existing housing nodes."""
    dedicated=getattr(graph,'drive_reaction_nodes',{}).get(owner)
    if dedicated:
        a,b,third=dedicated
        if (graph.point(b)[0]-graph.point(a)[0])*axis_direction<0:a,b=b,a
        return dict(torqueCoupling=a,torqueArm=third,torqueArm2=b)
    names=sorted(graph.groups[owner]);xyz=np.array([graph.point(n) for n in names])
    mass=np.array([graph.nodes[n]['options']['nodeWeight'] for n in names])
    pairs=np.array(list(itertools.combinations(range(len(names)),2)))
    delta=xyz[pairs[:,1]]-xyz[pairs[:,0]];length=np.linalg.norm(delta,axis=1)
    # The output axis follows the wheel's outboard-to-inboard ordering.
    alignment=abs(delta[:,0])/np.maximum(length,1e-12)
    aligned=pairs[alignment>.95]
    if not len(aligned):raise ValueError('Differential representation lacks a transverse output axis: '+owner)
    candidates=[]
    for a,b in aligned:
        if (xyz[b,0]-xyz[a,0])*axis_direction<0:a,b=b,a
        axis=xyz[b]-xyz[a]
        arm=np.linalg.norm(np.cross(axis,xyz-xyz[a]),axis=1)/np.linalg.norm(axis)
        axial=(xyz-xyz[a])@axis/np.dot(axis,axis)
        for third in np.flatnonzero(arm>=.01):
            triangle=dict(torqueCoupling=names[a],torqueArm=names[third],torqueArm2=names[b])
            candidates.append((reaction_inertia(graph,triangle),abs(axial[third]),triangle))
    if not candidates:raise ValueError('Differential representation lacks a torque moment arm: '+owner)
    best=max(value for value,_,_ in candidates)
    # Equivalent triangles use the lever nearest that halfshaft's axis origin,
    # preserving mirrored left/right reactions and deterministic node ordering.
    tied=[(axial,tuple(triangle.values()),triangle) for value,axial,triangle in candidates
          if np.isclose(value,best,rtol=1e-10,atol=1e-14)]
    return min(tied,key=lambda entry:entry[:2])[2]


def reaction_inertia(graph,triangle):
    names=[triangle[k] for k in ('torqueCoupling','torqueArm','torqueArm2')]
    mass=np.array([graph.nodes[n]['options']['nodeWeight'] for n in names]);xyz=np.array([graph.point(n) for n in names])
    xyz-=mass@xyz/mass.sum()
    tensor=sum(m*(np.dot(p,p)*np.eye(3)-np.outer(p,p)) for m,p in zip(mass,xyz))
    value=1/np.linalg.solve(tensor,np.array([1.,0,0]))[0]
    if not math.isfinite(value) or value<=0:raise ValueError('Drive reaction triangle has no positive rotational inertia')
    return float(value)


def brake_reaction_node(graph,owner,axis_nodes):
    """Choose a well-supported torque lever on the actual wheel carrier.

    A named ball joint is not always a useful brake-reaction lever. Evaluate
    the full triangle's effective inertia using existing final node masses.
    """
    a,b=axis_nodes;axis=graph.point(b)-graph.point(a);axis/=np.linalg.norm(axis)
    candidates=[]
    for node in sorted(graph.groups[owner]):
        if node in axis_nodes:continue
        names=[a,b,node];mass=np.array([graph.nodes[n]['options']['nodeWeight'] for n in names])
        xyz=np.array([graph.point(n) for n in names]);xyz-=mass@xyz/mass.sum()
        arm=np.linalg.norm(np.cross(axis,graph.point(node)-graph.point(a)))
        if arm<.001:continue
        tensor=sum(m*(np.dot(p,p)*np.eye(3)-np.outer(p,p)) for m,p in zip(mass,xyz))
        inertia=1/float(axis@np.linalg.solve(tensor,axis))
        candidates.append((inertia,node))
    if not candidates:raise ValueError('Wheel carrier has no usable brake torque lever: '+owner)
    best=max(v[0] for v in candidates)
    return next(n for value,n in candidates if np.isclose(value,best,rtol=1e-10,atol=1e-14))


class Structure:
    def __init__(self,frame,frame_owner='frame'):
        self.frame_owner=frame_owner
        self.part=copy.deepcopy(frame);self.nodes=node_table(self.part);self.frame_ids=list(self.nodes)
        self.beams=beam_table(frame);self.new_beams=[];self.groups={};self.reports={};self.owners={n:frame_owner for n in self.nodes};self.spectral_edges=set();self.collision_edges=set()
        for v in self.nodes.values():
            groups=v['options'].get('group',[])
            v['options']['group']=list(dict.fromkeys((groups if isinstance(groups,list) else [groups])+['frame_structure']))
            # The wrapped frame is an external envelope spanning empty space
            # between tubes. Its nodes cannot serve as internal contact points
            # against attached panels/housings within the native contact skin.
            # Keep terrain/other-vehicle collision and the sealed material graph.
            v['options']['selfCollision']=False
        self.collision_policy=dict(frame_representation='external_wrapped_envelope',
            frame_nodes={n:dict(self_collision=False,collision=v['options'].get('collision',True),
                               static_collision=v['options'].get('staticCollision',True)) for n,v in self.nodes.items()},
            limitation='Wrapped frame envelope does not model internal contact with attached or detached components')
        self.part['nodes']=[['id','posX','posY','posZ']]+[[n,*v['position'],v['options']] for n,v in self.nodes.items()]
        self.frame_joint_nodes={name:p['parents'][0] for name,p in self.part.get('cadMountPatches',{}).items() if p.get('mode')=='joint'}
        self.groups[frame_owner]=self.frame_ids.copy();self.joints=[];self.mounts=[];self.connection_torsions=[]
        self.spherical_constraint_rows=[];self.steering_constraints=[]
        self.mass_allocations={frame_owner:{n:v['options']['nodeWeight'] for n,v in self.nodes.items()}}
        self.rigid_owners=set();self.fixed_owners=set();self.fixed_attachment_contract={}
        self.rigid_member_allocations={}
        self.rigidifier_nodes=set()
        self.axial_rigid_owners=set()
    def point(self,name):return np.array(self.nodes[name]['position'])
    def beam(self,a,b,**options):
        if np.linalg.norm(self.point(a)-self.point(b))<1e-7:raise ValueError('Coincident beam '+a+'/'+b)
        self.new_beams.append([a,b,dict(beamSpring=180000.,beamDamp=40.,beamDeform=1e30,beamStrength=1e30,beamPrecompression=1,breakGroup='')|options])
    def rigid_component(self,component,required,shared=()):
        owner=component['Id'];meshes,moments,_=c.read_geometry(component)
        if moments[0]<=0:raise ValueError('Mechanism components require positive CAD mass: '+owner)
        required=dict(required)
        if getattr(self,'wishbone_representation','cad_moments')=='rigidifier' and component.get('MvpRole','').endswith('_wishbone'):
            points=np.asarray(list(required.values()),float)
            _,_,axes=np.linalg.svd(points-points.mean(0),full_matrices=True)
            normal=axes[-1];radius=.25*float(np.linalg.norm(np.ptp(points,axis=0)))
            if radius<.01:raise ValueError('Wishbone is too small for a separated rigidifier pair')
            for index,sign in enumerate((-1,1)):
                name=owner+'_rigidifier_'+str(index)
                required[name]=np.asarray(moments[1])+sign*radius*normal
                self.rigidifier_nodes.add(name)
        names=list(required)
        role=component.get('MvpRole','')
        minimal=(role.endswith('_wishbone') and getattr(self,'wishbone_representation','hardpoint_lumped')=='hardpoint_lumped'
                 or role.endswith('_trailing_arm') and getattr(self,'trailing_arm_representation','hardpoint_lumped')=='hardpoint_lumped'
                 or role.endswith('_upright') and getattr(self,'upright_representation','cad_moments')=='hardpoint_lumped')
        if minimal:
            from rigid_point_mass import distribute
            xyz,masses,report=distribute(moments,list(required.values()))
        else:
            xyz,importance=rigid_mass_points(moments,list(required.values()))
            names.extend(owner+'_mass_'+str(index) for index in range(len(xyz)-len(names)))
            masses,report=fit_masses(xyz,*moments,minimum_weights=importance)
            report['representation']='Required hardpoints and six symmetric residual-moment quadrature nodes'
            report['allocation_method']='Log-det constrained positive hardpoint mass fit; three opposite residual point pairs preserve mass, COM and inertia'
            if not report['accepted']:raise ValueError(owner+': fixed representation cannot fit CAD mass/COM/inertia')
        spec=getattr(self,'reaction_graph',None)
        if spec is not None and owner in self.reaction_owners:
            from driveline_physics import housing_points
            extra=housing_points(spec,owner,xyz)
            if extra:
                if set(extra)&set(required):raise ValueError(owner+': cannot form reaction triangle on declared axis')
                return self.rigid_component(component,required|extra,shared)
        edges=list(itertools.combinations(range(len(xyz)),2))
        columns,_,_=axial_columns(xyz,edges)
        if not minimal and np.linalg.matrix_rank(columns,tol=1e-8)!=3*len(xyz)-6:raise ValueError(owner+': rigid representation has an internal mechanism')
        from rigid_bracing import reinforce
        springs,dampers,torsions=reinforce(xyz,edges,masses)
        if minimal:
            from rigid_bracing import gradient
            angular=[]
            for ids,_,_ in torsions:
                column=np.zeros_like(xyz);column[ids]=gradient(xyz[ids]);angular.append(column.ravel())
            rigidity=np.column_stack([columns,*angular]) if angular else columns
            if np.linalg.matrix_rank(rigidity,tol=1e-8)!=3*len(xyz)-6:
                raise ValueError(owner+': minimal rigid member has an internal mechanism')
        for name,point,mass in zip(names,xyz,masses):
            if name in self.nodes:
                if name not in shared or not np.allclose(self.point(name),point,atol=1e-9,rtol=0):
                    raise ValueError('Duplicate or displaced shared physical node '+name)
                self.nodes[name]['options']['nodeWeight']+=float(mass)
                self.nodes[name]['options']['group'].append(owner+'_structure')
                continue
            opts=dict(nodeWeight=float(mass),collision=False,selfCollision=False,group=[owner+'_structure'])
            self.nodes[name]=dict(position=point.tolist(),options=opts);self.owners[name]=owner
            self.part['nodes'].append([name,*point.tolist(),opts])
        # A hinge-axis edge already supplied by the chassis is not a second
        # arm beam. Reuse its structural restraint without editing its tuning.
        frame_edges={frozenset((b['a'],b['b'])) for b in self.beams
                     if b['a'] in self.frame_ids and b['b'] in self.frame_ids}
        reused=[]
        for (a,b),spring,damper in zip(edges,springs,dampers):
            if minimal and frozenset((names[a],names[b])) in frame_edges:
                reused.append([names[a],names[b]])
                continue
            self.beam(names[a],names[b],beamSpring=float(spring),beamDamp=float(damper))
            self.spectral_edges.add((names[a],names[b]))
        if minimal:
            report.update(reused_chassis_edges=reused,mechanical_node_count=len(names),
                          auxiliary_node_count=0,added_internal_beam_count=len(edges)-len(reused))
        self.part.setdefault('torsionbars',[['id1:','id2:','id3:','id4:']]).extend(
            [[*[names[i] for i in ids],dict(spring=k,damp=d,deform=1e30,strength=1e30)] for ids,k,d in torsions])
        self.groups[owner]=names;self.reports[owner]=report
        self.mass_allocations[owner]=dict(zip(names,map(float,masses)))
        self.rigid_owners.add(owner)
        return names,meshes
    def rebudget_carrier(self,owner,wheel_owner):
        """Use assembled support masses in the carrier's numerical rigidity fit.

        Keep CAD ownership/moments unchanged. A shared physical pivot has the
        sum of its owners' masses. The final assembled tangent audit, including
        the sealed frame and every body, still rejects an excessive eigenvalue.
        """
        names=self.groups[owner];allocation=self.mass_allocations[wheel_owner]
        if not set(allocation)<=set(names) or any(m<0 for m in allocation.values()):
            raise ValueError('Wheel mass must belong to its carrier axle nodes')
        if all(self.nodes[n]['options']['nodeWeight']==self.mass_allocations[owner][n] for n in names):return
        edges=list(itertools.combinations(range(len(names)),2))
        internal={(a,b):options for a,b,options in self.new_beams if a in names and b in names}
        existing_frame={frozenset((b['a'],b['b'])) for b in self.beams
                        if b['a'] in self.frame_ids and b['b'] in self.frame_ids}
        if {frozenset(pair) for pair in internal}|{pair for pair in existing_frame if pair<=set(names)}!={frozenset((names[a],names[b])) for a,b in edges}:
            raise ValueError('Carrier reinforcement requires its complete, unique rigid graph')
        masses=np.array([self.nodes[n]['options']['nodeWeight'] for n in names])
        from rigid_bracing import reinforce
        springs,dampers,torsions=reinforce(np.array([self.point(n) for n in names]),edges,masses)
        for (a,b),spring,damper in zip(edges,springs,dampers):
            if (names[a],names[b]) not in internal:continue
            internal[names[a],names[b]].update(beamSpring=float(spring),beamDamp=float(damper))
        rows=self.part['torsionbars']
        self.part['torsionbars']=rows[:1]+[r for r in rows[1:] if not set(r[:4])<=set(names)]+[
            [*[names[i] for i in ids],dict(spring=k,damp=d,deform=1e30,strength=1e30)] for ids,k,d in torsions]
        self.reports[owner]['rigidity_mass_budget']=dict(component_mass_kg=sum(self.mass_allocations[owner].values()),
            additional_owner=wheel_owner,additional_mass_kg=sum(allocation.values()),
            assembled_node_masses_kg=dict(zip(names,map(float,masses))),
            scope='Numerical rigid-carrier fit uses assembled pivot/axle masses; full coupled tangent audited; CAD ownership unchanged')
    def geometry_component(self,component,points,scratch,cgal):
        if component.get('Method')=='rigid':
            result=self.rigid_component(component,{component['Id']+'_mount_'+str(i):p for i,p in enumerate(points)})
            self.reports[component['Id']]['render_as_rigid_prop']=True
            return result
        anchors=[dict(Id=str(i),Name=component['Name']+' mount '+str(i),Status='resolved',Position=p) for i,p in enumerate(points)]
        part,report=c.generate_component(component,anchors,Path(scratch)/component['Id'],cgal)
        if component.get('_DrivelineHousing') and getattr(self,'reaction_graph',None):
            from driveline_physics import housing_points
            existing=[node['position'] for node in node_table(part).values()]
            extra=housing_points(self.reaction_graph,component['Id'],existing)
            if extra:
                points=list(points)+list(extra.values())
                anchors=[dict(Id=str(i),Name=component['Name']+' mount '+str(i),Status='resolved',Position=p) for i,p in enumerate(points)]
                part,report=c.generate_component(component,anchors,Path(scratch)/component['Id']/'reaction-sites',cgal)
        rigid_housing=component.get('_DrivelineHousing',False) or component.get('MvpRole') in ('engine','cvt','front_diff','rear_diff','rear_final_drive','shaft_carrier')
        compact_solid=(component.get('Template')=='bulk' and
                       report.get('settings',{}).get('wrap',{}).get('selected_method')=='exact_convex_solid' and
                       len(node_table(part))<=32)
        if rigid_housing or compact_solid:
            # A compact solid carries mounting and drive reactions. Its
            # collision shell is not a thin deformable panel: sparse shell
            # diagonals and per-node collision caps can let the casing fold.
            # Keep the CAD-fitted masses, node positions and collision surface,
            # but jointly budget its axial/angular rigid-template load paths.
            housing_nodes=node_table(part);housing_names=list(housing_nodes)
            if len(housing_names)>32:
                raise ValueError('Powertrain housing needs a compact rigid load skeleton before its collision skin: '+component['Id'])
            xyz=np.array([housing_nodes[n]['position'] for n in housing_names]);mass=np.array([housing_nodes[n]['mass'] for n in housing_names])
            if points:
                # Mounts carry external reactions as well as the body's internal
                # constraints. Double their priority relative to the existing
                # CAD mass allocation. Preserve the other nodes' relative
                # support instead of restarting with uniform priorities.
                # This is numerical load support, not added ballast or a claim
                # that every hardpoint can contain a fixed number of kilograms.
                loaded={component['Id']+'_mount_'+str(i) for i in range(len(points))}
                if not loaded<=set(housing_names):raise ValueError('Housing mount node is missing')
                priority=mass*np.array([2. if n in loaded else 1. for n in housing_names])
                mass,mass_report=fit_masses(xyz,*c.read_geometry(component)[1],minimum_weights=priority)
                if not mass_report['accepted']:raise ValueError('Loaded housing cannot preserve CAD mass properties: '+component['Name'])
                mass_report['load_support']=dict(priority=2.,basis='existing CAD mass allocation',nodes=sorted(loaded),
                    scope='Prioritize mount nodes while fitting the same CAD mass, COM and inertia')
                report['mass']=mass_report
                by_name=dict(zip(housing_names,map(float,mass)))
                for row in part['nodes'][1:]:
                    if isinstance(row,list):row[-1]['nodeWeight']=by_name[row[0]]
            if component.get('_ExperimentalReactionSupport'):
                from reaction_support import allocate
                retained=[name.startswith(component['Id']+'_mount_') for name in housing_names]
                kept,added,added_mass,support_report=allocate(c.read_geometry(component)[1],xyz,mass,retained,
                    axis=component.get('_ReactionAxis',(1.,0.,0.)),minimum=component.get('_ReactionMinimumMass',2.))
                mass=kept.copy();added_names=[]
                for index,(position,value) in enumerate(zip(added,added_mass)):
                    matches=np.flatnonzero(np.linalg.norm(xyz-position,axis=1)<1e-7)
                    if len(matches):
                        target=int(matches[0]);mass[target]+=value;added_names.append(housing_names[target])
                        continue
                    name=component['Id']+'_drive_support_'+str(index)
                    housing_names.append(name);added_names.append(name)
                    xyz=np.vstack((xyz,position));mass=np.r_[mass,value]
                    part['nodes'].append([name,*position.tolist(),dict(nodeWeight=float(value),collision=False,
                        staticCollision=False,selfCollision=False,group=[component['Id']+'_structure'])])
                by_name=dict(zip(housing_names,map(float,mass)))
                for row in part['nodes'][1:]:
                    if isinstance(row,list):row[-1]['nodeWeight']=by_name[row[0]]
                if not hasattr(self,'drive_reaction_nodes'):self.drive_reaction_nodes={}
                self.drive_reaction_nodes[component['Id']]=added_names[:3]
                report['mass']['drive_reaction_support']=support_report
            edges=list(itertools.combinations(range(len(xyz)),2))
            from rigid_bracing import reinforce
            # Three-dimensional solids already have full axial rigidity.
            # Reserve angular braces for thin mechanisms; oblique torsion
            # levers on a dense solid introduce unnecessary native dynamics.
            springs,dampers,torsions=reinforce(xyz,edges,mass,angular=False)
            part['beams']=[['id1:','id2:']]+[[housing_names[a],housing_names[b],dict(beamSpring=float(k),beamDamp=float(d),beamDeform=1e30,beamStrength=1e30)]
                for (a,b),k,d in zip(edges,springs,dampers)]
            part['torsionbars']=[['id1:','id2:','id3:','id4:']]+[[*[housing_names[i] for i in ids],dict(spring=k,damp=d,deform=1e30,strength=1e30)] for ids,k,d in torsions]
            self.spectral_edges.update((r[0],r[1]) for r in part['beams'][1:])
            report['load_representation']='Provisional compact axial rigid solid; CAD mass/COM/inertia and collision shell retained; rupture uncalibrated'
        owner=component['Id'];names=[]
        for name,node in node_table(part).items():
            if name in self.nodes:raise ValueError('Duplicate physical node '+name)
            names.append(name);self.nodes[name]=node;self.owners[name]=owner
            self.part['nodes'].append([name,*node['position'],node['options']])
        self.new_beams.extend(part['beams'][1:])
        self.collision_edges.update((b['a'],b['b']) for b in beam_table(part))
        self.part.setdefault('triangles',[['id1:','id2:','id3:']]).extend(part.get('triangles',[])[1:])
        self.part.setdefault('torsionbars',[['id1:','id2:','id3:','id4:']]).extend(part.get('torsionbars',[])[1:])
        self.groups[owner]=names;self.reports[owner]=report['mass']|{'representation':report}
        self.mass_allocations[owner]={n:self.nodes[n]['options']['nodeWeight'] for n in names}
        if rigid_housing or compact_solid:
            self.rigid_owners.add(owner);self.axial_rigid_owners.add(owner)
        return names,c.read_geometry(component)[0]
    def patch(self,name,child,release=None,strength=4000,damping=None,direct=False):
        patch=self.part.get('cadMountPatches',{}).get(name)
        if patch is None:raise ValueError('Recalibrate frame with the required mounting patch: '+name)
        if not np.allclose(self.point(child),patch['position'],atol=1e-7,rtol=0):raise ValueError('Mount moved after frame calibration: '+name)
        if patch.get('mode')=='joint':
            if child!=patch['parents'][0]:raise ValueError('Structural joint did not use the calibrated pivot: '+name)
            self.joints.append(dict(id=name,kind='shared_frame_pivot',parent=self.frame_owner,child=self.owners[child],nodes=[child]))
            return
        # Articulated suspension points are located by distances to the frame's
        # well-spaced structural supports. A second 6 mm locator cage adds small
        # masses and two compliant joints in series without adding a DOF.
        parents=patch['frame_supports'] if direct else patch['parents']
        for parent in parents:
            self.beam(parent,child,beamSpring=2000000 if direct else 180000,breakGroup=release or '',beamStrength=strength if release else 1e30,
                      breakGroupType=0,disableMeshBreaking=True,disableTriangleBreaking=True,
                      **(dict(beamDamp=damping,dampCutoffHz=0) if damping is not None else {}))
        if release:
            self.mounts.append(dict(id=name,name=name,group=release,parent=self.frame_owner,child=self.owners[child],
                                    edges=[[parent,child] for parent in patch['parents']],attachment_length_m=.006))
        self.joints.append(dict(id=name,kind='spherical',parent=self.frame_owner,child=self.owners[child],nodes=[*parents,child]))
    def spherical(self,name,parents,child,*,parent_owner):
        # Shared ball/hinge nodes may have been created by another component.
        # Their first owner is not the owner of this joint's support body.
        if (len(parents)!=3 or len(set(parents))!=3 or
            not set(parents)<=set(self.groups.get(parent_owner,()))):
            raise ValueError('Spherical supports must belong to the declared parent: '+name)
        for parent in parents:self.beam(parent,child,beamSpring=500000)
        # Thin parent structures need an angular constraint to locate the ball
        # perpendicular to their plane; three long axial distances alone have
        # very little tangent stiffness in that direction.
        from rigid_bracing import point_constraint
        names=[*parents,child];xyz=np.array([self.point(n) for n in names])
        masses=np.array([self.nodes[n]['options']['nodeWeight'] for n in names])
        ids,k,d=point_constraint(xyz,masses)
        options=dict(spring=k,damp=d,deform=1e30,strength=1e30)
        row=[*[names[i] for i in ids],options]
        self.part.setdefault('torsionbars',[['id1:','id2:','id3:','id4:']]).append(row)
        self.spherical_constraint_rows.append(row)
        self.connection_torsions.append(options)
        self.joints.append(dict(id=name,kind='spherical',parent=parent_owner,child=self.owners[child],nodes=[*parents,child]))
    def finish(self):
        from vehicle_conditioning import refit_joint_constraints
        self.joint_refits=refit_joint_constraints(self)
        for joint in self.joints:
            if joint['kind']=='shared_frame_pivot':
                owners=[owner for owner,allocation in self.mass_allocations.items() if owner!=self.frame_owner and joint['nodes'][0] in allocation]
                if not owners:raise ValueError('Structural pivot has no attached component: '+joint['id'])
                joint['child']=owners[0];joint['child_components']=owners
        # Limit added springs using all incident constraints and final endpoint
        # masses. The calibrated frame's own springs and masses stay unchanged.
        constraints=self.new_beams+[row for row in self.part.get('hydros',[])[1:] if isinstance(row,list)]
        degree={n:0 for n in self.nodes}
        for a,b,_ in constraints:degree[a]+=1;degree[b]+=1
        connections=self.connection_torsions.copy()
        if getattr(self,'condition_rigid_bodies',False):
            if getattr(self,'frame_reference_hz',0):
                from frame_reference import fit
                frame_options,self.frame_reference=fit(self.part,self.frame_ids,self.frame_reference_hz)
                connections.extend(frame_options)
            else:
                from vehicle_conditioning import condition_frame_locators
                locator_options,self.frame_locator_conditioning=condition_frame_locators(self.part,self.nodes,self.frame_ids)
                connections.extend(locator_options)
        for a,b,options in constraints:
            # These complete rigid-body blocks already satisfy the coupled
            # stiffness/damping bound with half the step budget reserved for
            # external constraints. A second degree cap selectively softens
            # their loaded axes and destroys the designed angular/axial ratio.
            if (a,b) in self.spectral_edges:continue
            if options.get('beamType') in ('|BOUNDED','|SUPPORT'):continue
            ma=self.nodes[a]['options']['nodeWeight'];mb=self.nodes[b]['options']['nodeWeight']
            # Collision envelopes contain thin, deformable tetrahedra. Retain
            # their direction-independent bound under contact deformation;
            # the rest-state spectral cap alone cannot protect a folding cell.
            if (a,b) in self.collision_edges:
                cap=min(ma/degree[a],mb/degree[b])*(2*math.pi*260)**2
                options['beamSpring']=min(options['beamSpring'],cap)
            # Normal constraints share the full assembled step budget below.
            # A separate 350 Hz edge cap discarded usable stiffness even when
            # the complete mass/stiffness/damping operator had ample margin.
            options['beamDamp']=min(options['beamDamp'],.6*math.sqrt(options['beamSpring']*ma*mb/(ma+mb)))
            connections.append(options)
        self.part['beams'].extend(self.new_beams)
        if getattr(self,'condition_rigid_bodies',False):
            from rigid_revision import refit
            from vehicle_conditioning import rigid_allocations
            allocations=rigid_allocations(self)
            self.rigid_refits={}
            for owner in sorted(self.rigid_owners):
                selected,self.rigid_refits[owner]=refit(self.part,allocations,owner,angular=owner not in self.axial_rigid_owners,
                    damping_budget=getattr(self,'rigid_damping_budget',2.),
                    priority_nodes=list(getattr(self,'numerical_mass',{}).get('nodes',{})),
                    priority=getattr(self,'wishbone_loaded_priority',1.) if owner in getattr(self,'wishbone_owners',set()) else 1.)
                connections.extend(selected)
            from fixed_structure import attach
            for owner in sorted(self.fixed_owners):
                rows,self.fixed_attachment_contract[owner]=attach(self.part,self.groups[owner],self.frame_ids)
                connections.extend(row[-1] for row in rows)
        from rigid_bracing import budget_connections
        self.connection_budget=budget_connections(self.part,self.nodes,connections)
        self.part['beams'].append(dict(beamType='|NORMAL',beamPrecompression=1,beamSpring=250000,beamDamp=40,beamDeform=1e30,beamStrength=1e30,breakGroup=''))
        return self.part


def wheel_options(mass,front,parameters,vehicle_mass):
    radius=parameters.get('tire_radius_m',.28);width=parameters.get('tire_width_m',.16)
    rim_width=float(parameters.get('rim_width_m',width*.85))
    if not math.isfinite(rim_width) or rim_width<=0:raise ValueError('Rim width must be positive')
    rays=parameters.get('tire_rays',16)
    if isinstance(rays,bool) or not isinstance(rays,int) or not 12<=rays<=32:
        raise ValueError('Tire rays must be an integer between 12 and 32')
    bias=float(parameters.get('front_brake_bias',.6));deceleration=float(parameters.get('brake_deceleration_g',1.))
    if not 0<bias<1 or not math.isfinite(deceleration) or deceleration<=0:raise ValueError('Invalid brake bias/deceleration target')
    # A template brake target scales with the actual vehicle, rather than
    # applying a passenger-car torque to lightweight suspension reaction nodes.
    brake=vehicle_mass*9.81*radius*deceleration*(bias if front else 1-bias)/2
    brake=float(parameters.get('front_brake_torque_nm' if front else 'rear_brake_torque_nm',brake))
    if not math.isfinite(brake) or brake<=0:raise ValueError('Brake torque must be finite and positive')
    carcass_damping=float(parameters.get('tire_carcass_damping_scale',1.))
    if not math.isfinite(carcass_damping) or not 0<carcass_damping<=8:
        raise ValueError('Tire carcass damping scale must be in (0, 8]')
    rim_stiffness=float(parameters.get('rim_stiffness_scale',.7))
    if not math.isfinite(rim_stiffness) or not 0<rim_stiffness<=1:
        raise ValueError('Rim stiffness scale must be in (0, 1]')
    belt_precompression=float(parameters.get('tire_belt_precompression',1.))
    side_precompression=float(parameters.get('tire_sidewall_precompression',1.))
    if any(not math.isfinite(value) or not .9<=value<=1 for value in (belt_precompression,side_precompression)):
        raise ValueError('Tire carcass precompression must be between 0.9 and 1')
    return dict(hubRadius=parameters.get('rim_radius_m',.16),radius=radius,hubWidth=rim_width,tireWidth=width,
                numRays=rays,hasTire=True,enableHubcaps=False,hubNodeWeight=mass*.45/(2*rays),nodeWeight=mass*.55/(2*rays),
                beamSpring=100000,beamDamp=10,beamDeform=50000,beamStrength=100000,beamPrecompression=1,
                tireSupportBeamSpring=100000,tireSupportBeamDamp=10,hubTreadBeamSpring=-rim_stiffness,hubPeripheryBeamSpring=-rim_stiffness,hubSideBeamSpring=-rim_stiffness,hubReinfBeamSpring=-rim_stiffness,
                hubTreadBeamDamp=-1,hubPeripheryBeamDamp=-1,hubSideBeamDamp=-1,hubReinfBeamDamp=-1,hubBeamDeform=40000,hubBeamStrength=80000,
                wheelSideBeamSpring=10200,wheelSideBeamDamp=8*carcass_damping,wheelSideBeamSpringExpansion=125000,wheelSideBeamDampExpansion=8*carcass_damping,
                wheelTreadBeamSpring=60000,wheelTreadBeamDamp=12*carcass_damping,wheelPeripheryBeamSpring=45000,wheelPeripheryBeamDamp=10*carcass_damping,
                # Pressure stretches an initially unloaded carcass. Explicit
                # rest-length tuning permits a pretensioned belt/sidewall;
                # these values change tire response, never CAD mass or inertia.
                wheelSideBeamPrecompression=side_precompression,wheelReinfBeamPrecompression=belt_precompression,
                wheelTreadBeamPrecompression=belt_precompression,wheelTreadReinfBeamPrecompression=belt_precompression,
                wheelPeripheryBeamPrecompression=belt_precompression,wheelPeripheryReinfBeamPrecompression=belt_precompression,
                # Documented pressure-tire carcass construction. Radial side
                # beams alone do not constrain lateral/tread shear adequately.
                # These are provisional tire properties, not CAD rubber data.
                enableTireLbeams=True,enableTireReinfBeams=False,enableTreadReinfBeams=True,enableTirePeripheryReinfBeams=True,
                wheelReinfBeamSpring=15000,wheelReinfBeamDamp=140,wheelReinfBeamDampCutoffHz=500,
                wheelTreadReinfBeamSpring=120000,wheelTreadReinfBeamDamp=40,wheelTreadReinfBeamDampCutoffHz=500,
                wheelPeripheryReinfBeamSpring=95000,wheelPeripheryReinfBeamDamp=23,wheelPeripheryReinfBeamDampCutoffHz=500,
                wheelSideBeamDeform=20000,wheelSideBeamStrength=50000,wheelTreadBeamDeform=20000,wheelTreadBeamStrength=50000,
                wheelPeripheryBeamDeform=40000,wheelPeripheryBeamStrength=60000,pressurePSI=parameters.get('tire_pressure_psi',12),
                nodeMaterial='|NM_RUBBER',hubNodeMaterial='|NM_METAL',hubFrictionCoef=.5,
                frictionCoef=1,slidingFrictionCoef=.95,triangleCollision=False,selfCollision=False,collision=True,dragCoef=5,
                brakeTorque=brake,parkingTorque=0 if front else brake,enableABS=False)


def wheel_support_mass(options,axis_masses,half_span,minimum=2.):
    """Put existing hub mass on loaded axle points without ballast.

    Move additional rim mass outward to retain spin inertia, and solve the
    internal hub-ring width to retain both transverse moments. The contact
    radius and tread width stay unchanged. This preserves the provisional tire
    model's moments; it does not claim CAD rubber-property calibration.
    """
    if not math.isfinite(minimum) or minimum<=0:raise ValueError('Wheel support minimum mass must be positive')
    options=dict(options);count=2*options['numRays']
    hub=count*options['hubNodeWeight'];tread=count*options['nodeWeight']
    added=max(0.,minimum-min(axis_masses));axle=2*added
    radius=options['radius'];rim=options['hubRadius'];width=options['tireWidth'];old_width=options['hubWidth']
    if radius<=rim or half_span<=0:raise ValueError('Wheel mass allocation requires a tire outside its rim and distinct axle nodes')
    outward=axle*rim**2/(radius**2-rim**2)
    remaining=hub-axle-outward;new_tread=tread+outward
    lateral_second=hub*(old_width/2)**2+tread*(width/2)**2
    hub_second=lateral_second-axle*half_span**2-new_tread*(width/2)**2
    if remaining<=1e-6 or hub_second<0:
        raise ValueError('Existing wheel hub mass cannot support the requested axle node mass while preserving inertia; revise the wheel representation or minimum mass')
    new_width=2*math.sqrt(hub_second/remaining)
    # A pressure-wheel bead may be wider than its tread (the documented
    # automotive construction). Bound excessive redistribution relative to
    # the declared cross-section, rather than forbidding that valid geometry.
    if new_width<=1e-6 or new_width>1.5*max(width,old_width):
        raise ValueError('Wheel support mass requires an invalid internal rim width')
    options.update(hubNodeWeight=remaining/count,nodeWeight=new_tread/count,hubWidth=new_width)
    return options,added,dict(minimum_support_node_kg=minimum,added_per_axle_node_kg=added,
        original_mass_kg=hub+tread,generated_mass_kg=remaining+new_tread,
        hub_width_before_m=old_width,hub_width_after_m=new_width,
        spin_inertia_kg_m2=hub*rim**2+tread*radius**2,
        transverse_second_moment_kg_m2=lateral_second,
        scope='Existing provisional wheel mass/COM/inertia preserved; no added ballast')


def cad_wheel_support_mass(options,axis_masses,half_span,moments,axis,minimum=2.):
    """Fit an axisymmetric pressure wheel to CAD mass and principal moments.

    The contact radius stays fixed. The ring widths represent mass distribution,
    not the maximum sidewall bulge. Reject infeasible fits instead of adding mass.
    """
    mass,center,inertia=moments;axis=np.asarray(axis,float);axis/=np.linalg.norm(axis)
    if not math.isfinite(minimum) or minimum<=0:raise ValueError('Wheel support minimum mass must be positive')
    spin=float(axis@inertia@axis);lateral=float((np.trace(inertia)-2*spin)/2)
    added=max(0.,minimum-min(axis_masses));axle=2*added;remaining=mass-axle
    radius=float(options['radius']);rim=float(options['hubRadius'])
    if not 0<rim<radius or half_span<=0:raise ValueError('Invalid CAD wheel radii or axle span')
    tread=(spin-remaining*rim**2)/(radius**2-rim**2);hub=remaining-tread
    second=lateral-axle*half_span**2
    if min(hub,tread,second)<=1e-8:
        raise ValueError('CAD wheel mass/inertia cannot supply the minimum axle masses with these ring radii; check materials and wheel representation')
    ratio=float(options['hubWidth'])/float(options['tireWidth'])
    width=2*math.sqrt(second/(tread+hub*ratio**2));hub_width=ratio*width
    if width>1.05*options['tireWidth'] or min(width,hub_width)<.01:
        raise ValueError('CAD wheel moments require ring widths outside its declared tire envelope')
    count=2*options['numRays'];options=dict(options,hubNodeWeight=hub/count,nodeWeight=tread/count,tireWidth=width,hubWidth=hub_width)
    equivalent=(spin/2+lateral)*np.eye(3)+(spin/2-lateral)*np.outer(axis,axis)
    return options,added,dict(minimum_support_node_kg=minimum,added_per_axle_node_kg=added,
        original_mass_kg=mass,generated_mass_kg=remaining,spin_inertia_kg_m2=spin,
        transverse_second_moment_kg_m2=lateral,tire_mass_ring_width_m=width,
        inertia_axisymmetry_relative_error=float(np.linalg.norm(equivalent-inertia)/np.linalg.norm(inertia)),
        scope='CAD mass, axial inertia and mean transverse inertia preserved; axisymmetric tire approximation; no ballast')


def cad_tire_budget(options):
    """Experimental carcass coefficients for small CAD ring masses; no ballast."""
    o=dict(options);hub=min(1.,o['hubNodeWeight']/.06);tread=min(1.,o['nodeWeight']/.3)
    for key in ('hubTreadBeamSpring','hubPeripheryBeamSpring','hubSideBeamSpring','hubReinfBeamSpring',
                'wheelSideBeamSpring','wheelSideBeamSpringExpansion','wheelSideBeamDamp','wheelSideBeamDampExpansion','wheelReinfBeamSpring'):
        o[key]*=hub
    o['wheelReinfBeamDamp']=.2*math.sqrt(o['wheelReinfBeamSpring']*o['hubNodeWeight'])
    o['wheelReinfBeamDampCutoffHz']=0
    for key in ('wheelTreadBeamSpring','wheelTreadBeamDamp','wheelPeripheryBeamSpring','wheelPeripheryBeamDamp',
                'wheelTreadReinfBeamSpring','wheelTreadReinfBeamDamp','wheelPeripheryReinfBeamSpring','wheelPeripheryReinfBeamDamp'):
        o[key]*=tread
    o['wheelTreadReinfBeamDampCutoffHz']=0;o['wheelPeripheryReinfBeamDampCutoffHz']=0
    return o,dict(hub_scale=hub,tread_scale=tread,
        scope='Experimental carcass stabilization for low CAD ring mass; pressure and all masses unchanged')


def wheel_axis_points(points,center=None,half_span=.075):
    """Locate the axle on its declared CAD axis, with a consistent +X order."""
    hub=np.asarray(points['hub'],float);axis=np.asarray(points['hub_axis'],float)-hub
    length=np.linalg.norm(axis)
    if not math.isfinite(half_span) or half_span<=0:raise ValueError('Wheel axle half span must be positive')
    if not np.isfinite(axis).all() or length<.01 or abs(axis[0])<1e-8:
        raise ValueError('Wheel needs a finite transverse hub axis at least 10 mm long')
    if center is not None:hub=hub+axis*np.dot(np.asarray(center)-hub,axis)/length**2
    axis*= (half_span/length)*(1 if axis[0]>0 else -1)
    return hub-axis,hub+axis


def generate(project,frame,definition,*,scratch=None,cgal=None):
    from frame_harness.progress import emit
    drive_graph=definition.get('driveline')
    if drive_graph:
        drive_graph=resolved_wheel_datums(definition)
        from driveline import validate as validate_drive
        from driveline_physics import owners as drive_owners
        validate_drive(drive_graph,project)
        chains={};drive_components=drive_owners(drive_graph)
    else:
        chains=shaft_chains.validate(definition,project['Components']);drive_components=set()
    for name,position in frame_mounts(definition).items():
        patch=frame.get('cadMountPatches',{}).get(name)
        if patch is None or not np.allclose(patch['position'],position,atol=1e-7,rtol=0):raise ValueError('Mount moved or missing after frame calibration: '+name)
    model=TemplateModel(definition);checks={corner:Mechanism(model,corner).inspect() for corner in model.data['corners']}
    single=[v for v in project['Components'] if not v['MvpRole'].startswith('panel') and v['MvpRole'] not in shaft_chains.REPEATABLE_ROLES|{'accessory'} and (v['Id'] not in drive_components or v['MvpRole'].endswith('_wheel'))]
    roles={v['MvpRole']:v for v in single}
    if len(roles)!=len(single):raise ValueError('Duplicate single-owner role')
    graph=Structure(frame,roles['frame']['Id']);meshes={};bindings={};corners={};wheel_rows=[];hydros=[]
    graph.condition_rigid_bodies=definition.get('parameters',{}).get('assembled_rigid_conditioning',True)
    graph.wishbone_representation=definition.get('parameters',{}).get('wishbone_representation','hardpoint_lumped')
    if graph.wishbone_representation not in ('cad_moments','hardpoint_lumped','rigidifier'):raise ValueError('Unknown wishbone mass representation')
    graph.trailing_arm_representation=definition.get('parameters',{}).get('trailing_arm_representation','hardpoint_lumped')
    if graph.trailing_arm_representation not in ('cad_moments','hardpoint_lumped'):raise ValueError('Unknown trailing arm mass representation')
    graph.upright_representation=definition.get('parameters',{}).get('upright_representation','cad_moments')
    if graph.upright_representation not in ('cad_moments','hardpoint_lumped'):raise ValueError('Unknown upright mass representation')
    graph.rigid_damping_budget=float(definition.get('parameters',{}).get('rigid_damping_budget',2.))
    graph.steering_link_frequency_hz=definition.get('parameters',{}).get('steering_link_frequency_hz')
    graph.wishbone_loaded_priority=float(definition.get('parameters',{}).get('wishbone_loaded_priority',1.))
    graph.wishbone_owners=set()
    graph.frame_reference_hz=float(definition.get('parameters',{}).get('rigid_frame_reference_hz',0))
    shared_carrier_points={}
    share_outer=definition.get('parameters',{}).get('shared_halfshaft_carrier_nodes',False)
    if type(share_outer) is not bool:raise ValueError('Shared halfshaft carrier option must be boolean')
    if share_outer:
        for owner,shaft in definition.get('halfshafts',{}).items():
            corner=shaft['corner'];template=model.data['corners'][corner]['template']
            role=corner.lower()+('_upright' if template in ('double_wishbone','trailing_radius_toe','trailing_ball_radius_toe') else '_trailing_arm')
            point=np.asarray(shaft['outer'],float)
            if point.shape!=(3,) or not np.isfinite(point).all():raise ValueError('Invalid carrier shaft center')
            shared_carrier_points.setdefault(role,{})[owner+'_outer']=point
    def rigid(role,points,shared=()):
        # An existing shaft center can belong to both rigid carrier and shaft.
        # A shared point transmits force without constraining relative rotation.
        # Do not move it to an axle endpoint or add a spring across wheel travel.
        points=dict(points)
        for name,point in shared_carrier_points.get(role,{}).items():
            if name in points:raise ValueError('Duplicate carrier shaft center')
            points[name]=point
        shared=set(shared)|set(graph.frame_joint_nodes.values()).intersection(points)
        comp=roles[role]
        if role.endswith('_wishbone'):graph.wishbone_owners.add(comp['Id'])
        names,mesh=graph.rigid_component(comp,points,shared);meshes[comp['Id']]=mesh;bindings[comp['Id']]=[comp['Id']+'_structure'];return names
    def endpoint(owner,name,point,mass):
        if name in graph.nodes:
            if name not in graph.frame_joint_nodes.values() or not np.allclose(graph.point(name),point,atol=1e-9,rtol=0):raise ValueError('Invalid shared endpoint '+name)
            graph.nodes[name]['options']['nodeWeight']+=mass;graph.nodes[name]['options']['group'].append(owner+'_structure')
        else:
            opts=dict(nodeWeight=mass,collision=False,selfCollision=False,group=[owner+'_structure'])
            graph.nodes[name]=dict(position=point.tolist(),options=opts);graph.owners[name]=owner
            graph.part['nodes'].append([name,*point.tolist(),opts])
    total=sum(c.read_geometry(v)[1][0] for v in project['Components']);parameters=definition.get('parameters',{});shock_options={}
    if parameters.get('wheel_mass_model','provisional') not in ('provisional','cad_axisymmetric'):
        raise ValueError('Unknown wheel mass model')
    from vehicle_alignment import solve as solve_alignment
    graph.alignment=solve_alignment(model)
    rear_length_scale=float(parameters.get('rear_toe_link_length_scale',1.))
    if not math.isfinite(rear_length_scale) or not .98<=rear_length_scale<=1.02:
        raise ValueError('Rear toe link length scale must be between 0.98 and 1.02')
    if rear_length_scale!=1 and definition['templates']['rear_suspension'] not in ('double_wishbone','trailing_radius_toe','trailing_ball_radius_toe'):
        raise ValueError('Rear toe link adjustment requires a rear suspension with toe links')
    for corner_index,corner in enumerate(('FL','FR','RL','RR')):
        emit('Build suspension',completed=corner_index,total=4,detail=corner)
        corner_length_scale=graph.alignment.get(corner,{}).get('length_scale',rear_length_scale if corner[0]=='R' else 1.)
        p=model.corner_points(corner);prefix=corner.lower();front=corner[0]=='F';ids={};toe_link=None;wishbone=model.data['corners'][corner]['template']=='double_wishbone'
        ball_radius_toe=model.data['corners'][corner]['template']=='trailing_ball_radius_toe'
        radius_toe=model.data['corners'][corner]['template']=='trailing_radius_toe' or ball_radius_toe
        cad_wheel=parameters.get('wheel_mass_model')=='cad_axisymmetric'
        wheel_moments=c.read_geometry(roles[prefix+'_wheel'])[1]
        axle_points=wheel_axis_points(p,wheel_moments[1] if cad_wheel else None,
            float(parameters.get('wheel_axle_half_span_m',.045)) if cad_wheel else .075)
        def node(role):return graph.frame_joint_nodes.get(corner+'_'+role,corner+'_'+role)
        if wishbone:
            for arm in ('upper','lower'):
                points={node(arm+'_'+which):p[arm+'_'+which] for which in ('inner_front','inner_rear')}
                points[node(arm+'_ball')]=p[arm+'_ball']
                if arm=='lower':points[node('shock_bottom')]=p['shock_bottom']
                role=prefix+'_'+arm+'_wishbone';rigid(role,points)
                for which in ('inner_front','inner_rear'):graph.patch(corner+'_'+arm+'_'+which,node(arm+'_'+which),direct=True)
            points={node(key):p[key] for key in ('upper_ball','lower_ball','tie_outer')}
            points[node('axis_in')],points[node('axis_out')]=axle_points
            rigid(prefix+'_upright',points,shared=[node(arm+'_ball') for arm in ('upper','lower')])
            # A common pivot locates the ball exactly but transmits no moment
            # between the independently rigid bodies. Each CAD component keeps
            # its own mass contribution at the shared point.
            for arm in ('upper','lower'):
                graph.joints.append(dict(id=node(arm+'_ball_joint'),kind='shared_ball',
                    parent=roles[prefix+'_'+arm+'_wishbone']['Id'],child=roles[prefix+'_upright']['Id'],nodes=[node(arm+'_ball')]))
            # A steering actuator changes tie length. This is an explicit
            # equivalent linkage, also used by the analytical solver.
            inner=node('tie_inner');role=prefix+('_tie_rod' if front else '_toe_link')
            # A free rigid cage attached at one point adds spurious mechanisms.
            # The slender link instead distributes its mass at its endpoints.
            link=roles[role];link_mass=c.read_geometry(link)[1][0]
            translating=front and definition.get('steering',{}).get('kind')=='translating_rack'
            endpoint(link['Id'],inner,p['tie_inner'],link_mass/2)
            if not translating:graph.patch(corner+'_tie_inner',inner,direct=True)
            graph.nodes[node('tie_outer')]['options']['nodeWeight']+=link_mass/2
            graph.mass_allocations[link['Id']]={inner:link_mass/2,node('tie_outer'):link_mass/2}
            meshes[link['Id']]=c.read_geometry(link)[0]
            # The inboard end also needs a local, noncollinear visual basis.
            # Upright nodes alone all lie far along the slender link from that
            # end, so native flexbody mapping can fail to find a VY locator.
            # Reuse existing frame nodes: this adds no mass or constraints.
            visual_supports=joint_supports(graph,graph.frame_owner,p['tie_inner'])
            for n in set([inner,*visual_supports,*graph.groups[roles[prefix+'_upright']['Id']]]):
                graph.nodes[n]['options']['group'].append(link['Id']+'_structure')
            bindings[link['Id']]=[link['Id']+'_structure']
            length=float(np.linalg.norm(p['tie_outer']-p['tie_inner']))
            steering_spring=float(definition.get('parameters',{}).get('steering_link_spring_n_m',2500000))
            if not math.isfinite(steering_spring) or steering_spring<=0:
                raise ValueError('Steering link spring must be finite and positive')
            # Tune the existing axial steering restraint only. The assembled
            # tangent budget below still limits its final native coefficient.
            if translating:graph.beam(inner,node('tie_outer'),beamSpring=steering_spring,beamDamp=50)
            elif front:hydros.append([inner,node('tie_outer'),dict(inputSource='steering_input',factor=-checks[corner]['steer_length_m']/length,inRate=2,outRate=2,beamSpring=steering_spring,beamDamp=50,beamDeform=80000,beamStrength=160000,beamPrecompression=corner_length_scale,beamPrecompressionTime=0)])
            else:
                # A threaded toe link has a tunable unloaded length. This is
                # fixed mechanical alignment, with no driving-time controller.
                graph.beam(inner,node('tie_outer'),beamSpring=2500000,beamDamp=50,
                           beamPrecompression=corner_length_scale,beamPrecompressionTime=0)
                if corner_length_scale!=1:
                    toe_link=dict(nodes=[inner,node('tie_outer')],reference_length_m=length*corner_length_scale)
            if front:
                graph.steering_constraints.append(graph.new_beams[-1] if translating else hydros[-1])
        else:
            pivots=('trailing_ball',) if ball_radius_toe else ('hinge_inner','hinge_outer')
            carrier_sites=('carrier_axis_a','carrier_axis_b') if ball_radius_toe else ('carrier_ball',)
            arm_sites=(*pivots,'shock_bottom',*carrier_sites,'radius_upper_outer','radius_lower_outer') if ball_radius_toe else (*pivots,'shock_bottom')
            points={node(key):p[key] for key in arm_sites}
            if radius_toe and not ball_radius_toe:points[node('carrier_ball')]=p['carrier_ball']
            elif not radius_toe:points[node('axis_in')],points[node('axis_out')]=axle_points
            rigid(prefix+'_trailing_arm',points)
            for key in pivots:
                graph.patch(corner+'_'+key,node(key),direct=True)
                if radius_toe:graph.joints.append(dict(id=node(key+'_ball_joint'),kind='shared_ball',parent=graph.frame_owner,child=roles[prefix+'_trailing_arm']['Id'],nodes=[node(key)]))
            if radius_toe:
                upright_sites=(*carrier_sites,'tie_outer') if ball_radius_toe else ('carrier_ball','radius_upper_outer','radius_lower_outer','tie_outer')
                points={node(key):p[key] for key in upright_sites}
                points[node('axis_in')],points[node('axis_out')]=axle_points
                rigid(prefix+'_upright',points,shared=[node(key) for key in carrier_sites])
                graph.joints.append(dict(id=node('carrier_joint'),kind='shared_hinge' if ball_radius_toe else 'shared_ball',parent=roles[prefix+'_trailing_arm']['Id'],child=roles[prefix+'_upright']['Id'],nodes=[node(key) for key in carrier_sites]))
                for key,suffix in [('radius_upper','upper_radius_rod'),('radius_lower','lower_radius_rod'),('tie','toe_link')]:
                    link=roles[prefix+'_'+suffix];owner=link['Id'];inner=node(key+'_inner');outer=node(key+'_outer')
                    mesh,moments,_=c.read_geometry(link);mass=moments[0]
                    endpoint(owner,inner,p[key+'_inner'],mass/2);graph.patch(corner+'_'+key+'_inner',inner,direct=True)
                    graph.nodes[outer]['options']['nodeWeight']+=mass/2
                    graph.mass_allocations[owner]={inner:mass/2,outer:mass/2};graph.groups[owner]=[inner,outer]
                    # An axial beam with shared endpoints has no bending or
                    # torsional constraint: both rod ends are spherical.
                    scale=corner_length_scale if key=='tie' else 1.
                    graph.beam(inner,outer,beamSpring=2500000,beamDamp=50,beamPrecompression=scale,beamPrecompressionTime=0)
                    length=float(np.linalg.norm(p[key+'_outer']-p[key+'_inner']))
                    graph.joints.append(dict(id=owner+'_length',kind='spherical_ended_rod',nodes=[inner,outer],reference_length_m=length*scale))
                    outer_owner=roles[prefix+('_trailing_arm' if ball_radius_toe and key!='tie' else '_upright')]['Id']
                    for end,parent,n in [('inner',graph.frame_owner,inner),('outer',outer_owner,outer)]:
                        graph.joints.append(dict(id=owner+'_'+end+'_ball_joint',kind='shared_ball',parent=parent,child=owner,nodes=[n]))
                    graph.reports[owner]=dict(target_mass_kg=mass,actual_mass_kg=mass,allocation_method='endpoint_lumped',limitations=['Slender spherical-ended rod: endpoint mass approximation; bending and local joint strength are not calibrated.'])
                    supports=joint_supports(graph,graph.frame_owner,p[key+'_inner'])
                    for n in set([inner,*supports,*graph.groups[outer_owner]]):graph.nodes[n]['options']['group'].append(owner+'_structure')
                    meshes[owner]=mesh;bindings[owner]=[owner+'_structure']
                    if key=='tie' and scale!=1:toe_link=dict(nodes=[inner,outer],reference_length_m=length*scale)
        # A two-ended telescopic spring is represented by a bounded beam. The
        # mass of its CAD body is distributed to the two attachment structures.
        shock=roles[prefix+'_spring_damper'];shock_mass=c.read_geometry(shock)[1][0]
        bottom=node('shock_bottom');ids.update(axis_in=node('axis_in'),axis_out=node('axis_out'),shock_bottom=bottom)
        # Keep additional mass outside the calibrated frame by giving the upper
        # spring eye its own node and physical half-mass.
        top=node('shock_top');endpoint(shock['Id'],top,p['shock_top'],shock_mass/2)
        graph.patch(corner+'_shock_top',top,direct=True);ids['shock_top']=top
        graph.nodes[bottom]['options']['nodeWeight']+=shock_mass/2
        graph.mass_allocations[shock['Id']]={top:shock_mass/2,bottom:shock_mass/2}
        meshes[shock['Id']]=c.read_geometry(shock)[0]
        suspension_owner=roles[prefix+('_lower_wishbone' if wishbone else '_trailing_arm')]['Id']
        for name in [top,*graph.groups[suspension_owner]]:graph.nodes[name]['options']['group'].append(shock['Id']+'_structure')
        bindings[shock['Id']]=[shock['Id']+'_structure']
        ratio=checks[corner]['motion_ratio']
        # Preload changes a beam's reference length. A stop on that same beam
        # would engage relative to the unloaded spring, rather than the CAD
        # design ride height. Keep the spring and physical travel stops separate.
        # Both are bounded beams so native JBeam permits the duplicate endpoints.
        graph.beam(top,bottom,beamType='|BOUNDED',beamSpring=0,beamDamp=0,
                   beamLongBound=1,beamShortBound=1,beamLimitSpring=0,beamLimitDamp=0,beamPrecompressionTime=.5)
        spring_options=graph.new_beams[-1][2]
        graph.beam(top,bottom,beamType='|BOUNDED',beamSpring=0,beamDamp=0,
                   shortBoundRange=.08*ratio,longBoundRange=.08*ratio,boundZone=.01,beamLimitSpring=150000,beamLimitDamp=250,
                   dampCutoffHz=100)
        shock_options[corner]=dict(spring=spring_options,damper=graph.new_beams[-1][2])
        mass=c.read_geometry(roles[prefix+'_wheel'])[1][0]
        meshes[roles[prefix+'_wheel']['Id']]=c.read_geometry(roles[prefix+'_wheel'])[0];bindings[roles[prefix+'_wheel']['Id']]=['tire_'+corner]
        # Allocate CAD moments and budget the reference carcass before changing
        # contact resolution. Otherwise refinement silently softens its recipe
        # a second time through the per-node low-mass budget.
        from tire_resolution import REFERENCE_RAYS,DEFAULT_RAYS,refine,validate_rays
        requested_rays=validate_rays(parameters.get('tire_rays',DEFAULT_RAYS))
        options=wheel_options(mass,front,dict(parameters,tire_rays=REFERENCE_RAYS),total)
        axes=[ids['axis_in'],ids['axis_out']]
        allocation=cad_wheel_support_mass if cad_wheel else wheel_support_mass
        extra=dict(moments=wheel_moments,axis=p['hub_axis']-p['hub']) if cad_wheel else {}
        axis_masses=[graph.nodes[n]['options']['nodeWeight'] for n in axes]
        # Keep the CAD wheel mass/inertia in its rotating rings. The support
        # target is an audit, not permission to strip mass out of the rim or
        # change the body's inertia. Ballast is a separate explicit experiment.
        additive=parameters.get('loaded_node_mass_policy','reported_ballast')!='preserve_cad'
        wheel_minimum=min(axis_masses)
        options,axle_mass,wheel_allocation=allocation(options,
            axis_masses,
            np.linalg.norm(graph.point(axes[1])-graph.point(axes[0]))/2,
            minimum=wheel_minimum,**extra)
        wheel_allocation['support_mass_source']='separate_reported_ballast' if additive else 'cad_carrier_mass_only'
        if cad_wheel:
            wheel_allocation['center_error_m']=float(np.linalg.norm((graph.point(axes[0])+graph.point(axes[1]))/2-wheel_moments[1]))
        if parameters.get('cad_tire_budget',False):
            options,wheel_allocation['experimental_tire_budget']=cad_tire_budget(options)
        options,wheel_allocation['contact_resolution']=refine(options,requested_rays)
        for name in axes:graph.nodes[name]['options']['nodeWeight']+=axle_mass
        graph.mass_allocations[roles[prefix+'_wheel']['Id']]={name:axle_mass for name in axes} if axle_mass else {}
        carrier=roles[prefix+('_upright' if wishbone or radius_toe else '_trailing_arm')]['Id']
        graph.rebudget_carrier(carrier,roles[prefix+'_wheel']['Id'])
        torque_arm=brake_reaction_node(graph,carrier,[ids['axis_in'],ids['axis_out']])
        # The generic pressure-wheel generator staggers its two rings. Mirror
        # that construction across the vehicle, with node1 outboard and node2
        # inboard, and reverse wheelDir so both sides still drive forward.
        wheel_axis=[ids['axis_out'],ids['axis_in']] if corner[1]=='L' else [ids['axis_in'],ids['axis_out']]
        wheel_direction=-1 if corner[1]=='L' else 1
        wheel_rows.append([corner,'rim_'+corner,'tire_'+corner,*wheel_axis,9999,torque_arm,wheel_direction,options])
        corners[corner]=dict(nodes=ids,wheel_mass_kg=mass-2*axle_mass,cad_wheel_mass_kg=mass,mass_allocation=wheel_allocation,motion_ratio=ratio,template=model.data['corners'][corner]['template'],
            hardpoint_nodes={key:node(key) for key in p if node(key) in graph.nodes},
            brake_torque_nm=options['brakeTorque'],brake_reaction_node=torque_arm,
            tire_contract=dict(wheel_section='pressureWheels',tread_nodes=2*options['numRays'],hub_nodes=2*options['numRays'],collision=True,self_collision=False,
                reinforcement_l_beams=2*options['numRays'],
                axle_nodes=wheel_axis,wheel_direction=wheel_direction,
                radius_m=options['radius'],tire_mass_ring_width_m=options['tireWidth'],pressure_psi=parameters.get('tire_pressure_psi',12)))
        if toe_link:corners[corner]['toe_link']=toe_link
    # Fixed items use declared mounts; no body bounds or display transforms can
    # silently relocate a physical mounting point.
    physical_owners={v['Id'] for v in project['Components']}
    visual_owners=set(project.get('_VisualComponentIds',[]))
    fixed={owner:copy.deepcopy(points) for owner,points in definition.get('fixed_mounts',{}).items() if owner not in visual_owners}
    if set(fixed)-physical_owners:raise ValueError('Fixed mount owner is missing from the physical project')
    from attachment_contract import prepare_points,connect as connect_fasteners
    authored_mounts=definition.get('attachment_contract')
    parent_locators=prepare_points(fixed,authored_mounts,graph.frame_owner) if authored_mounts is not None else {}
    if drive_graph:
        from driveline_physics import housing_points
        endpoints={e['id']:e for e in drive_graph['endpoints']}
        engine_device=next(d for d in drive_graph['devices'] if d['type']=='engine')
        cvt_device=next(d for d in drive_graph['devices'] if d['type']=='cvt')
        engine_owner=engine_device['component'];cvt_owner=cvt_device['component']
        crank_axis=np.array(endpoints[engine_device['ports'][0]['endpoint']]['axis'])
        crank_report=dict(method='cad_endpoint',axis=crank_axis.tolist(),scope='Explicit driveline engine output axis')
        shaft_owners={s['component'] for s in drive_graph['shafts']}
        if shaft_owners&set(fixed):raise ValueError('Shaft bodies cannot also be rigidly mounted to the chassis')
        housing_owners={d['component'] for d in drive_graph['devices'] if d['type']!='wheel'}
        if drive_graph['version']==2:
            graph.reaction_graph=drive_graph;graph.reaction_owners=housing_owners
        if not housing_owners<=set(fixed):raise ValueError('Every device housing needs explicit reviewed frame mounts')
    else:
        from drive_axes import resolve as resolve_drive_axis
        crank_axis,crank_report=resolve_drive_axis(roles['engine'],roles['cvt'],parameters)
        engine_owner=roles['engine']['Id'];cvt_owner=roles['cvt']['Id']
    graph.drive_axes={engine_owner:crank_axis}
    for component_index,(owner,points) in enumerate(fixed.items()):
        emit('Build fixed components',completed=component_index,total=len(fixed),detail=owner)
        comp=next(v for v in project['Components'] if v['Id']==owner)
        if definition.get('steering',{}).get('component')==owner:
            from translating_rack import generate as generate_rack
            names,mesh=generate_rack(graph,project,definition,points,hydros)
        elif drive_graph and owner in housing_owners:
            required={owner+'_mount_'+str(i):p for i,p in enumerate(points)}
            if drive_graph['version']==1:required.update(housing_points(drive_graph,owner,points))
            if scratch is None:names,mesh=graph.rigid_component(comp,required)
            else:
                extra=[p for key,p in required.items() if key.startswith('driveline_axis_') and not any(np.linalg.norm(np.asarray(p)-q)<1e-7 for q in points)]
                names,mesh=graph.geometry_component(comp|dict(_DrivelineHousing=True),list(points)+extra,scratch,cgal)
        elif scratch is not None:
            if parameters.get('engine_reaction_support',False) and comp.get('MvpRole')=='engine':
                comp=comp|dict(_ExperimentalReactionSupport=True,_ReactionAxis=crank_axis.tolist(),
                    _ReactionMinimumMass=parameters.get('minimum_drive_reaction_node_kg',2.))
            if parameters.get('experimental_reaction_support',0)==1 and comp.get('MvpRole') in ('front_diff','rear_diff','rear_final_drive'):
                comp=comp|dict(_ExperimentalReactionSupport=True,_ReactionMinimumMass=parameters.get('minimum_drive_reaction_node_kg',2.))
            names,mesh=graph.geometry_component(comp,points,scratch,cgal)
        else:
            names,mesh=graph.rigid_component(comp,{owner+'_mount_'+str(i):p for i,p in enumerate(points)})
        meshes[owner]=mesh;bindings[owner]=[owner+'_structure']
        if authored_mounts is None:
            release='release_'+owner if comp.get('Template')=='panel' and owner not in definition.get('fixed_panel_components',[]) else None
            if not release and definition.get('steering',{}).get('component')!=owner:graph.fixed_owners.add(owner)
            for i in range(len(points)):graph.patch(owner+'_'+str(i),owner+'_mount_'+str(i),release+'_'+str(i) if release else None,
                    parameters.get('panel_mount_strength_n',4000),damping=None if release else parameters.get('fixed_mount_damping_ns_m',120),direct=not release)
    if authored_mounts is not None:connect_fasteners(graph,authored_mounts,parent_locators)
    if parameters.get('reuse_loaded_joint_supports',False):
        preferred=set()
        for corner in corners.values():
            preferred.update(corner['hardpoint_nodes'].values())
            preferred.update(corner['tire_contract']['axle_nodes'])
            preferred.add(corner['brake_reaction_node'])
        for role in ('front_diff','rear_final_drive','rear_diff'):
            if role in roles:
                owner=roles[role]['Id']
                for direction in (-1,1):preferred.update(wheel_reaction_nodes(graph,owner,direction).values())
        graph.preferred_joint_supports={owner:set(names)&preferred for owner,names in graph.groups.items()}
    shafts={} if drive_graph else definition.get('halfshafts',{})|definition.get('shafts',{})
    ideal_sections=[]
    if drive_graph:
        from driveline_physics import ideal_declarations
        hub_owners={corner:roles[corner.lower()+('_upright' if model.data['corners'][corner]['template'] in ('double_wishbone','trailing_radius_toe','trailing_ball_radius_toe') else '_trailing_arm')]['Id'] for corner in corners}
        shafts=ideal_declarations(drive_graph,hub_owners)
    for shaft_index,(owner,declaration) in enumerate(shafts.items()):
        emit('Connect shafts',completed=shaft_index,total=len(shafts),detail=owner)
        comp=next(v for v in project['Components'] if v['Id']==owner)
        if owner in meshes:raise ValueError('A halfshaft cannot also have fixed chassis mounts: '+owner)
        ideal='ideal_id' in declaration
        if ideal:
            housing,suspension=declaration['parents']
        elif 'corner' in declaration:
            corner=declaration['corner'];prefix=corner.lower()
            housing=roles['front_diff' if corner[0]=='F' else ('rear_final_drive' if 'rear_final_drive' in roles else 'rear_diff')]['Id']
            suspension=roles[prefix+('_upright' if model.data['corners'][corner]['template'] in ('double_wishbone','trailing_radius_toe','trailing_ball_radius_toe') else '_trailing_arm')]['Id']
        else:
            housing=roles[declaration['inner_role']]['Id'];suspension=roles[declaration['outer_role']]['Id']
        mesh,moments,_=c.read_geometry(comp);shaft_nodes=[];parents=[]
        if moments[0]<=0:raise ValueError(owner+': shaft needs positive CAD mass')
        for end,parent in [('inner',housing),('outer',suspension)]:
            n=owner+'_'+end;p=np.array(declaration[end],float)
            if ideal:
                n=next((site for site in graph.groups[parent] if np.linalg.norm(graph.point(site)-p)<1e-7),n)
            shaft_nodes.append(n)
            if n in graph.nodes:
                if ideal and (n not in graph.groups[parent] or np.linalg.norm(graph.point(n)-p)>1e-7):raise ValueError(owner+': shaft endpoint node identity conflicts with another owner')
                if not ideal and (not share_outer or owner not in definition.get('halfshafts',{}) or end!='outer'
                    or n not in graph.mass_allocations[parent] or not np.allclose(graph.point(n),p,atol=1e-9,rtol=0)):
                    raise ValueError('Invalid shared shaft endpoint: '+n)
                graph.nodes[n]['options']['nodeWeight']+=moments[0]/2
                graph.nodes[n]['options']['group'].append(owner+'_structure')
                parents.extend(graph.groups[parent])
                graph.joints.append(dict(id=n,kind='shared_ball',parent=parent,child=owner,nodes=[n]))
                continue
            options=dict(nodeWeight=moments[0]/2,collision=False,selfCollision=False,group=[owner+'_structure'])
            graph.nodes[n]=dict(position=p.tolist(),options=options);graph.owners[n]=owner
            graph.part['nodes'].append([n,*p.tolist(),options]);support=joint_supports(graph,parent,p);parents.extend(support)
            graph.spherical(owner+'_'+end,support,n,parent_owner=parent)
        plunge=float(declaration.get('plunge_m',.06))
        length=float(np.linalg.norm(graph.point(shaft_nodes[1])-graph.point(shaft_nodes[0])))
        if length<.001 or not (0<=plunge<length*.5 if ideal else 0<plunge<length*.5):
            raise ValueError(owner+': invalid shaft length or half travel')
        if plunge:
            graph.beam(*shaft_nodes,beamType='|BOUNDED',beamSpring=0,beamDamp=0,shortBoundRange=plunge,longBoundRange=plunge,
                       boundZone=.01,beamLimitSpring=20000,beamLimitDamp=50,dampCutoffHz=100)
        if ideal:
            ideal_sections.append(dict(id=declaration['ideal_id'],component=owner,representation='ideal',
                endpoints=shaft_nodes,nodes=shaft_nodes,parents=declaration['parents'],rest_length_m=length,half_travel_m=plunge))
        graph.groups[owner]=shaft_nodes;graph.mass_allocations[owner]={n:moments[0]/2 for n in shaft_nodes}
        for n in parents:graph.nodes[n]['options']['group'].append(owner+'_structure')
        graph.reports[owner]=dict(target_mass_kg=moments[0],actual_mass_kg=moments[0],allocation_method='endpoint_lumped',
            center_error_m=float(np.linalg.norm((graph.point(shaft_nodes[0])+graph.point(shaft_nodes[1]))/2-moments[1])),
            limitations=['Endpoint mass approximation; shaft bending/rotational inertia and physical spline strength are not calibrated.'])
        if plunge:graph.joints.append(dict(id=owner+'_plunge',kind='telescopic',nodes=shaft_nodes,travel_m=plunge*2))
        meshes[owner]=mesh;bindings[owner]=[owner+'_structure']
    graph.shaft_chains=shaft_chains.generate(graph,chains,project['Components'],meshes,bindings,joint_supports)
    if drive_graph:
        from driveline_physics import generate as generate_drive
        graph.driveline_hub_owners={corner:roles[corner.lower()+('_upright' if model.data['corners'][corner]['template'] in ('double_wishbone','trailing_radius_toe','trailing_ball_radius_toe') else '_trailing_arm')]['Id'] for corner in corners}
        generate_drive(drive_graph,graph,project,meshes,bindings,joint_supports)['sections'].extend(ideal_sections)
    graph.part['hydros']=[['id1:','id2:']]+hydros
    graph.part['pressureWheels']=[['name','hubGroup','group','node1:','node2:','nodeS','nodeArm:','wheelDir']]+wheel_rows
    from suspension_loads import configure as configure_suspension
    from vehicle_drivetrain import generate as drivetrain
    engine=engine_owner;cvt=cvt_owner
    if drive_graph:
        from driveline import compile as compile_drive,wheel_reactions
        from driveline_physics import reaction as reaction_basis
        basis=reaction_basis(graph,engine,crank_axis)
        engine_reactions=[basis['torqueCoupling'],basis['torqueArm2'],basis['torqueArm']]
        drive,contract=compile_drive(drive_graph,engine_reactions,graph.groups[cvt][0],parameters)
        wheel_reaction=wheel_reactions(drive_graph)
        wheel_housing={corner:value['component'] for corner,value in wheel_reaction.items()}
    else:drive,contract=drivetrain(definition['templates']['drivetrain'],parameters,reaction_nodes(graph,engine,cvt),graph.groups[cvt][0])
    graph.part.update(drive)
    if graph.shaft_chains:
        contract['shaft_chains']={key:dict(device=value['powertrain_device'],components=[s['component'] for s in value['segments']]) for key,value in graph.shaft_chains.items()}
        contract['assumptions'].append('Articulated shaft sections share the existing ideal powertrain connection; no additional gear reduction or Cardan angular-speed correction is inferred.')
    contract['devices']['mainEngine']['torqueReactionNodes']=drive['mainEngine']['torqueReactionNodes:']
    contract['engine_axis']=crank_report
    contract['assumptions'].append(crank_report['scope'])
    housing_inertias={};wheel_inertias={}
    for row in wheel_rows:
        corner=row[0];reaction=dict(nodeArm=corners[corner]['brake_reaction_node'])
        if corner in contract['driven_wheels']:
            housing=wheel_housing[corner] if drive_graph else roles['front_diff' if corner[0]=='F' else ('rear_final_drive' if 'rear_final_drive' in roles else 'rear_diff')]['Id']
            if drive_graph:
                torque=reaction_basis(graph,housing,wheel_reaction[corner]['axis'])
            else:torque=wheel_reaction_nodes(graph,housing,row[7])
            axle='front' if corner[0]=='F' else 'rear'
            options=row[-1];rays=options['numRays']*2
            # Native pressure-wheel wheel.nodes is the rotating hub ring.
            # Tire nodes deform separately and are not in shaft.calculateInertia.
            wheel_inertias[corner]=rays*options['hubNodeWeight']*options['hubRadius']**2
            row[-1].update({name+':':node for name,node in torque.items()})
            reaction.update(torque);corners[corner]['drive_reaction_owner']=housing
        corners[corner]['reaction_nodes']=reaction
    from vehicle_conditioning import allocate_support_mass
    allocate_support_mass(graph,corners,drive['mainEngine']['torqueReactionNodes:'],parameters)
    if graph.numerical_mass['added_mass_kg']:
        actual_mass=sum(v['options']['nodeWeight'] for v in graph.nodes.values())+sum(v['wheel_mass_kg'] for v in corners.values())
        for row in wheel_rows:
            corner=row[0];front=corner.startswith('F');options=row[-1]
            if ('front_brake_torque_nm' if front else 'rear_brake_torque_nm') not in parameters:
                share=parameters.get('front_brake_bias',.6)
                torque=actual_mass*9.81*options['radius']*parameters.get('brake_deceleration_g',1.)*(share if front else 1-share)/2
                options['brakeTorque']=torque;options['parkingTorque']=0 if front else torque
                corners[corner]['brake_torque_nm']=torque
        graph.numerical_mass['brake_load_mass_kg']=actual_mass
        emit('Numerical support mass',completed=1,total=1,
             detail=f"{graph.numerical_mass['added_mass_kg']:.3f} kg added; simulated mass {actual_mass:.3f} kg. This is additional numerical mass, not CAD/material mass.")
    # Final masses must precede load/preload and drivetrain reaction-inertia fits.
    configure_suspension(graph,corners,roles,model,definition,shock_options)
    for corner,wheel in corners.items():
        if corner not in contract['driven_wheels']:continue
        axle='front' if corner[0]=='F' else 'rear'
        key=corner if drive_graph else axle
        housing_inertias[key]=min(housing_inertias.get(key,float('inf')),reaction_inertia(graph,wheel['reaction_nodes']))
    from vehicle_drivetrain import configure_carrier
    if drive_graph:
        from driveline_physics import configure
        configure(graph.part,contract,wheel_inertias,housing_inertias,parameters)
    else:configure_carrier(graph.part,contract,housing_inertias,wheel_inertias,parameters)
    part=graph.finish()
    if authored_mounts is not None:
        from attachment_contract import audit_release
        graph.release_audit=audit_release(part,graph.mounts,graph.owners,bindings)
    return graph,part,corners,checks,contract,meshes,bindings
