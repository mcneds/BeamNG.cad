"""Generation-time support masses, with CAD mass and numerical additions separated."""
import math


def refit_joint_constraints(graph):
    """Fit existing numerical locators with final masses, before the global cap.

    No new constraint or change to rest geometry, travel, spring law or DOFs.
    The optional steering frequency is a rigid-link fidelity experiment, not
    a measured rod modulus. The final assembled budget may reduce these values.
    """
    import numpy as np
    from rigid_bracing import point_constraint
    report=dict(spherical=[],steering=[])
    for row in graph.spherical_constraint_rows:
        names=row[:4];xyz=np.array([graph.point(n) for n in names])
        masses=np.array([graph.nodes[n]['options']['nodeWeight'] for n in names])
        ids,spring,damp=point_constraint(xyz,masses)
        # Geometry may be permuted by the fitter, but the same four nodes stay.
        row[:4]=[names[i] for i in ids]
        row[-1].update(spring=spring,damp=damp)
        report['spherical'].append(dict(nodes=row[:4],spring=spring,damp=damp))
    frequency=getattr(graph,'steering_link_frequency_hz',None)
    if frequency is not None:
        frequency=float(frequency)
        if not math.isfinite(frequency) or not 0<frequency<=500:
            raise ValueError('Steering link numerical frequency must be finite and in (0, 500] Hz')
        for a,b,options in graph.steering_constraints:
            ma=graph.nodes[a]['options']['nodeWeight'];mb=graph.nodes[b]['options']['nodeWeight']
            reduced=ma*mb/(ma+mb)
            options['beamSpring']=reduced*(2*math.pi*frequency)**2
            report['steering'].append(dict(nodes=[a,b],reduced_mass_kg=reduced,
                requested_frequency_hz=frequency,requested_spring_n_m=options['beamSpring']))
    return report


def condition_frame_locators(part, nodes, frame_ids, frequency=160.):
    """Condition numerical shared pivots inside the frame, never moving members.

    Local CAD mount response is not calibrated by this numerical locator fit.
    Material frame edges not touching a locator retain their original values.
    """
    import numpy as np
    frame=set(frame_ids)
    patches={k:p for k,p in part.get('cadMountPatches',{}).items() if p.get('mode')=='joint'}
    locators={p['parents'][0] for p in patches.values()}
    if not locators<=frame:raise ValueError('Frame locator is outside the frame')
    defaults={};rows=[];edges={}
    for row in part['beams'][1:]:
        if isinstance(row,dict):defaults.update(row);continue
        a,b=row[:2];options=defaults|(row[-1] if isinstance(row[-1],dict) else {})
        rows.append([a,b,options]);edges.setdefault(frozenset((a,b)),[]).append(options)
        if {a,b}&locators:
            if not {a,b}<=frame or options.get('breakGroup') or options.get('beamType','|NORMAL')!='|NORMAL':
                raise ValueError('Frame locator conditioning cannot change a moving or breakaway connection')
            options.update(beamDeform=1e30,beamStrength=1e30)
    part['beams']=[part['beams'][0],*rows]
    # Angular constraints which use a locator also describe its numerical
    # position. Their stiffness remains unchanged; arbitrary fitted capacity
    # proxies cannot detach a permanently attached chassis pivot.
    for row in part.get('torsionbars',[])[1:]:
        if isinstance(row,list) and set(row[:4])<=frame and set(row[:4])&locators:
            if row[-1].get('breakGroup'):
                raise ValueError('Frame locator angular constraint crosses a moving boundary')
            row[-1].update(deform=1e30,strength=1e30)
    selected=[];reports={}
    for name,patch in patches.items():
        child=patch['parents'][0];parents=sorted(set(patch['frame_supports']))
        if not set(parents)<=frame or child in parents:raise ValueError('Invalid frame locator support')
        delta=np.array([nodes[n]['position'] for n in parents])-nodes[child]['position']
        lengths=np.linalg.norm(delta,axis=1)
        if min(lengths)<1e-7:raise ValueError('Coincident frame locator support')
        directions=delta/lengths[:,None];minimum=float(np.linalg.eigvalsh(directions.T@directions)[0])
        if minimum<.05:raise ValueError('Frame locator has insufficient directional support')
        mass=nodes[child]['options']['nodeWeight']
        spring=mass*(2*math.pi*frequency)**2/minimum
        for parent in parents:
            found=edges.get(frozenset((child,parent)),[])
            if len(found)!=1:raise ValueError('Frame locator requires one existing support edge')
            options=found[0];other=nodes[parent]['options']['nodeWeight'];reduced=mass*other/(mass+other)
            options.update(beamSpring=max(options.get('beamSpring',0),spring),
                           beamDamp=.12*math.sqrt(spring*reduced))
            selected.append(options)
        reports[name]=dict(node=child,parents=parents,requested_frequency_hz=frequency,
                           minimum_direction_eigenvalue=minimum)
    return selected,dict(patches=reports,material_response_qualified=False,
        scope='Existing chassis-side locator edges conditioned with final masses and the assembled timestep budget; no moving suspension connections added. Locator damage proxies disabled; frame material and fracture qualification must be repeated.')


