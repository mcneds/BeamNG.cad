"""Rigid CAD shaft sections, floating centres and explicit sliding members."""
import math
import numpy as np
import components as c
from driveline import validate


def owners(spec):
    return {s['component'] for s in spec['shafts']} | {d['component'] for d in spec['devices']}


def ideal_declarations(spec, hub_owners):
    endpoints = {e['id']: e for e in spec['endpoints']}
    ports = {p['endpoint']: device for device in spec['devices'] for p in device['ports']}
    result = {}
    for shaft in spec['shafts']:
        if shaft.get('representation') != 'ideal':
            continue
        positions, parents = [], []
        for end in (shaft['a'], shaft['b']):
            site = end
            if site not in ports:
                link = next(link for link in spec['connections'] if site in (link['a'], link['b']))
                site = link['b'] if link['a'] == site else link['a']
            device = ports[site]
            parents.append(hub_owners[device['wheel']] if device['type']=='wheel' else device['component'])
            positions.append(endpoints[end]['position'])
        result[shaft['component']] = dict(ideal_id=shaft['id'], parents=parents, inner=positions[0],
            outer=positions[1], plunge_m=shaft.get('half_travel_m',0.))
    return result


def prepare(spec, graph):
    """Declare aliasing and rail sites before fitting any moving CAD mass."""
    data = validate(spec); endpoints = data['endpoints']; alias = {e: e for e in endpoints}
    shaft_ends = {e for s in spec['shafts'] for e in (s['a'], s['b'])}
    def root(e):
        while alias[e] != e: e = alias[e]
        return e
    for link in spec['connections']:
        if link['kind'] == 'spherical' and {link['a'], link['b']} <= shaft_ends:
            alias[root(link['b'])] = root(link['a'])
    node = {e: 'driveline_'+root(e) for e in endpoints}
    rails = []; required = {}
    for s in spec['shafts']:
        if s.get('representation') == 'ideal': continue
        key = s.get('member') or s['component']
        required[key] = {node[e]: np.array(endpoints[e]['position']) for e in (s['a'], s['b'])}
    # Sliding interfaces connect real, separately owned CAD members. Three
    # parallel rails preserve orientation and leave exactly axial translation.
    for link in spec['connections']:
        if link['kind'] != 'slider': continue
        ea, eb = (endpoints[link[k]] for k in ('a', 'b'))
        pa, pb = ea.get('member') or ea['component'], eb.get('member') or eb['component']
        if pa not in required or pb not in required or pa == pb:
            raise ValueError(link['id']+': plunge needs two independently classified shaft bodies/members')
        p = np.array(ea['position'],float); u = np.array(ea['axis'],float); u /= np.linalg.norm(u)
        side = np.eye(3)[np.argmin(abs(u))]; side -= u*(side@u); side /= np.linalg.norm(side)
        cross = np.cross(u, side)
        # Keep a useful transverse lever on long/slender sliding members. A
        # fixed tiny guide triangle magnifies forces and permits the supporting
        # rigid cage to bend under gravity despite a stable rest-state tangent.
        # This is a numerical locator gauge, not a shaft diameter or bearing.
        spans=[np.linalg.norm(np.array(endpoints[s['a']]['position'])-endpoints[s['b']]['position']) for s in spec['shafts'] if (s.get('member') or s['component']) in (pa,pb)]
        gauge=min(.05,max(.01,min(spans)*.25))
        # Centre the guide triangle on the physical shaft axis. Positive-side
        # guides plus the reported nodal mass floor otherwise create an
        # artificial off-axis COM and a gravity-driven free-roll pendulum.
        offsets=[gauge*(math.cos(i*2*math.pi/3)*side+math.sin(i*2*math.pi/3)*cross) for i in range(3)]
        for i, offset in enumerate(offsets):
            prefix = 'driveline_'+link['id']+'_rail_'+str(i)
            a, b, slider = prefix+'_a', prefix+'_b', prefix+'_slider'
            required[pa][a] = p+offset-u*link['travel']; required[pa][b] = p+offset+u*link['travel']
            required[pb][slider] = p+offset
            rails.append(dict(id=prefix, a=a, b=b, slider=slider, connection=link['id']))
    graph.driveline_prepared = dict(required=required, node=node, rails=rails)
    return graph.driveline_prepared


