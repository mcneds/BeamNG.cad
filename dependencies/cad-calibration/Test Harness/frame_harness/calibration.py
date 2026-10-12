"""Reproducible CAD-material calibration on an immutable node/beam graph."""
from __future__ import annotations

import copy
import html
import json
import shutil
from dataclasses import asdict
from pathlib import Path

import numpy as np
from scipy.optimize import lsq_linear, minimize
from scipy.linalg import eigh

from .build import ASSETS, SOURCES, beam_table, node_table, sha256, write_json
from .cad import audit_body, extract_member, read_bodies
from .models import ParameterSet, TestScenario
from .generation import inputs, scenario as configured_scenario
from .projection import axial_columns, modal_frequencies, project_springs, reduced_mass_damping

MATERIAL_CASES = {
    '4130-annealed': {'yield_pa':360.6e6, 'ultimate_pa':560.5e6},
    '4130-normalized': {'yield_pa':436.4e6, 'ultimate_pa':668.8e6},
}
MATERIAL_SOURCE = 'https://www.admiralsteel.com/assets/pdf/catalog.pdf'
# Dense mounting load cases can keep improving after 10,000 iterations. This
# increases the fitting budget only; response, yield and modal limits are
# unchanged, and the existing convergence callback can still finish early.
ELASTIC_FIT_MAX_ITERATIONS = 20000
# Seed springs can differ by orders of magnitude on a regenerated graph.
# This is a positive-coefficient search range, not a material/stability limit:
# the modal projection and independent response checks remain authoritative.
ELASTIC_FIT_LOG_BOUNDS = (-12., 10.)


def load_part(path, part_name="mochi"):
    return json.loads('\n'.join(line for line in path.read_text(encoding='utf-8').splitlines() if not line.lstrip().startswith('//')))[part_name]


def graph_identity(part):
    from .torsion import table
    result={'nodes':{n:v['position'] for n,v in node_table(part).items()},
            'beams':[[b['a'],b['b']] for b in beam_table(part)]}
    if table(part):result['torsionbars']=[v['nodes'] for v in table(part)]
    return result


def mass_properties(audits, density):
    densities=np.broadcast_to(np.asarray(density,dtype=float),(len(audits),))
    masses = np.array([a.get('native_mass_kg',a['volume_m3']*d) for a,d in zip(audits,densities)]); centers = np.array([a['center_m'] for a in audits])
    mass = masses.sum(); center = masses@centers/mass; inertia = np.zeros((3,3))
    for a,m,c,d in zip(audits,masses,centers,densities):
        r = c-center
        inertia += m/a['volume_m3']*np.array(a['inertia_per_density'])+m*(np.dot(r,r)*np.eye(3)-np.outer(r,r))
    return float(mass), center, inertia


def fit_masses(positions, mass, center, inertia, minimum_weights=None):
    r = positions-center; scale = max(np.linalg.norm(np.ptp(positions,axis=0)),1e-3)
    x,y,z = (r/scale).T
    features = np.array([np.ones(len(r)),x,y,z,y*y+z*z,x*x+z*z,x*x+y*y,-x*y,-x*z,-y*z])
    target = np.r_[1,np.zeros(3),inertia.diagonal()/(mass*scale**2),inertia[0,1]/(mass*scale**2),inertia[0,2]/(mass*scale**2),inertia[1,2]/(mass*scale**2)]
    weights = np.array([1000,100,100,100,10,10,10,10,10,10])
    # Mass moments underdetermine the node weights. A generic least-squares
    # solution can starve loaded nodes and force the modal cap to soften every
    # spring. Maximize the smallest weight while preserving all CAD moments.
    from scipy.optimize import linprog
    count=len(positions)
    importance=np.ones(count) if minimum_weights is None else np.asarray(minimum_weights,dtype=float)
    if importance.shape!=(count,) or not np.isfinite(importance).all() or np.any(importance<=0):raise ValueError('Mass allocation weights must be finite and positive')
    balanced=linprog(np.r_[np.zeros(count),-1.],
        A_ub=np.column_stack((-np.eye(count),importance)),b_ub=np.zeros(count),
        A_eq=np.column_stack((features,np.zeros(len(target)))),b_eq=target,
        bounds=[(0,None)]*(count+1),method='highs')
    exact=balanced.success and balanced.x[-1]>1e-5
    fractions = balanced.x[:-1] if exact else lsq_linear(features*weights[:,None],target*weights,bounds=(1e-5,np.inf),tol=1e-12,max_iter=1000).x
    balancing=None
    if exact:
        from .mass_balance import balance
        # Retain 99.9% of the optimal minimum to leave an interior feasible
        # polytope for the unique second-stage allocation.
        fractions,balancing=balance(features,target,fractions,importance*balanced.x[-1]*.999,importance)
    masses = fractions/fractions.sum()*mass
    actual_center = masses@positions/mass
    rr = positions-actual_center
    actual_inertia = sum(m*(np.dot(v,v)*np.eye(3)-np.outer(v,v)) for m,v in zip(masses,rr))
    report = {'target_mass_kg':mass,'actual_mass_kg':float(masses.sum()),'center_error_m':float(np.linalg.norm(actual_center-center)),
              'inertia_relative_error':float(np.linalg.norm(actual_inertia-inertia)/np.linalg.norm(inertia)),
              'minimum_node_mass_kg':float(masses.min()),'target_center_m':center.tolist(),'actual_center_m':actual_center.tolist(),
              'target_inertia_kg_m2':inertia.tolist(),'actual_inertia_kg_m2':actual_inertia.tolist(),
              'allocation_method':'maximum minimum positive mass with exact CAD moments' if exact else 'bounded approximate CAD moments',
              'maximum_minimum_mass_kg':float(balanced.x[-1]*mass) if balanced.success else None}
    if minimum_weights is not None:
        report['allocation_method']='maximum minimum mass relative to CAD proximity weights; exact CAD moments' if exact else report['allocation_method']
        report['allocation_weights']=importance.tolist()
    if balancing is not None:report['balance']=balancing
    report['accepted'] = report['center_error_m']<=.005 and report['inertia_relative_error']<=.05
    return masses,report


def graph_response(columns, springs, names, scenario):
    free = np.array([3*i+j for i,n in enumerate(names) if n not in scenario.fixed_nodes for j in range(3)])
    matrix = columns[free]; load = np.zeros(3*len(names))
    for n,v in scenario.resolved_load_vectors().items():
        load[3*names.index(n):3*names.index(n)+3] = v
    k = (matrix*springs)@matrix.T
    u = np.zeros_like(load); u[free] = np.linalg.solve(k,load[free])
    return float(load@u), springs*(columns.T@u)