def rigid_allocations(graph):
    """Expand logical CAD owners into their independently moving rigid members.

    Accounting still belongs to the CAD component. Rigidity must never combine
    its rack and housing into one block, including after support mass is added.
    """
    result=dict(graph.mass_allocations)
    members=graph.rigid_member_allocations
    for owner in {v['owner'] for v in members.values()}:
        combined=result.pop(owner)
        selected={key:v['weights'] for key,v in members.items() if v['owner']==owner}
        totals={n:sum(v.get(n,0) for v in selected.values()) for n in combined}
        if any(v<=0 for v in totals.values()):raise ValueError('Incomplete moving-member mass ownership: '+owner)
        for key,weights in selected.items():
            result[key]={n:combined[n]*weight/totals[n] for n,weight in weights.items()}
    return result


def wishbone_support_targets(graph,corners,floor):
    """Numerical conditioning heuristic for narrow pivot pairs, not material mass.

    Fore/aft displacement amplification grows with arm reach / pivot span.
    Above a ratio of two, increase the support budget with its squared ratio.
    Apply the larger axle-side budget to both sides to avoid introducing an
    asymmetry from roundoff or the captured articulation. Native response tests
    remain necessary; this is not a universal stability or stiffness guarantee.
    """
    import numpy as np
    targets={};report=[]
    for axle in ('F','R'):
        for arm in ('upper','lower'):
            members=[]
            for corner,wheel in corners.items():
                if not corner.startswith(axle):continue
                mapping=wheel['hardpoint_nodes'];keys=[arm+'_'+s for s in ('inner_front','inner_rear','ball')]
                if not all(k in mapping for k in keys):continue
                names=[mapping[k] for k in keys];a,b,p=[np.asarray(graph.nodes[n]['position'],float) for n in names]
                span=float(np.linalg.norm(b-a))
                if span<1e-6:raise ValueError(corner+': coincident wishbone pivot pair')
                reach=float(np.linalg.norm(np.cross(p-a,b-a))/span)
                members.append((corner,names,reach/span))
            if not members:continue
            ratio=max(row[2] for row in members)
            multiplier=max(1,math.ceil((ratio/2.)**2-1e-9))
            for corner,names,aspect in members:
                for n in names:targets[n]=max(targets.get(n,floor),floor*multiplier)
                report.append(dict(corner=corner,member=arm,reach_to_pivot_span=aspect,
                                   support_target_kg=floor*multiplier,nodes=names))
    return targets,report


