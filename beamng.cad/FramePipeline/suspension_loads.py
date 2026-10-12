"""Static corner balance and spring loads from the assembled mass representation.

Virtual work removes the gravity carried directly by moving suspension/wheel
masses. It is a design-height, rigid-link calculation, not a tire dynamics model.
"""
import math
import numpy as np
from scipy.optimize import minimize


def physical_settings(parameters,corner,spring,damping,preload,law=None):
    """Explicit hardware settings stay fixed when numerical ballast changes.

    Without an explicit declaration, retain the existing provisional automatic
    estimates. Require all three values to avoid silently mixing a saved spring
    with newly inferred damping or preload.
    """
    supplied=parameters.get('suspension_physical_settings',{})
    if not isinstance(supplied,dict) or set(supplied)-{'FL','FR','RL','RR'}:
        raise ValueError('Physical suspension settings must name wheel corners')
    if corner not in supplied:return spring,damping,preload,'automatic_mass_based_estimate'
    values=supplied[corner];keys=('spring_n_m','damper_ns_m','spring_preload_n')
    if not isinstance(values,dict) or set(values)!=set(keys):
        raise ValueError(corner+': explicit suspension settings require spring, damping and preload with SI units')
    if any(type(values[k]) not in (int,float) or not math.isfinite(values[k]) for k in keys):
        raise ValueError(corner+': physical suspension settings must be finite numbers')
    spring,damping,preload=(float(values[k]) for k in keys)
    if spring<=0 or damping<0 or preload<0:raise ValueError(corner+': invalid spring, damping or preload')
    if law and not math.isclose(spring,law['initial_rate_n_m'],rel_tol=1e-9,abs_tol=1e-8):
        raise ValueError(corner+': explicit spring conflicts with assigned coilover spring law')
    return spring,damping,preload,'explicit_physical_settings'


def corner_masses(hubs,mass,center):
    hubs=np.asarray(hubs,float);center=np.asarray(center,float)
    span=np.maximum(np.ptp(hubs[:,:2],axis=0),1e-6)
    matrix=np.vstack([np.ones(len(hubs)),(hubs[:,:2]/span).T])
    target=np.r_[1.,center[:2]/span];equal=np.full(len(hubs),1/len(hubs))
    fractions=equal+matrix.T@np.linalg.solve(matrix@matrix.T,target-matrix@equal)
    if min(fractions)<=1e-10:
        fit=minimize(lambda v:float(np.sum((v-equal)**2)),equal,jac=lambda v:2*(v-equal),method='SLSQP',
            bounds=[(0.,1.)]*len(hubs),constraints=[dict(type='eq',fun=lambda v:matrix@v-target,jac=lambda v:matrix)],
            options=dict(ftol=1e-12,maxiter=100))
        fractions=fit.x
        if not fit.success:raise ValueError('Vehicle COM cannot be supported by the declared wheel contact polygon')
    if min(fractions)<=1e-10 or max(abs(matrix@fractions-target))>1e-8:
        raise ValueError('Design ride height requires positive load on every wheel')
    return mass*fractions


def effective_moving_mass(allocations,positions,rigid_derivatives,point_derivatives):
    """d(sum(m*z))/d(hub travel), with separate allocations at shared pivots."""
    total=0.
    for owner,derivative in rigid_derivatives.items():
        for name,mass in allocations[owner].items():total+=mass*float((derivative@np.r_[positions[name],1.])[2])
    for owner,derivatives in point_derivatives.items():
        for name,dz in derivatives.items():total+=allocations[owner][name]*dz
    return float(total)


def axle_reference_height(model,corner):
    """Optional sag raises hubs relative to the chassis along existing joints."""
    parameters=model.data['parameters'];axle='front' if corner[0]=='F' else 'rear'
    captured=float(np.mean([model.corner_points(c)['hub'][2]
                            for c in model.data['corners'] if c[0]==corner[0]]))
    absolute=axle+'_ride_hub_height_m'
    sag=float(parameters.get(axle+'_ride_sag_m',parameters.get('ride_sag_m',0.)))
    if not math.isfinite(sag) or not 0<=sag<=.15:
        raise ValueError('Ride sag must be finite and between 0 and 150 mm')
    if absolute in parameters and sag!=0:
        raise ValueError('Choose an absolute ride hub height or ride sag, not both')
    height=float(parameters.get(absolute,captured+sag))
    if not math.isfinite(height):raise ValueError('Ride reference hub height must be finite')
    return height