def fit_yield_capacities(initial, forces, targets):
    """Fit first onset without allowing another calibrated load to yield early.

    Each scenario imposes a lower bound |unit beam force| * target external
    yield load. A separating active constraint establishes onset in each case.
    If the patterns cannot realize distinct onsets, retain the envelope and
    expose that limitation through the response errors.
    """
    names=list(forces)
    required=np.array([abs(forces[n])*targets[n]['first_yield_force_n'] for n in names])
    envelope=required.max(axis=0);capacity=np.maximum(initial,envelope)
    active={}
    for i,name in enumerate(names):
        eligible=np.flatnonzero((required[i]>1e-12)&(required[i]>=envelope*(1-1e-10)))
        if not len(eligible):
            active[name]=None;continue
        selected=int(eligible[np.argmin(abs(np.log(required[i,eligible]/initial[eligible])))])
        capacity[selected]=envelope[selected];active[name]=selected
    return capacity,{'active_beam_indices':active,'method':'onset capacity envelope for independently calibrated load patterns',
                     'minimum_multiplier':float(np.min(capacity/initial)),'maximum_multiplier':float(np.max(capacity/initial))}


def surface_distances(points, body):
    """Exact point-to-triangle minimum, including edge/vertex Voronoi regions."""
    t = body.vertices[body.faces]; a,b,c = t[:,0],t[:,1],t[:,2]
    ab,ac = b-a,c-a; normal = np.cross(ab,ac); nn = np.sum(normal*normal,axis=1)
    result = []
    for p in points:
        ap = p-a; signed = np.sum(ap*normal,axis=1)
        projected = p-signed[:,None]*normal/np.maximum(nn[:,None],1e-30)
        v = projected-a
        d00,d01,d11 = np.sum(ab*ab,axis=1),np.sum(ab*ac,axis=1),np.sum(ac*ac,axis=1)
        d20,d21 = np.sum(v*ab,axis=1),np.sum(v*ac,axis=1)
        den = d00*d11-d01*d01
        u = (d11*d20-d01*d21)/np.maximum(den,1e-30); w = (d00*d21-d01*d20)/np.maximum(den,1e-30)
        best = np.where((u>=0)&(w>=0)&(u+w<=1),signed*signed/np.maximum(nn,1e-30),np.inf)
        for q,r in ((a,b),(b,c),(c,a)):
            edge = r-q; fraction = np.clip(np.sum((p-q)*edge,axis=1)/np.maximum(np.sum(edge*edge,axis=1),1e-30),0,1)
            best = np.minimum(best,np.sum((p-q-fraction[:,None]*edge)**2,axis=1))
        result.append(np.sqrt(best.min()))
    return np.array(result)


def associate(part, bodies):
    nodes = node_table(part); names = list(nodes); xyz = np.array([nodes[n]['position'] for n in names])
    shell = np.array([i for i,n in enumerate(names) if n.startswith('sh')]); edges = beam_table(part)
    adjacency = {i:set() for i in shell}
    for e in edges:
        a,b = names.index(e['a']),names.index(e['b'])
        if a in adjacency and b in adjacency:
            adjacency[a].add(b); adjacency[b].add(a)
    memberships = {n:[] for n in names}; rows = []; reports = []
    for body in bodies:
        distance = surface_distances(xyz[shell],body)
        # Each vertex needs a local locator basis. Global noncollinearity alone
        # allowed 16 meshes to fail VY selection in Drive, even with 12 nodes.
        nearest=np.argsort(np.linalg.norm(body.vertices[:,None,:]-xyz[shell][None,:,:],axis=2),axis=1)
        selected=set(int(i) for i in shell[nearest[:,:4]].ravel())
        for order in np.unique(nearest[:,:2],axis=0):
            center,vx=map(int,shell[order]);axis=xyz[vx]-xyz[center];axis/=np.linalg.norm(axis)
            delta=xyz[shell]-xyz[center];length=np.linalg.norm(delta,axis=1)
            direction=delta/np.maximum(length[:,None],1e-12)
            perpendicular=np.abs(direction@axis)
            candidates=np.flatnonzero((length>1e-6)&(perpendicular<.5))
            if len(candidates):
                iy=int(candidates[np.argmin(distance[candidates]+.25*length[candidates])]);selected.add(int(shell[iy]))
                normal=np.cross(axis,direction[iy]);normal/=np.linalg.norm(normal)
                candidates=np.flatnonzero((length>1e-6)&(np.abs(direction@normal)>.5))
                if len(candidates):selected.add(int(shell[candidates[np.argmin(distance[candidates]+.25*length[candidates])]]))
        # Join the required locators using existing shell edges, preferring
        # paths near the CAD surface. No helper nodes or new beams are introduced.
        import heapq
        required=set(selected);selected={min(required,key=lambda i:distance[np.where(shell==i)[0][0]])}
        while not required.issubset(selected):
            queue=[(0.,i,[]) for i in selected];heapq.heapify(queue);seen=set();found=False
            while queue:
                cost,i,path=heapq.heappop(queue)
                if i in seen:continue
                seen.add(i)
                if i in required-selected:
                    selected.update(path+[i]);found=True;break
                for j in adjacency[i]-seen:
                    heapq.heappush(queue,(cost+np.linalg.norm(xyz[j]-xyz[i])*(1+distance[np.where(shell==j)[0][0]]),j,path+[i]))
            if not found:raise ValueError('Shell graph cannot connect CAD mesh locators for '+body.name)
        group = 'cad_'+body.name; rows.append([body.name,[group]])
        for i in selected:
            memberships[names[i]].append(group)
        pts = xyz[sorted(selected)]; spread = np.linalg.svd(pts-pts.mean(0),compute_uv=False)
        reports.append({'mesh':body.name,'nodes':[names[i] for i in sorted(selected)],
                        'surface_distance_max_m':float(surface_distances(pts,body).max()),
                        'vertex_coverage_max_m':float(np.linalg.norm(body.vertices[:,None,:]-pts[None,:,:],axis=2).min(axis=1).max()),
                        'noncollinear':bool(len(spread)>=2 and spread[1]>1e-5),'binding':'engine node-group binding; no authored per-vertex weights'})
    for row in part['nodes'][1:]:
        if isinstance(row,list):
            if len(row)==4: row.append({})
            groups = nodes[row[0]]['options'].get('group',[])
            if isinstance(groups,str): groups=[groups]
            row[4]['group'] = [g for g in groups if not g.startswith(('mochi_part_','cad_'))]+memberships[row[0]]
    part['flexbodies'] = [['mesh','[group]:','nonFlexMaterials'],*rows]
    return reports


def configure_mesh_breaking(part, associations, native_mesh=True):
    """A shell edge can support visible interpolation even if its midpoint is in air."""
    membership={name:set() for name in node_table(part)}
    for association in associations:
        for name in association['nodes']:membership[name].add(association['mesh'])
    visible=[]
    for row in part['beams'][1:]:
        if not isinstance(row,list):continue
        a,b=row[:2]
        supports_mesh=bool(membership[a]&membership[b])
        row[2].update(disableMeshBreaking=not (supports_mesh and native_mesh),disableTriangleBreaking=not supports_mesh)
        visible.append(supports_mesh)
    return visible