def generate(spec, graph, project, meshes, bindings, supports):
    from translating_rack import member_component
    data = validate(spec, project); endpoints = data['endpoints']; prep = prepare(spec, graph)
    node = prep['node']; components = {v['Id']: v for v in project['Components']}; partitioned = {}
    section_contracts = []
    for s in sorted(spec['shafts'], key=lambda v: v['id']):
        if s.get('representation') == 'ideal': continue
        key = s.get('member') or s['component']; logical = components[s['component']]
        comp = member_component(project, logical['Id'], s['member']) if s.get('member') else logical
        if key in graph.groups: raise ValueError(s['id']+': shaft body already has a physical representation')
        points = prep['required'][key]; shared = set(points) & set(graph.nodes)
        names, mesh = graph.rigid_component(comp, points, shared=shared)
        for n in names:
            if graph.owners[n] == key: graph.owners[n] = logical['Id']
        if s.get('member'):
            weights = graph.mass_allocations.pop(key)
            graph.rigid_member_allocations[key] = dict(owner=logical['Id'], weights=weights)
            partitioned.setdefault(logical['Id'], []).append((key, names, mesh, weights))
        else:
            meshes[key] = mesh; bindings[key] = [key+'_structure']
        section_contracts.append(dict(id=s['id'], component=s['component'], member=s.get('member'),
            endpoints=[node[s['a']], node[s['b']]], nodes=names,rest_length_m=float(np.linalg.norm(np.array(endpoints[s['a']]['position'])-endpoints[s['b']]['position']))))
    for owner, sections in partitioned.items():
        if components[owner].get('AppearanceSelections') or components[owner].get('AppearanceDirectory'):
            raise ValueError(owner+': independently moving shaft members need their own CAD meshes; use separate section groups for appearance replacement')
        expected = c.read_geometry(components[owner])[1][0]
        total = sum(sum(w.values()) for _, _, _, w in sections)
        if abs(expected-total) > max(1e-6, expected*1e-6): raise ValueError(owner+': classify all shaft CAD mass exactly once into moving members')
        graph.mass_allocations[owner] = {}; graph.groups[owner] = []
        graph.moving_render = getattr(graph, 'moving_render', {})
        graph.moving_render[owner] = []
        meshes[owner] = []; bindings[owner] = [owner+'_structure']
        for key, names, mesh, weights in sections:
            for n, mass in weights.items(): graph.mass_allocations[owner][n] = graph.mass_allocations[owner].get(n, 0)+mass
            graph.groups[owner].extend(n for n in names if n not in graph.groups[owner])
            graph.moving_render[owner].append(dict(meshes=mesh, group=key+'_structure'))
            meshes[owner].extend(mesh)
        graph.reports[owner] = dict(target_mass_kg=expected, actual_mass_kg=total, representation='independent rigid shaft members')
    joints = []
    shaft_ends = {e for s in spec['shafts'] for e in (s['a'], s['b'])}
    ideal_ends={e for s in spec['shafts'] if s.get('representation')=='ideal' for e in (s['a'],s['b'])}
    for link in spec['connections']:
        if link['a'] in ideal_ends or link['b'] in ideal_ends:continue
        kind = link['kind']; a, b = link['a'], link['b']
        if kind in ('internal', 'direct', 'slider'): continue
        if a in shaft_ends and b in shaft_ends:
            if kind == 'bearing': raise ValueError(link['id']+': bearing support must name its separate mounted carrier')
            # Shared centre: positional spherical articulation, independent
            # rigid frames and mass allocations. Spin is intentionally ideal.
            joints.append(dict(id=link['id'], kind='floating', node=node[a], endpoints=[a,b]))
            graph.joints.append(dict(id='driveline_'+link['id'],kind='shared_driveline_pivot',parent=endpoints[a]['component'],child=endpoints[b]['component'],nodes=[node[a]]))
            continue
        if (a in shaft_ends) == (b in shaft_ends): raise ValueError(link['id']+': physical joint needs a shaft endpoint')
        shaft, parent = (a,b) if a in shaft_ends else (b,a)
        parent_owner = endpoints[parent].get('member') or endpoints[parent]['component']
        wheel = next((d for d in spec['devices'] if d['type']=='wheel' and any(p['endpoint']==parent for p in d['ports'])), None)
        if wheel:
            parent_owner = graph.driveline_hub_owners[wheel['wheel']]
        if parent_owner not in graph.groups: raise ValueError(link['id']+': endpoint housing or carrier is not physically mounted')
        triplet = supports(graph, parent_owner, np.array(endpoints[parent]['position']))
        graph.spherical('driveline_'+link['id'], triplet, node[shaft], parent_owner=parent_owner)
        joints.append(dict(id=link['id'], kind=kind, node=node[shaft], parent=parent_owner, support_nodes=triplet))
    for rail in prep['rails']:
        graph.part.setdefault('rails', {})[rail['id']] = {'links:':[rail['a'],rail['b']], 'looped':False, 'capped':True}
        graph.part.setdefault('slidenodes', [['id:','railName']]).append([rail['slider'],rail['id'],dict(attached=True,fixToRail=True,tolerance=0,spring=2e6,strength=1e30,capStrength=1e30)])
    graph.driveline_physics = dict(sections=section_contracts, joints=joints, rails=prep['rails'],
        qualification='diagnostic', limitations=['Positional articulation and explicit axial travel; no spin animation, Cardan phasing or calibrated torsional fracture.'])
    return graph.driveline_physics