def ride_reference(model,corner,alignment):
    """Automatic preload uses a common axle plane, not arbitrary CAD articulation.

    Its absolute height remains provisional unless the caller specifies it.
    Explicit False retains the legacy captured-pose interpretation for callers
    whose CAD assembly really is saved at the intended loaded ride position.
    """
    p=model.corner_points(corner);parameters=model.data['parameters']
    if not parameters.get('level_axle_ride_height',True):return 0.,0.,'captured_cad_pose'
    height=axle_reference_height(model,corner)
    if abs(height-p['hub'][2])>.15:raise ValueError(corner+': level ride reference exceeds 150 mm from captured CAD pose')
    toe=alignment.get(corner,{})
    extension=toe.get('reference_length_m',0)-toe.get('original_length_m',0)
    return height-p['hub'][2],extension,'level_axle_plane'


def configure(graph,corners,roles,model,definition,shock_options):
    from vehicle_wizard.kinematics import Mechanism
    order=list(corners);positions={n:graph.point(n) for n in graph.nodes}
    masses=np.array([v['options']['nodeWeight'] for v in graph.nodes.values()])
    total=float(sum(masses));moment=masses@np.array(list(positions.values()))
    # A CAD mate datum may lie at the inboard bearing face rather than the
    # pressure wheel's center. Use the generated axle center for support/COM.
    hubs=np.array([(positions[corners[c]['nodes']['axis_in']]+positions[corners[c]['nodes']['axis_out']])/2 for c in order])
    for corner,hub in zip(order,hubs):
        mass=corners[corner]['wheel_mass_kg'];total+=mass;moment+=mass*hub
    support=corner_masses(hubs,total,moment/total)
    parameters=definition.get('parameters',{});frequency=float(parameters.get('frequency_hz',1.5));zeta=float(parameters.get('damping_ratio',.65))
    if not math.isfinite(frequency) or frequency<=0 or not math.isfinite(zeta) or zeta<0:raise ValueError('Invalid suspension frequency/damping')
    for corner,normal_mass in zip(order,support):
        mechanism=Mechanism(model,corner);p=mechanism.p;prefix=corner.lower();step=1e-4
        height,extension,reference_kind=ride_reference(model,corner,getattr(graph,'alignment',{}))
        _,reference=mechanism.solve(height,extension)
        low,lo=mechanism.solve(height-step,extension);high,hi=mechanism.solve(height+step,extension)
        tl=mechanism.component_transforms(low,extension);th=mechanism.component_transforms(high,extension)
        derivative={k:(th[k]-tl[k])/(2*step) for k in tl}
        bodies={roles[prefix+'_trailing_arm']['Id']:derivative['trailing_arm']} if mechanism.hinged or mechanism.radius_toe or mechanism.ball_radius_toe else {
            roles[prefix+'_lower_wishbone']['Id']:derivative['lower_arm'],roles[prefix+'_upper_wishbone']['Id']:derivative['upper_arm'],
            roles[prefix+'_upright']['Id']:derivative['upright']}
        if mechanism.radius_toe or mechanism.ball_radius_toe:bodies[roles[prefix+'_upright']['Id']]=derivative['upright']
        # Wheel mass transferred onto the axle nodes still moves with the
        # carrier. Only the remaining generated rings are counted below.
        wheel_owner=roles[prefix+'_wheel']['Id']
        if wheel_owner in graph.mass_allocations:
            bodies[wheel_owner]=derivative['wheel']
        def node(key):return graph.frame_joint_nodes.get(corner+'_'+key,corner+'_'+key)
        def dz(key):return float((hi[key][2]-lo[key][2])/(2*step))
        points={roles[prefix+'_spring_damper']['Id']:{node('shock_top'):dz('shock_top'),node('shock_bottom'):dz('shock_bottom')}}
        if mechanism.wishbone:
            owner=roles[prefix+('_tie_rod' if mechanism.front else '_toe_link')]['Id']
            points[owner]={node('tie_inner'):dz('tie_inner'),node('tie_outer'):dz('tie_outer')}
        if mechanism.radius_toe or mechanism.ball_radius_toe:
            for key,suffix in [('radius_upper','upper_radius_rod'),('radius_lower','lower_radius_rod'),('tie','toe_link')]:
                owner=roles[prefix+'_'+suffix]['Id'];points[owner]={node(key+'_inner'):dz(key+'_inner'),node(key+'_outer'):dz(key+'_outer')}
        for owner,shaft in definition.get('halfshafts',{}).items():
            if shaft['corner']!=corner:continue
            name=owner+'_outer'
            points[owner]={owner+'_inner':0.,name:float((derivative['upright']@np.r_[positions[name],1.])[2])}
        ring_center=(positions[corners[corner]['nodes']['axis_in']]+positions[corners[corner]['nodes']['axis_out']])/2
        ring_dz=float((derivative['wheel']@np.r_[ring_center,1.])[2])
        unsprung=corners[corner]['wheel_mass_kg']*ring_dz+effective_moving_mass(graph.mass_allocations,positions,bodies,points)
        sprung=float(normal_mass-unsprung)
        if not math.isfinite(sprung) or sprung<=0:raise ValueError(corner+': no positive sprung load at design height')
        ratio=-(np.linalg.norm(hi['shock_bottom']-hi['shock_top'])-np.linalg.norm(lo['shock_bottom']-lo['shock_top']))/(2*step)
        if not .05<ratio<3:raise ValueError(corner+': spring does not compress during bump travel')
        omega=2*math.pi*frequency;spring=sprung*omega**2/ratio**2;damping=2*zeta*sprung*omega/ratio**2
        force=sprung*9.81/ratio
        captured_length=float(np.linalg.norm(p['shock_bottom']-p['shock_top']))
        length=float(np.linalg.norm(reference['shock_bottom']-reference['shock_top']))
        from coilover_springs import rates,crossover_beam,settings_for_corner
        settings,settings_source=settings_for_corner(roles,corner,parameters)
        law=rates(settings,length,shock_options[corner]['damper']['shortBoundRange'])
        corners[corner]['coilover_settings_source']=settings_source
        if law:
            spring=law['initial_rate_n_m']
            damping=2*zeta*math.sqrt(sprung*spring)/ratio
            crossover=crossover_beam(law)
            crossover['beamPrecompression']*=length/captured_length
            if reference_kind=='level_axle_plane':
                law.update(crossover_reference='Compression from the level axle ride reference',preload_mode='Automatic support load at the level axle ride reference')
            graph.beam(node('shock_top'),node('shock_bottom'),**crossover)
            corners[corner]['coilover_spring']=law
        spring,damping,force,source=physical_settings(parameters,corner,spring,damping,force,law)
        if law and source=='explicit_physical_settings':law['preload_mode']='Explicit physical preload; unchanged by numerical mass'
        shock_options[corner]['spring'].update(beamSpring=spring,beamPrecompression=(length+force/spring)/captured_length)
        shock_options[corner]['damper'].update(beamDamp=damping,beamPrecompression=length/captured_length,beamPrecompressionTime=0)
        corners[corner].update(spring_n_m=spring,damper_ns_m=damping,motion_ratio=ratio,suspension_settings_source=source,
            static_support_mass_kg=float(normal_mass),effective_unsprung_mass_kg=unsprung,effective_sprung_mass_kg=sprung,
            spring_preload_n=force,ride_reference=dict(kind=reference_kind,hub_height_m=float(reference['hub'][2]),
                captured_shock_length_m=captured_length,reference_shock_length_m=length),
            static_load_method='Balanced assembled mass/COM; linkage gravity derivative at '+reference_kind)