def make_candidate(part, bodies, audits, targets, material, config, elastic_template=None, symmetry_sections=None, elastic_seed=None):
    fit_target=float(config.get('elastic_fit_target_error',.01))
    if not np.isfinite(fit_target) or not 0<fit_target<=.08:
        raise ValueError('Elastic fit stopping target must be positive and at most 8%; acceptance remains independently checked')
    part = copy.deepcopy(part); nodes = node_table(part); names = list(nodes)
    xyz = np.array([nodes[n]['position'] for n in names]); edges = beam_table(part)
    endpoints = np.array([[names.index(e['a']),names.index(e['b'])] for e in edges])
    columns,lengths,directions = axial_columns(xyz,endpoints)
    from .torsion import table as torsion_table, columns as torsion_columns
    torsions=torsion_table(part);axial_count=len(edges)
    angular_ids=[[names.index(n) for n in t['nodes']] for t in torsions]
    if torsions:
        columns=np.column_stack((columns,torsion_columns(xyz,angular_ids)))
    assigned=material.get('bodies')
    physical=[assigned[b.name] if assigned is not None else dict(material,young_pa=config['young_pa'],density_kg_m3=config['density_kg_m3']) for b in bodies]
    mass,center,inertia = mass_properties(audits,[m['density_kg_m3'] for m in physical])
    # Mounting locators can outnumber physical shell nodes. Equal lower bounds
    # then put much of the frame mass in those numerical helpers and starve the
    # members carrying load. Prefer nodes near actual CAD, with a nonzero floor
    # everywhere; the independent mass/COM/inertia constraints remain exact.
    nearest=np.min([surface_distances(xyz,body) for body in bodies],axis=0)
    proximity_length=max(np.linalg.norm(np.ptp(xyz,axis=0))*.025,1e-6)
    minimum_weights=1+3*np.exp(-(nearest/proximity_length)**2)
    structural={n for p in part.get('cadMountPatches',{}).values() if p.get('mode')=='joint' for n in p['parents']}
    for i,n in enumerate(names):
        if n in structural:minimum_weights[i]=12.
    # Protect the global reference load nodes as well. Adding many pivots must
    # not starve the shell points used to measure whole-frame flex/torsion.
    global_loads={n for case in ('flex','torsion') for n in configured_scenario(config,case).load_nodes}
    reactions={n for case in ('flex','torsion') for n in configured_scenario(config,case).fixed_nodes}
    for i,n in enumerate(names):
        if n in global_loads:minimum_weights[i]=max(minimum_weights[i],24.)
        # Fixture reactions are force application points too. Starving these
        # shell nodes can cap the entire frame's usable spring stiffness.
        if structural and n in reactions:minimum_weights[i]=max(minimum_weights[i],12.)
    masses,mass_report = fit_masses(xyz,mass,center,inertia,minimum_weights)
    mass_report['cad_proximity_length_m']=float(proximity_length)
    mass_report['loaded_frame_mass_contributions_kg']={n:float(masses[names.index(n)]) for n in sorted(structural|global_loads|reactions)}
    mid = xyz[endpoints].mean(axis=1)
    characteristic=lengths.copy()
    if torsions:
        mid=np.vstack((mid,xyz[angular_ids].mean(axis=1)))
        axis=xyz[np.array(angular_ids)[:,2]]-xyz[np.array(angular_ids)[:,1]]
        characteristic=np.r_[characteristic,np.linalg.norm(axis,axis=1)]
        directions=np.vstack((directions,axis/np.linalg.norm(axis,axis=1)[:,None]))
        # Axial energy is E*V*(extension/L)^2; angular energy is E*V*angle^2.
        # Capacities are N for axial rows and Nm for angular rows.
        lengths=np.r_[lengths,np.ones(len(torsions))]
    count=columns.shape[1];volume=np.zeros(count)
    raw=np.zeros(count);initial_yield=np.zeros(count);initial_ultimate=np.zeros(count)
    for body,audit,properties in zip(bodies,audits,physical):
        distance = surface_distances(mid,body)
        width = max(.05,np.linalg.norm(np.ptp(body.vertices,axis=0))*.2)
        weight = np.exp(-np.minimum((distance/width)**2,700))*characteristic
        volume_for_material=audit.get('native_mass_kg',audit['volume_m3']*properties['density_kg_m3'])/properties['density_kg_m3']
        contribution=volume_for_material*weight/weight.sum()
        volume += contribution
        raw += properties['young_pa']*contribution/lengths**2
        initial_yield += properties['yield_pa']*contribution/lengths
        initial_ultimate += properties['ultimate_pa']*contribution/lengths
    from .reflection import constraint_groups,average_groups
    coefficient_groups,reflection_report=constraint_groups(part,symmetry_sections,audits,
        {b.name:dict({'poisson':config.get('poisson',.29)},**properties) for b,properties in zip(bodies,physical)})
    if reflection_report['applied']:raw=average_groups(raw,coefficient_groups)
    areas = volume/lengths
    springs=raw*min(1.,(config['frequency_limit_hz']/modal_frequencies(columns,masses,raw)[-1])**2)
    # Fit families, not unconstrained independent edges: dominant orientation x longitudinal region.
    region = np.minimum(2,((mid[:,1]-mid[:,1].min())/max(np.ptp(mid[:,1]),1e-9)*3).astype(int))
    family = np.argmax(abs(directions),axis=1)+3*region
    fit_log = {'attempted':False}
    # A frame calibrated in isolation cannot reproduce arbitrarily stiff welded
    # local details at a finite explicit timestep. Preserve the physical target
    # in the audit; local connection fitting uses a documented numerical ceiling.
    # C >= f^T M^-1 f / omega_max^2 is necessary under the modal stiffness cap.
    # Reserving 3/4 of the modal budget for other coupled directions gives a
    # practical four-times-bound ceiling. This is NOT physical CAD acceptance.
    local_targets={}
    for name,target in targets.items():
        if name in ('flex','torsion'):continue
        scenario=configured_scenario(config,name)
        bound=sum(np.dot(v,v)/masses[names.index(n)] for n,v in scenario.resolved_load_vectors().items())/(2*np.pi*config['frequency_limit_hz'])**2
        local_targets[name]=dict(cad_compliance_m_n=target['compliance_m_n'],modal_compliance_lower_bound_m_n=float(bound),
                                compliance_ceiling_m_n=max(target['compliance_m_n'],4*float(bound)),modal_budget_fraction=.25)
    if elastic_template is not None:
        template,template_report=elastic_template
        springs=np.r_[[b['spring'] for b in beam_table(template)],[v['options']['spring'] for v in torsion_table(template)]]
        fit_log=copy.deepcopy(template_report['fit'])
        fit_log['elastic_reused']='Same CAD, density, E and Poisson ratio in both material-condition cases'
    required=set(config.get('reference_cases',('flex','torsion')))
    response_pairs=[]
    for pair in config.get('reference_response_pairs',[]):
        if len(pair)!=2 or pair[0]==pair[1] or not set(pair)<=required:
            raise ValueError('Invalid paired reference response: '+str(pair))
        if not set(pair)<=set(targets):continue
        response_pairs.append((pair[0],pair[1],targets[pair[0]]['compliance_m_n']/targets[pair[1]]['compliance_m_n']))
    complete={'flex','torsion'}<=required and required<=set(targets)
    if complete and elastic_template is None:
        from .elastic_fit import objective as response_objective
        from scipy.sparse import csc_matrix
        weighted=csc_matrix(columns/np.sqrt(np.repeat(masses,3))[:,None])
        cases=[];matrices={}
        for name,target in targets.items():
            scenario=configured_scenario(config,name)
            free=np.array([3*i+j for i,n in enumerate(names) if n not in scenario.fixed_nodes for j in range(3)])
            load=np.zeros(3*len(names))
            for n,v in scenario.resolved_load_vectors().items():load[3*names.index(n):3*names.index(n)+3]=v
            key=tuple(free)
            if key not in matrices:matrices[key]=csc_matrix(columns[free])
            cases.append((matrices[key],load[free],local_targets[name]['compliance_ceiling_m_n'],True) if name in local_targets
                         else (matrices[key],load[free],target['compliance_m_n']))
        limit=(2*np.pi*config['frequency_limit_hz'])**2
        case_names=list(targets)
        paired_indices=[(case_names.index(a),case_names.index(b),ratio) for a,b,ratio in response_pairs]
        initial=springs.copy()
        def objective(values):
            value,gradient,_=response_objective(values[family],initial,weighted,cases,limit,regularizer=0,response_pairs=paired_indices)
            return value+.001*float(values@values),np.bincount(family,weights=gradient,minlength=9)+.002*values
        fit=minimize(objective,np.zeros(9),jac=True,method='L-BFGS-B',bounds=[(-4,4)]*9,options={'maxiter':80,'ftol':1e-9})
        springs=initial*np.exp(fit.x[family]); highest=modal_frequencies(columns,masses,springs)[-1]
        if highest>config['frequency_limit_hz']: springs *= (config['frequency_limit_hz']/highest)**2
        fit_log={'attempted':True,'optimizer_success':bool(fit.success),'objective':float(fit.fun),'family_log_multipliers':fit.x.tolist()}
        # Refine individual weights on the same graph. Analytic sensitivities make
        # this practical and avoid mistaking a restrictive family fit for a
        # fundamental limitation of the existing node layout.
        initial=springs.copy();last_fit={}
        if elastic_seed is not None:
            if graph_identity(elastic_seed)!=graph_identity(part):raise ValueError('Elastic seed graph differs from this generation')
            seed=np.r_[[b['spring'] for b in beam_table(elastic_seed)],
                       [v['options']['spring'] for v in torsion_table(elastic_seed)]]
            if seed.shape!=initial.shape or not np.isfinite(seed).all() or np.any(seed<=0):
                raise ValueError('Elastic seed requires positive finite stiffness on the same graph')
            initial=seed.copy()
            initial*=min(1.,(config['frequency_limit_hz']/modal_frequencies(columns,masses,initial)[-1])**2)
            fit_log['elastic_seed']='Sealed source graph stiffness used only as optimizer initialization; all current CAD and numerical criteria reevaluated'
        if reflection_report['applied']:initial=average_groups(initial,coefficient_groups)
        def edge_objective(values):
            expanded=values[coefficient_groups]
            value,gradient,stats=response_objective(expanded,initial,weighted,cases,limit,response_pairs=paired_indices)
            last_fit.update(values=values.copy(),stats=stats)
            return value,np.bincount(coefficient_groups,weights=gradient,minlength=len(values))
        from .progress import emit
        iterations=0
        def fit_progress(values):
            nonlocal iterations
            iterations+=1
            if iterations%25==0:
                errors=last_fit['stats']['projected_relative_errors']
                emit('Stiffness fit',completed=iterations,total=ELASTIC_FIT_MAX_ITERATIONS,
                     detail=f'Max response error {max(errors):.1%}; flex {errors[0]:.1%}, torsion {errors[1]:.1%}; {len(errors)} load cases')
                if np.array_equal(values,last_fit['values']) and max(errors)<fit_target:raise StopIteration
        coefficient_count=int(coefficient_groups.max())+1
        refinement=minimize(edge_objective,np.zeros(coefficient_count),jac=True,method='L-BFGS-B',bounds=[ELASTIC_FIT_LOG_BOUNDS]*coefficient_count,callback=fit_progress,
                            options={'maxiter':ELASTIC_FIT_MAX_ITERATIONS,'maxfun':30*ELASTIC_FIT_MAX_ITERATIONS,'ftol':1e-10,'maxls':30,'maxcor':50})
        springs=initial*np.exp(refinement.x[coefficient_groups]); highest=modal_frequencies(columns,masses,springs)[-1]
        if highest>config['frequency_limit_hz']: springs*=(config['frequency_limit_hz']/highest)**2
        fit_log['edge_refinement']={'success':bool(refinement.success),'message':str(refinement.message),
                                    'objective':float(refinement.fun),'iterations':int(refinement.nit),
                                    'evaluations':int(refinement.nfev),'iteration_budget':ELASTIC_FIT_MAX_ITERATIONS,
                                    'evaluation_budget':30*ELASTIC_FIT_MAX_ITERATIONS,
                                    'log_multipliers':refinement.x[coefficient_groups].tolist(),'log_bounds':list(ELASTIC_FIT_LOG_BOUNDS),
                                    'target_max_response_error':fit_target}
    yield_force=initial_yield.copy()
    damage_targets={name:target for name,target in targets.items() if name in config.get('reference_cases',('flex','torsion'))}
    if {'flex','torsion'}<=set(damage_targets):
        stresses={s:graph_response(columns,springs,names,configured_scenario(config,s))[1] for s in damage_targets}
        def damage_objective(values):
            trial=yield_force*np.exp(values[family])
            return sum(np.log(1/np.max(abs(stresses[s])/trial)/damage_targets[s]['first_yield_force_n'])**2 for s in ('flex','torsion'))+.01*float(values@values)
        fit=minimize(damage_objective,np.zeros(9),method='L-BFGS-B',bounds=[(-3,3)]*9,options={'maxiter':100})
        yield_force*=np.exp(fit.x[family])
        fit_log['damage_family_log_multipliers']=fit.x.tolist()
        # Every declared load path needs its independently derived yield floor.
        # A stiffness fit alone allowed a local pivot edge to break during normal
        # driving even though the two global yield tests matched. The envelope
        # preserves separating global onsets where the graph can represent them;
        # incompatible targets remain visible and cannot qualify physically.
        yield_force,fit_log['damage_refinement']=fit_yield_capacities(yield_force,stresses,damage_targets)
    strength=yield_force*initial_ultimate/initial_yield
    damping=reduced_mass_damping(springs[:axial_count],masses,endpoints,config['damping_ratio'])
    if not torsions and reflection_report['applied']:damping=average_groups(damping,coefficient_groups)
    damping_report=None
    if torsions:
        weighted=columns/np.sqrt(np.repeat(masses,3))[:,None]
        inverse_inertia=np.sum(weighted[:,axial_count:]**2,axis=0)
        damping=np.r_[damping,2*config['damping_ratio']*np.sqrt(springs[axial_count:]/inverse_inertia)]
        if reflection_report['applied']:damping=average_groups(damping,coefficient_groups)
        dt=.0005
        stiffness_bound=dt*dt*np.linalg.eigvalsh((weighted*springs)@weighted.T)[-1]
        damping_bound=2*dt*np.linalg.eigvalsh((weighted*damping)@weighted.T)[-1]
        factor=min(1.,max(0.,2.-stiffness_bound)/max(damping_bound,1e-12));damping*=factor
        damping_report=dict(step_seconds=dt,step_budget=2.,damping_scale=float(factor),
            final_step_eigenvalue=float(np.linalg.eigvalsh((weighted*(dt*dt*springs+2*dt*damping))@weighted.T)[-1]))
    for row in part['nodes'][1:]:
        if isinstance(row,list):
            if len(row)==4: row.append({})
            row[4]['nodeWeight']=float(masses[names.index(row[0])])
    for row,k,c,fy,fu in zip([r for r in part['beams'][1:] if isinstance(r,list)],springs,damping,yield_force,strength):
        if len(row)==2: row.append({})
        row[2].update(beamSpring=float(k),beamDamp=float(c),beamDeform=float(fy),beamStrength=float(fu),
                      disableMeshBreaking=True,disableTriangleBreaking=True,breakGroup='')
    if torsions:
        part['torsionbars']=[['id1:','id2:','id3:','id4:']]+[
            [*t['nodes'],t['options']|dict(spring=float(k),damp=float(c),deform=float(fy),strength=float(fu))]
            for t,k,c,fy,fu in zip(torsions,springs[axial_count:],damping[axial_count:],yield_force[axial_count:],strength[axial_count:])]
    associations=associate(part,bodies)
    physical=configure_mesh_breaking(part,associations)
    measurements={}
    for name in config.get('reference_cases',('flex','torsion')):
        compliance,force=graph_response(columns,springs,names,configured_scenario(config,name))
        first_yield=float(1/np.max(abs(force)/yield_force)); ultimate=float(1/np.max(abs(force)/strength))
        measurements[name]={'compliance_m_n':compliance,'elastic_yield_proxy_n':first_yield,'elastic_ultimate_proxy_n':ultimate,
                            'reference':targets.get(name),'elastic_only':name not in damage_targets}
        if name in local_targets:
            local_targets[name].update(actual_compliance_m_n=compliance,
                numerical_ceiling_met=bool(compliance<=local_targets[name]['compliance_ceiling_m_n']*1.1),
                yield_target_n=targets[name]['first_yield_force_n'],actual_yield_proxy_n=first_yield,
                yield_floor_met=bool(first_yield>=targets[name]['first_yield_force_n']*(1-1e-8)),
                cad_reference_qualified=bool(abs(compliance/targets[name]['compliance_m_n']-1)<=.1 and
                    abs(first_yield/targets[name]['first_yield_force_n']-1)<=.15))
    paired_responses=[]
    for first,second,target_ratio in response_pairs:
        actual_ratio=measurements[first]['compliance_m_n']/measurements[second]['compliance_m_n']
        paired_responses.append(dict(first=first,second=second,cad_ratio=target_ratio,actual_ratio=actual_ratio,
                                     relative_error=abs(actual_ratio/target_ratio-1),accepted=bool(abs(actual_ratio/target_ratio-1)<=.1)))
    accepted=mass_report['accepted'] and complete and all(v['accepted'] for v in paired_responses) and all(abs(measurements[name]['compliance_m_n']/targets[name]['compliance_m_n']-1)<=.1 and
        abs(measurements[name]['elastic_yield_proxy_n']/targets[name]['first_yield_force_n']-1)<=.15 for name in ('flex','torsion')) and all(v['numerical_ceiling_met'] and v['yield_floor_met'] for v in local_targets.values())
    report={'mass':mass_report,'fit':fit_log,'reflection':reflection_report,'responses':measurements,'offline_accepted':bool(accepted),
            'highest_linear_mode_hz':float(modal_frequencies(columns,masses,springs)[-1]),
            'beam_material_volume_m3':float(volume.sum()),'visible_failure_beams':sum(physical),
            'numerical_braces':len(physical)-sum(physical),'associations':associations,
            'mesh_breaking_policy':'Existing shell edges shared by CAD mesh locator groups; internal support edges do not break visible meshes',
            'material':material,'actual_condition':'SolidWorks assignments; physical condition unverified' if assigned is not None else 'unknown','ultimate_thresholds':'Elastic capacity proxies, not validated ductile rupture loads'}
    report['local_mount_reference']=local_targets
    report['paired_mount_responses']=paired_responses
    report['local_mount_reference_qualified']=all(v['cad_reference_qualified'] for v in local_targets.values())
    if torsions:
        report['angular_constraints']=dict(count=len(torsions),damage_telemetry_qualified=False,
            limitation='Angular yield/rupture are fitted capacity proxies; native frame damage telemetry does not yet measure torsion-bar damage')
        report['tangent_step_budget']=damping_report
    return part,report