def allocate_support_mass(graph, corners, engine_reactions, parameters):
    policy=parameters.get('loaded_node_mass_policy','reported_ballast')
    if policy not in ('reported_ballast','preserve_cad','redistribute_then_ballast'):
        raise ValueError('Loaded node mass policy must be reported_ballast, preserve_cad or redistribute_then_ballast')
    target=float(parameters.get('minimum_loaded_node_kg',2.))
    if not math.isfinite(target) or target<=0:raise ValueError('Loaded node mass target must be positive')
    requested={};role_targets=parameters.get('loaded_hardpoint_mass_targets_kg',{})
    available={key for wheel in corners.values() for key in wheel['hardpoint_nodes']}
    if not isinstance(role_targets,dict) or set(role_targets)-available:
        raise ValueError('Loaded hardpoint mass targets must name existing hardpoint roles')
    role_targets={key:float(value) for key,value in role_targets.items()}
    if any(not math.isfinite(value) or value<target for value in role_targets.values()):
        raise ValueError('Hardpoint mass targets must be finite and at least the loaded node floor')
    requested_targets={}
    geometry_targets,geometry_report=(wishbone_support_targets(graph,corners,target)
        if parameters.get('condition_wishbone_support_mass',True) else ({},[]))
    wheel_target=float(parameters.get('minimum_wheel_support_node_kg',target))
    if not math.isfinite(wheel_target) or wheel_target<=0:raise ValueError('Wheel support mass target must be positive')
    axle_nodes={wheel['nodes'][key] for wheel in corners.values() for key in ('axis_in','axis_out')}
    def request(node,reason):
        if node not in graph.nodes:raise ValueError('Missing loaded node: '+node)
        requested.setdefault(node,[]).append(reason)
    for corner,wheel in corners.items():
        for key,node in wheel['hardpoint_nodes'].items():
            request(node,corner+':'+key)
            requested_targets[node]=max(requested_targets.get(node,target),role_targets.get(key,geometry_targets.get(node,target)))
        for key in ('axis_in','axis_out'):request(wheel['nodes'][key],corner+':'+key)
        for key,node in wheel.get('reaction_nodes',{}).items():request(node,corner+':'+key)
    for node in engine_reactions:request(node,'engine torque reaction')
    for section in getattr(graph,'driveline_physics',{}).get('sections',[]):
        for node in section['endpoints']:request(node,'driveline shaft joint')
    for rail in getattr(graph,'driveline_physics',{}).get('rails',[]):
        for key in ('a','b','slider'):request(rail[key],'driveline sliding interface')
    for node in getattr(graph,'rigidifier_nodes',()):request(node,'internal non-colliding member rigidifier')
    # Both sides of a mechanical joint receive its forces. In particular,
    # spherical shaft supports can select residual CAD-moment nodes on a
    # carrier, not just named suspension hardpoints. Flooring only the shaft
    # endpoints left those directly loaded carrier nodes at a few grams.
    # No beam is added across a plunge/rotational degree of freedom.
    for joint in graph.joints:
        if joint['kind']=='telescopic':
            for node in joint['nodes']:request(node,'shaft endpoint')
    loaded=set(requested)
    for joint in graph.joints:
        if joint['kind']=='spherical' and joint['nodes'][-1] in loaded:
            for node in joint['nodes']:request(node,'loaded spherical support: '+joint.get('id','spherical'))
    original_masses={n:float(v['options']['nodeWeight']) for n,v in graph.nodes.items()}
    final_targets={node:max(target,wheel_target if node in axle_nodes else target,requested_targets.get(node,target)) for node in requested}
    redistribution=None
    if policy=='redistribute_then_ballast':
        from support_mass_fit import redistribute
        redistribution=redistribute(graph,final_targets,float(parameters.get('minimum_redistribution_donor_kg',.25)))
    rows={};added_by_owner={}
    for node,reasons in sorted(requested.items()):
        options=graph.nodes[node]['options'];before=float(options['nodeWeight'])
        owners={owner:values[node] for owner,values in graph.mass_allocations.items() if values.get(node,0)>0}
        if not owners or abs(sum(owners.values())-before)>max(1e-8,before*1e-8):
            raise ValueError('Loaded node has incomplete mass ownership: '+node)
        node_target=max(target,wheel_target) if node in axle_nodes else target
        node_target=max(node_target,requested_targets.get(node,target))
        extra=max(0.,node_target-before) if policy!='preserve_cad' else 0.
        contributions={}
        for owner,mass in owners.items():
            added=extra*mass/before
            graph.mass_allocations[owner][node]+=added
            added_by_owner[owner]=added_by_owner.get(owner,0.)+added
            contributions[owner]=added
        options['nodeWeight']=before+extra
        rows[node]=dict(reasons=sorted(set(reasons)),target_kg=node_target,cad_assembled_mass_kg=original_masses[node],
                        redistributed_cad_mass_kg=before,
                        simulated_mass_kg=before+extra,added_mass_kg=extra,added_by_component_kg=contributions)
    added=sum(v['added_mass_kg'] for v in rows.values())
    for owner,extra in added_by_owner.items():
        if owner in graph.reports:graph.reports[owner]['numerical_added_mass_kg']=extra
    graph.numerical_mass=dict(policy=policy,target_kg=target,added_mass_kg=added,
        added_by_component_kg=added_by_owner,nodes=rows,
        wishbone_geometry_conditioning=geometry_report,redistribution=redistribution,
        below_target_nodes=[node for node,row in rows.items() if row['simulated_mass_kg']<row['target_kg']-1e-9],
        scope='Additional numerical support mass is simulated and included in suspension loads; it is not CAD/material mass.',
        material_mass_equivalent=added==0)
    return graph.numerical_mass