def reaction(graph, owner, axis):
    """Torque basis along an explicitly authored axis, on the actual owner."""
    import itertools
    from vehicle_templates import reaction_inertia
    u = np.array(axis, float); u /= np.linalg.norm(u)
    names = sorted(graph.groups[owner]); xyz = np.array([graph.point(n) for n in names]); candidates = []
    for i,j in itertools.combinations(range(len(names)),2):
        delta=xyz[j]-xyz[i]; length=np.linalg.norm(delta)
        if length < 1e-6 or abs(delta@u)/length < .995: continue
        if delta@u < 0: i,j=j,i; delta=-delta
        for k in range(len(names)):
            if np.linalg.norm(np.cross(delta,xyz[k]-xyz[i]))/length < .005: continue
            value=dict(torqueCoupling=names[i], torqueArm=names[k], torqueArm2=names[j])
            candidates.append((reaction_inertia(graph,value),value))
    if not candidates: raise ValueError(owner+': no conditioned reaction basis along the declared port axis')
    return max(candidates,key=lambda v:v[0])[1]


def housing_points(spec, owner, mounts=()):
    """Required axis sites for moment fitting, never additional frame mounts."""
    points={}
    needed=None
    if spec.get('version')==2:
        needed=set()
        data=validate(spec)
        for d in spec['devices']:
            if d['type']=='engine':needed.update(p['endpoint'] for p in d['ports'])
            if d['type']=='wheel':
                route=data['incoming'][d['id']]
                needed.update(p['endpoint'] for p in data['devices'][route['source']]['ports'] if p['direction']=='output' and p['index']==route['port'])
    for d in spec['devices']:
        if d['component']!=owner or d['type']=='wheel':continue
        for port in d['ports']:
            if needed is not None and port['endpoint'] not in needed:continue
            e=next(e for e in spec['endpoints'] if e['id']==port['endpoint'])
            p=np.array(e['position'],float);u=np.array(e['axis'],float);u/=np.linalg.norm(u)
            if needed is not None:
                basis=list(map(np.asarray,mounts))+list(points.values())
                if any(np.linalg.norm(b-a)>1e-6 and abs((b-a)@u)>=.995*np.linalg.norm(b-a)
                       and any(np.linalg.norm(np.cross(b-a,c-a))>.005*np.linalg.norm(b-a) for c in basis)
                       for i,a in enumerate(basis) for b in basis[i+1:]):continue
            for i,offset in enumerate((-.03,.03)):
                q=p+u*offset
                if not any(np.linalg.norm(q-v)<1e-7 for v in list(points.values())+(list(mounts) if needed is not None else [])):points['driveline_axis_'+e['id']+'_'+str(i)]=q
    return points