def render_calibration(output,state):
    native=state['config'].get('material_source')=='solidworks'
    title='SolidWorks material calibration' if native else '4130 calibration'
    description=('Materials captured from the selected CAD bodies. Library values describe the assigned material; physical condition and ductile rupture remain unvalidated. Joints are assumed fully joined.' if native else
                 'Material condition unknown. Annealed and normalized cases are representative assumptions, not guaranteed bounds. Joints are assumed fully joined.')
    lines=['<!doctype html><meta charset="utf-8"><title>'+title+'</title>',
           '<style>body{font:16px system-ui;max-width:1150px;margin:2rem auto;padding:1rem}td,th{padding:.5rem;border:1px solid #ccc}table{border-collapse:collapse}pre{white-space:pre-wrap}</style>',
           '<h1>'+title+'</h1>',f"<p><strong>{html.escape(state['status'])}</strong></p>",
           '<p>'+description+'</p>',
           '<p><a href="calibration-study.json">Full evidence</a> · <a href="geometry-audit.json">Geometry and reference audit</a></p>']
    for filename,label in (('measured-summary.json','Measured summary'),('measurements.csv','Measurement table'),
                           ('force-deflection.png','Force–deflection curves'),('mesh-review.json','Rendered mesh review')):
        if (output/filename).exists():
            lines.append(f'<p><a href="{filename}">{label}</a></p>')
    for problem in state.get('limitations',[]):
        lines.append('<p>'+html.escape(problem)+'</p>')
    if native:
        from collections import Counter
        assignments=next(iter(state.get('candidates',{}).values()),{}).get('material',{}).get('bodies',{})
        counts=Counter(m['name'] for m in assignments.values())
        lines.append('<p>'+html.escape('; '.join(f'{name}: {count} bodies' for name,count in counts.items()))+'</p>')
    lines.append('<table><tr><th>Case</th><th>Mass (kg)</th><th>COM error (mm)</th><th>Inertia error</th><th>Global CAD / numerical fit</th><th>Files</th></tr>')
    for name,report in state.get('candidates',{}).items():
        m=report['mass']
        lines.append(f"<tr><td>{name}</td><td>{m['actual_mass_kg']:.6f}</td><td>{m['center_error_m']*1000:.3f}</td><td>{m['inertia_relative_error']:.2%}</td><td>{report['offline_accepted']}</td><td><a href='{name}/report.json'>Diagnostics</a> · <a href='{name}/calibration.json'>Build artifact</a></td></tr>")
    lines.append('</table>')
    for case,report in state.get('candidates',{}).items():
        if not report.get('local_mount_reference'):continue
        lines.append('<h2>Local mounting response: '+html.escape(case)+'</h2><p>The numerical ceiling allows a stable timestep-limited representation. It does not replace the physical CAD target. A local mismatch prevents physical frame qualification.</p>')
        lines.append('<table><tr><th>Load</th><th>CAD compliance (m/N)</th><th>Numerical ceiling</th><th>Generated compliance</th><th>CAD yield (N)</th><th>Generated yield proxy (N)</th><th>Physical reference qualified</th></tr>')
        for name,v in report['local_mount_reference'].items():
            target_yield=f"{v['yield_target_n']:.4g}" if 'yield_target_n' in v else 'Not fitted'
            actual_yield=f"{v['actual_yield_proxy_n']:.4g}" if 'actual_yield_proxy_n' in v else 'Not fitted'
            lines.append(f"<tr><td>{html.escape(name)}</td><td>{v['cad_compliance_m_n']:.4g}</td><td>{v['compliance_ceiling_m_n']:.4g}</td><td>{v['actual_compliance_m_n']:.4g}</td><td>{target_yield}</td><td>{actual_yield}</td><td>{v['cad_reference_qualified']}</td></tr>")
        lines.append('</table>')
        if report.get('paired_mount_responses'):
            lines.append('<h3>Corresponding mounting responses</h3><p>Ratios follow the independent CAD reference; equality is not assumed.</p><table><tr><th>First load / second load</th><th>CAD ratio</th><th>Generated ratio</th><th>Error</th><th>Accepted</th></tr>')
            for pair in report['paired_mount_responses']:
                lines.append(f"<tr><td>{html.escape(pair['first']+' / '+pair['second'])}</td><td>{pair['cad_ratio']:.4g}</td><td>{pair['actual_ratio']:.4g}</td><td>{pair['relative_error']:.1%}</td><td>{pair['accepted']}</td></tr>")
            lines.append('</table>')
    lines.append('<h2>Live tests</h2><ul>')
    for record in state.get('runs',[]):
        p=Path(record['path']); page=p/('damage_report.html' if (p/'damage_report.html').exists() else 'report.html')
        if not page.exists():page=p/'result.json'
        lines.append(f"<li><a href='{page.as_uri()}'>{html.escape(record['candidate']+' / '+record['scenario'])}</a>: {html.escape(record['status'])} {html.escape(record.get('failure_reason') or '')}</li>")
    lines.append('</ul><h2>Acceptance</h2><pre>'+html.escape(json.dumps(state.get('acceptance',{}),indent=2))+'</pre>')
    (output/'index.html').write_text('\n'.join(lines),encoding='utf-8')


def run_calibration(project,reference,output,*,resume=False,live=True,diagnostic=False,case=None,save_report=True):
    from .reference import build_frame,solve_frame,analytical_checks
    from .runner import run_test, saved_recording_failure
    from .session import DriveSession
    from .progress import emit
    output=output.resolve(); output.mkdir(parents=True,exist_ok=True)
    config=json.loads(reference.read_text()); state_path=output/'calibration-study.json'
    reference_model=config.get('reference_model','tube_frame')
    if reference_model!='tube_frame':
        raise ValueError('Unsupported reference model: '+reference_model+'. This backend supports frame tubes; panels/solids require a geometry-based reference backend.')
    generation=inputs(project)
    assigned=None
    if generation.get('material_snapshot'):
        from .materials import load_snapshot,ASSIGNED_CASE
        assigned=load_snapshot(project.source/generation['material_snapshot'])
        if config.get('material_source')!='solidworks' or config.get('actual_condition')!='assigned_in_cad':
            raise ValueError('Captured SolidWorks materials require an assigned-material reference configuration')
    elif config.get('material_source')=='solidworks':raise ValueError('SolidWorks material snapshot missing')
    if (assigned is None and config.get('actual_condition')!='unknown') or config.get('joint_assumption')!='fully_joined':
        raise ValueError('Unsupported material condition or joint assumption')
    cases={ASSIGNED_CASE:{'bodies':assigned,'source':'solidworks'}} if assigned is not None else dict(MATERIAL_CASES)
    if case is not None:
        if case not in cases:raise ValueError('Material candidate is not available in this generation: '+case)
        cases={case:cases[case]}
    for key in (('density_kg_m3','young_pa') if assigned is None else ())+('frequency_limit_hz','damping_ratio','force_limit_n','ramp_seconds','slow_ramp_seconds'):
        if not np.isfinite(config[key]) or config[key]<=0: raise ValueError(f'Invalid {key}')
    if (assigned is None and not -1<config['poisson']<.5) or config['slow_ramp_seconds']!=2*config['ramp_seconds']:
        raise ValueError('Poisson ratio must be physical; slow ramp must double the normal ramp')
    identity={'source':{n:sha256(project.source/n) for n in generation['sources']},'reference':sha256(reference),
              'implementation':{p.relative_to(Path(__file__).parent).as_posix():sha256(p) for p in Path(__file__).parent.rglob('*') if p.suffix in ('.py','.lua')}}
    identity['cases']=list(cases)
    def save():
        write_json(state_path,state); render_calibration(output,state)
    if state_path.exists():
        if not resume: raise ValueError('Output already exists; use --resume or a new directory')
        state=json.loads(state_path.read_text())
        if state['identity']!=identity: raise ValueError('Source, reference or implementation changed; start a new calibration')
    else:
        state={'status':'auditing','identity':identity,'config':config,'reference_model':reference_model,'limitations':[], 'candidates':{},'runs':[]}
        save()
    if (project.source/'generation.json').exists():
        from .build import validate_part
        raw=load_part(project.source/generation['raw'],generation['part'])
        if not config.get('fixtures') or not config.get('cut_fixture'):
            raise ValueError('New generations require reviewed flex, torsion and cut fixtures')
        for case in ('flex','torsion'):
            validate_part(raw,configured_scenario(config,case))
    if state['status']=='auditing':
        # An interrupted audit is rebuilt deterministically, including incomplete
        # candidate directories. It must never enter live testing with half a fit.
        state['candidates']={};state['limitations']=[]
        shutil.copy2(reference,output/'reference.json')
        bodies=[]; audits=[]; sections={}; issues=[]
        cad_bodies=read_bodies(project.source/generation['mesh'])
        if not cad_bodies:raise ValueError('CAD source contains no bodies')
        if assigned is not None:
            load_snapshot(project.source/generation['material_snapshot'],[b.name for b in cad_bodies])
        geometry_path=project.source/'geometry.json'
        geometry=json.loads(geometry_path.read_text()) if geometry_path.exists() else {}
        body_names={m['Id']:m.get('Body',m['Id']) for m in geometry.get('Meshes',[])}
        native_records={m['Id']:m for m in geometry.get('Meshes',[])}
        for index,body in enumerate(cad_bodies):
            emit('CAD body audit',completed=index,total=len(cad_bodies),detail=body_names.get(body.name,body.name))
            body,audit=audit_body(body); override=config.get('body_overrides',{}).get(body.name,{})
            if 'mass_properties' in override:
                audit.update(override['mass_properties']); audit.update(valid=True,override=True)
            bodies.append(body); audits.append(audit)
            record=native_records.get(body.name,{})
            if assigned is not None and record.get('MassKg') is not None:
                native_mass=float(record['MassKg']);mesh_mass=audit['volume_m3']*assigned[body.name]['density_kg_m3']
                if not np.isfinite(native_mass) or native_mass<=0 or abs(native_mass/mesh_mass-1)>.05:
                    raise ValueError(body_names[body.name]+': SolidWorks mass differs from audited mesh/material mass by more than 5%')
                audit.update(native_mass_kg=native_mass,mass_source='SolidWorks MassProperty2; tessellated COM and normalized inertia',
                             tessellated_mass_kg=mesh_mass)
            try: sections[body.name]=override.get('section') or extract_member(body)
            except ValueError as exc: issues.append(f'{body_names.get(body.name,body.name)} ({body.name}): {exc}')
        unresolved=[a['name'] for a in audits if not a['valid']]
        if not unresolved:
            original=sum(a.get('original_signed_volume_m3',a['volume_m3']) for a in audits)
            repair_error=abs(sum(a['volume_m3'] for a in audits)/original-1)
            if repair_error>.001:
                unresolved=['aggregate repair volume difference exceeds 0.1%']
        if unresolved:
            state['limitations'].append('Unresolved CAD surface audit: '+', '.join(unresolved)+'. Candidate mass is provisional; no physical-calibration acceptance.')
        state['limitations'].extend(issues)
        measured=[a if a['valid'] else {'name':a['name'],**a['provisional_properties']} for a in audits]
        part=load_part(project.source/generation['raw'],generation['part']); nodes=node_table(part)
        positions={n:np.array(v['position']) for n,v in nodes.items()}
        targets={}; reference_error=None
        analytical=analytical_checks()
        if not analytical['accepted']: raise ValueError('Independent reference failed analytical checks')
        if not issues:
            emit('Independent CAD reference'); print('Constructing independent CAD frame reference...',flush=True)
            try:
                frame=build_frame(sections,config.get('young_pa',205e9),config.get('poisson',.29),materials=assigned)
                for scenario in config.get('reference_cases',('flex','torsion')):
                    strengths={n:m['yield_pa'] for n,m in assigned.items()} if assigned is not None else MATERIAL_CASES['4130-annealed']['yield_pa']
                    targets[scenario]=solve_frame(frame,positions,configured_scenario(config,scenario),strengths)
            except ValueError as exc: reference_error=str(exc); targets={}
        if reference_error: state['limitations'].append(reference_error)
        write_json(output/'geometry-audit.json',{'bodies':audits,'sections':sections,'section_issues':issues,'reference_error':reference_error,('reference_targets_assigned' if assigned is not None else 'reference_targets_annealed'):targets,
                   'analytical_checks':analytical,'cad_geometry':str(project.source/generation['mesh']),
                   'repair_volume_relative_error':repair_error if not unresolved else None,
                   'notes':'Dangling export facets are removed only with closed-result and material-volume checks (0.5% per body, 0.1% whole frame). Original DAE is not modified.'})
        elastic_template=None;elastic_seed=None
        if config.get('elastic_seed_file'):
            seed_name=config['elastic_seed_file']
            if seed_name not in identity['source'] or Path(seed_name).name!=seed_name:
                raise ValueError('Elastic seed must be a sealed generation source file')
            elastic_seed=load_part(project.source/seed_name,generation['part'])
        for name,material in cases.items():
            emit('Material fit',detail=name); print('Generating '+name+'...',flush=True)
            case_targets=copy.deepcopy(targets)
            if assigned is None:
                for t in case_targets.values(): t['first_yield_force_n']*=material['yield_pa']/MATERIAL_CASES['4130-annealed']['yield_pa']
            generated,report=make_candidate(part,bodies,measured,case_targets,material,config,elastic_template,symmetry_sections=sections,elastic_seed=elastic_seed)
            if generation.get('render_binding'):
                from .skin import apply_skin
                if generation.get('runtime_assets',{}).get('cadSkin.lua')!='lua/controller/cadSkin.lua':
                    raise ValueError('Local render binding requires the sealed cadSkin controller')
                binding=json.loads((project.source/generation['render_binding']).read_text())
                if binding.get('version')!=1 or binding.get('physical_file')!=generation['mesh']:
                    raise ValueError('Render binding does not identify this physical CAD input')
                for file_key,hash_key in (('physical_file','physical_sha256'),('render_file','render_sha256')):
                    if binding.get(file_key) not in identity['source'] or binding.get(hash_key)!=identity['source'][binding[file_key]]:
                        raise ValueError('Render binding source or output hash differs')
                if {r['source_body'] for r in binding['regions']}!={b.name for b in bodies}:
                    raise ValueError('Render binding does not cover all selected CAD bodies')
                report['associations']=apply_skin(generated,binding)
                visible=configure_mesh_breaking(generated,report['associations'],native_mesh=False)
                report.update(visible_failure_beams=sum(visible),numerical_braces=len(visible)-sum(visible),
                              mesh_breaking_policy='Remove a local render patch when its four-node locator graph disconnects; coarse surface erosion, not resolved material fracture. Native polygon breaking is disabled for these patches.',
                              render_binding_sha256=identity['source'][generation['render_binding']])
            if elastic_template is None: elastic_template=(generated,report)
            if unresolved or issues: report['offline_accepted']=False
            if report.get('local_mount_reference_qualified') is False:
                state['limitations'].append(name+': local mounting stiffness uses a timestep-limited numerical representation; physical CAD local response remains unqualified')
            if report.get('angular_constraints'):
                state['limitations'].append(name+': '+report['angular_constraints']['limitation'])
            if graph_identity(generated)!=graph_identity(part): raise AssertionError('Calibration changed graph topology')
            directory=output/name; directory.mkdir(exist_ok=True)
            write_json(directory/generation['vehicle'],{generation['part']:generated}); write_json(directory/'report.json',report)
            artifact={'version':1,'source_hashes':identity['source'],'vehicle_file':generation['vehicle'],'vehicle_sha256':sha256(directory/generation['vehicle']),
                      'reference_config':config,'material':material,'material_source':('SolidWorks material snapshot '+identity['source'][generation['material_snapshot']] if assigned is not None else MATERIAL_SOURCE),'condition_case':name,
                      'offline_accepted':report['offline_accepted'],'geometry_valid':not unresolved,
                      'local_mount_reference':report.get('local_mount_reference',{}),
                      'local_mount_reference_qualified':report.get('local_mount_reference_qualified',True),
                      'angular_constraints':report.get('angular_constraints'),
                      'qualification':'diagnostic candidate until all offline and live checks pass'}
            write_json(directory/'calibration.json',artifact)
            vehicle=directory/'diagnostic-mod'/'vehicles'/'mochi';vehicle.mkdir(parents=True,exist_ok=True)
            for asset in generation['assets']: shutil.copy2(project.source/asset,vehicle/asset)
            from .generation import copy_runtime_assets
            copy_runtime_assets(project,vehicle)
            shutil.copy2(directory/generation['vehicle'],vehicle/generation['vehicle'])
            write_json(directory/'diagnostic-mod'/'qualification.json',artifact)
            shutil.make_archive(str(directory/'diagnostic-mod'),'zip',directory/'diagnostic-mod')
            state['candidates'][name]=report
            save()
        state['status']='offline_complete'; save()
    if not live:
        print('Calibration audit: '+str(output/'index.html'),flush=True); return state
    if not diagnostic and not all(r['offline_accepted'] for r in state['candidates'].values()):
        state['status']='offline_rejected';save();return state
    verification_identity={'mode':'full','version':1,'game':str(project.executable.resolve()),
                           'game_sha256':sha256(project.executable)}
    if state.get('verification_identity',verification_identity)!=verification_identity:
        raise ValueError('Full verification environment changed; start a new generation')
    state['verification_identity']=verification_identity
    state['status']='testing'; save()
    scheduled=5+sum(7+(10 if r['offline_accepted'] else 0) for r in state['candidates'].values()); finished=0
    active=None
    def run(key,scenario,parameters):
        nonlocal finished
        from .verification import batch_progress
        batch_progress(state['runs'],finished,scheduled,'Full: '+key)
        existing=[r for r in state['runs'] if r.get('key')==key]
        if existing:
            record=existing[-1]
            if record['status']!='cancelled' and not saved_recording_failure(Path(record['path'])):
                finished+=1
                return record
        if {n:sha256(project.source/n) for n in generation['sources']}!=identity['source']: raise ValueError('Source changed during calibration')
        result=run_test(project,scenario,parameters,session=active,save_report=save_report)
        finished+=1
        record=asdict(result)|{'key':key}; state['runs'].append(record);save()
        if result.status=='cancelled': raise KeyboardInterrupt
        return record
    try:
        with DriveSession(project) as active:
            instrument=[]
            for name in ('spring','spring-yield','spring-break'):
                instrument.append(run(name,configured_scenario(config,name),ParameterSet(name='instrument-'+name)))
            spring=instrument[0]['metrics']; breaking=instrument[2]['metrics'].get('first_natural_beam_break')
            yield_load=instrument[1]['metrics'].get('first_yield_external_force_n')
            instrument_ok=(all(r['status']=='completed' for r in instrument) and spring.get('spring_relative_error',1)<.01 and
                           yield_load is not None and abs(yield_load/8-1)<.05 and breaking is not None and
                           abs(breaking['external_force_n']/12-1)<.05)
            state['instrument_accepted']=instrument_ok;save()
            if not instrument_ok:
                state['status']='instrument_failed';save();return state
            for name,report in state['candidates'].items():
                p=ParameterSet(name=name,calibration=str(output/name/'calibration.json'))
                screening=[]
                for scenario in ('idle','flex','torsion'):
                    s=configured_scenario(config,scenario);s.capture=True
                    screening.append(run(name+'-'+scenario,s,p))
                if any(r['status']!='completed' for r in screening):
                    scheduled-=4+(10 if report['offline_accepted'] else 0)
                    state['limitations'].append(name+': invalid/unstable screening; destructive loading skipped');save();continue
                for base in ('flex','torsion'):
                    # An elastic ultimate proxy is not a post-yield rupture load:
                    # redistribution can defer breaking well beyond 1.3x it.
                    # Explore the explicitly configured actuator range and keep
                    # absent/zero-load thresholds unqualified.
                    target=config['force_limit_n']
                    for ramp in (config['ramp_seconds'],config['slow_ramp_seconds']):
                        s=configured_scenario(config,base);s.name=f'{base}-damage-{ramp:g}';s.force_n=target;s.ramp_s=ramp;s.hold_s=2;s.duration=2+ramp+2+6;s.capture=True;s.expected_damage=True
                        run(name+'-'+s.name,s,p)
                if report['offline_accepted']:
                    for repeat in (2,3):
                        for base in ('idle','flex','torsion'):
                            run(f'{name}-{base}-{repeat}',configured_scenario(config,base),p)
                        for base in ('flex','torsion'):
                            s=configured_scenario(config,base);s.name=base+'-damage-confirm';s.ramp_s=config['slow_ramp_seconds'];s.force_n=config['force_limit_n']
                            s.hold_s=2;s.duration=2+s.ramp_s+2+6;s.expected_damage=True
                            run(f'{name}-{base}-damage-{repeat}',s,p)
            # Keep the pieces far enough apart to inspect, including when one
            # cut releases a much lighter piece than the other.
            from .damage import cut_separating_force
            chosen=next(iter(state['candidates']));part=load_part(output/chosen/generation['vehicle'],generation['part']);nodes=node_table(part)
            ys=[v['position'][1] for v in nodes.values()]
            for fraction in (.35,.65):
                plane=min(ys)+(max(ys)-min(ys))*fraction
                cut=[[e['a'],e['b']] for e in beam_table(part) if (nodes[e['a']]['position'][1]<plane)!=(nodes[e['b']]['position'][1]<plane)]
                cut_fixture=config.get('cut_fixture', {'load_nodes':['sp02l','sp02r'], 'load_vectors':{'sp02l':[0,-.5,0],'sp02r':[0,-.5,0]}})
                separating_force=cut_separating_force(nodes,beam_table(part),cut,cut_fixture['load_vectors'],max(ys)-min(ys))
                s=TestScenario('mesh-cut',10,0,[],cut_fixture['load_nodes'],separating_force,settle_s=3,ramp_s=2,hold_s=2,
                               load_vectors=cut_fixture['load_vectors'],expected_damage=True,cut_edges=cut,cut_at_s=3,capture=True)
                run(f'mesh-cut-{fraction}',s,ParameterSet(name=chosen,calibration=str(output/chosen/'calibration.json')))
            from .acceptance import evaluate_acceptance,export_qualified
            state['acceptance']=evaluate_acceptance(state,output)
            export_qualified(output,state)
            state['status']='completed' if all(a['accepted'] for a in state['acceptance'].values()) else 'completed_with_limitations';save()
    except KeyboardInterrupt:
        state['status']='cancelled';save()
    print('Calibration report: '+str(output/'index.html'),flush=True)
    return state