def configure(part, contract, wheel_inertias, reaction_inertias, parameters):
    """Graph-derived conservative recoil budget and exact native normalization.

    Independent terminal mobilities provide a conservative upper bound, so a
    changed branch cannot silently inherit the current vehicle's inertia fit.
    Native wheel-only cumulative inertia is calculated separately.
    """
    rows={r[1]:r for r in part['powertrain'][1:]}; children={k:[] for k in rows}
    for name,row in rows.items():
        if row[2] in children: children[row[2]].append(name)
    for names in children.values(): names.sort()
    cumulative={}; mobility={}; max_ratio={}
    def visit(name):
        row=rows[name]; opts=part.get(name,row[4]); kind=row[0]; ratio=float(opts.get('gearRatio',1))
        for child in children[name]:visit(child)
        wheel=opts.get('connectedWheel')
        if wheel:
            native=wheel_inertias[wheel]; inverse=1/native+1/reaction_inertias[wheel]; maximum=1.
        else:
            native=sum(cumulative[c] for c in children[name]); inverse=sum(mobility[c] for c in children[name]); maximum=max((max_ratio[c] for c in children[name]),default=1.)
        if kind=='splitShaft':
            if len(children[name])!=2:raise ValueError(name+': locked splitter needs both outputs')
            primary=int(opts.get('primaryOutputID',1))-1;native=cumulative[children[name][primary]]
            contract['devices'][name]['inertiaChildren']=children[name]
        if kind=='cvtGearbox':ratio=float(opts['maxGearRatio'])
        cumulative[name]=native/ratio**2;mobility[name]=inverse*ratio**2;max_ratio[name]=maximum*abs(ratio)
    visit('mainEngine')
    budgets={}
    def tuning(prefix):
        f=float(parameters.get(prefix+'_frequency_hz',120.));z=float(parameters.get(prefix+'_damping_ratio',.3))
        if not 0<f<=150 or not 0<z<=.5:raise ValueError(prefix+': numerical coupling budget outside supported range')
        return 2*math.pi*f,z
    engine_inertia=float(part['mainEngine']['inertia'])
    peak=max(r[1] for r in part['mainEngine']['torque'][1:])
    for name,row in rows.items():
        kind=row[0];opts=part.get(name,row[4])
        if kind not in ('centrifugalClutch','splitShaft','cvtGearbox'):continue
        if not children[name]:raise ValueError(name+': coupling has no output')
        if kind=='cvtGearbox':
            omega,z=tuning('park'); inverse=sum(mobility[c] for c in children[name]);effective=1/inverse
            spring=effective*omega**2;damp=2*z*effective*omega;native=sum(cumulative[c] for c in children[name])
            opts.update(parkLockSpring=spring,parkLockDampRatio=damp/math.sqrt(spring*native))
            expected=dict(parkLockSpring=spring,parkLockDamp=damp)
        else:
            omega,z=tuning('clutch' if kind=='centrifugalClutch' else 'carrier')
            inverse=mobility[name]+(1/engine_inertia if kind=='centrifugalClutch' else 0);effective=1/inverse
            tangent=effective*omega**2;damp=2*z*effective*omega
            if kind=='centrifugalClutch':
                if row[2]!='mainEngine':raise ValueError(name+': native centrifugal clutch must connect directly to the combustion engine')
                spring=tangent/2;native=min(cumulative[children[name][0]],engine_inertia*.5)
            else:
                capacity=float(opts.get('lockTorque',peak*max_ratio['mainEngine']*1.25));opts['lockTorque']=capacity
                spring=tangent*tangent/(4*capacity);native=cumulative[children[name][1 if int(opts.get('primaryOutputID',1))==1 else 0]]
            opts.update(lockSpring=spring,lockDampRatio=damp/math.sqrt(spring*native));expected=dict(lockSpring=spring,lockDamp=damp)
        budgets[name]=dict(effective_inertia_kg_m2=effective,native_inertia_kg_m2=native,
            expected=expected,step_seconds=.0005,step_eigenvalue=(.0005**2*effective*omega**2+2*.0005*damp)/effective)
    contract['coupling_budgets']=budgets
