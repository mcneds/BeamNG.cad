"""CAD endpoint driveline contract and deterministic native torque-tree compiler.

CAD ownership is independent of device identity. Connections join explicit
endpoints; a shaft is a physical edge, not a front/rear role. No point, axis,
ratio, support or connection is inferred from display geometry.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re
import numpy as np

TYPES = {'engine': ('combustionEngine', 0, 1), 'clutch': ('centrifugalClutch', 1, 1),
         'cvt': ('cvtGearbox', 1, 1), 'reduction': ('shaft', 1, 1),
         'shaft': ('shaft', 1, 1), 'differential': ('differential', 1, 2),
         'splitter': ('splitShaft', 1, 2), 'wheel': ('shaft', 1, 0)}
CORNERS = ('FL', 'FR', 'RL', 'RR')


def drive_role(role):
    return role in ('engine','cvt','rear_diff','front_diff','rear_final_drive','front_propshaft','cvt_output_shaft','shaft_carrier') or (role or '').endswith('_halfshaft')


def settings(value):
    return dict((v['Key'], v['Value']) for v in value) if isinstance(value, list) else dict(value or {})


def indexed(values, label):
    result = {}
    for v in values:
        key = v.get('id')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', key):
            raise ValueError(label + ': IDs must start with a letter and contain letters, digits or underscores')
        if key in result: raise ValueError(label + ': duplicate ID ' + key)
        result[key] = v
    return result


def vector(value, label, unit=False):
    a = np.asarray(value, float)
    if a.shape != (3,) or not np.isfinite(a).all(): raise ValueError(label + ': expected three finite coordinates')
    if unit:
        if np.linalg.norm(a) < 1e-8: raise ValueError(label + ': axis has no direction')
        a = a / np.linalg.norm(a)
    return a.tolist()


def resolve(project):
    """Resolve private persistent reference bindings; output contains no CAD paths."""
    spec = copy.deepcopy(project.get('Driveline'))
    if not spec: return None
    if spec.get('version') not in (1, 2): raise ValueError('Unsupported driveline graph version')
    anchors = {a['Id']: a for a in project.get('Anchors', [])}
    joints = {j['Id']: j for j in project.get('JointWorkspace', {}).get('Joints', [])}
    components = {c['Id']: c for c in project['Components']}
    members = {m['Id']: m for m in project.get('JointWorkspace', {}).get('Members', [])}
    for device in spec.get('devices',[]):device['parameters']=settings(device.get('parameters'))
    for e in spec.get('endpoints', []):
        owner = components.get(e.get('component'))
        if not owner: raise ValueError(e['id'] + ': endpoint owner is missing')
        if e.get('member') and members.get(e['member'], {}).get('ComponentId') != e['component']:
            raise ValueError(e['id'] + ': moving member belongs to another component')
        def anchor(key):
            a = anchors.get(e.get(key))
            if not a or a.get('Status') != 'resolved' or a['ComponentId'] != owner['Id']:
                raise ValueError(e['id'] + ': capture or repair ' + key + ' on ' + owner['Name'])
            body_ids=['body_'+hashlib.sha256((a.get('ComponentReference','')+'|'+b).encode()).hexdigest()[:24] for b in a.get('BodyReferences',[]) if b]
            allowed=members[e['member']].get('BodyIds',[]) if e.get('member') else owner.get('BodyIds',[])
            if any(b not in allowed for b in body_ids):raise ValueError(e['id'] + ': reference lies outside its assigned CAD body/member')
            return np.array(vector(a.get('Position'), e['id'] + '.' + key))
        if not any(e.get(k) for k in ('anchor','axis_anchor','joint')) and e.get('position') is not None:
            # Explicit reviewed-definition coordinates remain a supported input
            # contract. Native bindings always take precedence and must repair
            # rather than silently falling back to these snapshots.
            e['position']=vector(e['position'],e['id'])
            if e.get('axis') is not None or spec['version']==1:e['axis']=vector(e.get('axis'),e['id'],True)
        elif e.get('joint'):
            j = joints.get(e['joint'])
            if not j or j.get('Status') != 'approved' or j.get('Issue') or owner['Id'] not in (j['Parent'], j['Child']):
                raise ValueError(e['id'] + ': review the endpoint joint')
            e['position'] = vector(j.get('Center'), e['id'])
            if e.get('member') and e['member'] not in (j.get('ParentMember'),j.get('ChildMember')):raise ValueError(e['id']+': joint does not belong to the declared moving member')
            axis=anchor('axis_anchor')-np.array(e['position']) if e.get('axis_anchor') else j.get('Axis')
            e.pop('axis',None)
            if axis is not None or spec['version']==1:e['axis']=vector(axis,e['id'],True)
        elif spec['version']==2 and not any(e.get(k) for k in ('anchor','axis_anchor','joint')) and e.get('position') is None and e.get('axis') is None:
            continue
        else:
            p=anchor('anchor')
            e['position']=p.tolist()
            e.pop('axis',None)
            if e.get('axis_anchor') or spec['version']==1:e['axis']=vector(anchor('axis_anchor')-p,e['id'],True)
        for key in ('anchor', 'axis_anchor', 'joint'): e.pop(key, None)
    validate(spec, project)
    return spec


def validate(spec, project=None):
    if spec.get('version') not in (1, 2): raise ValueError('Unsupported driveline graph version')
    endpoints = indexed(spec.get('endpoints', []), 'Endpoints')
    devices = indexed(spec.get('devices', []), 'Devices')
    shafts = indexed(spec.get('shafts', []), 'Shafts')
    links = indexed(spec.get('connections', []), 'Connections')
    components = {c['Id']: c for c in project['Components']} if project else None
    members = {m['Id']: m for m in project.get('JointWorkspace', {}).get('Members', [])} if project else {}
    for e in endpoints.values():
        if spec['version']==1 or e.get('position') is not None or e.get('axis') is not None:
            vector(e.get('position'), e['id'])
            if spec['version']==1 or e.get('axis') is not None:vector(e.get('axis'), e['id'], True)
        if not e.get('component') or components is not None and e['component'] not in components:
            raise ValueError(e['id'] + ': missing physical owner')
    port_owners = {}; ports = {}
    for d in devices.values():
        kind = d.get('type')
        if kind not in TYPES: raise ValueError(d['id'] + ': unsupported device type ' + str(kind))
        if components is not None and d.get('component') not in components: raise ValueError(d['id'] + ': missing housing owner')
        _, inputs, outputs = TYPES[kind]
        declared = indexed(d.get('ports', []), d['id'] + ' ports')
        for direction, count in (('input', inputs), ('output', outputs)):
            actual = [p for p in declared.values() if p.get('direction') == direction]
            indices=[p.get('index') for p in actual]
            if any(type(i) is not int for i in indices) or sorted(indices) != list(range(1, count+1)):
                raise ValueError(d['id'] + ': declare ' + str(count) + ' indexed ' + direction + ' ports')
        if len(declared) != inputs+outputs: raise ValueError(d['id'] + ': unexpected ports')
        for p in declared.values():
            e = endpoints.get(p.get('endpoint'))
            if not e or e['component'] != d['component']: raise ValueError(d['id'] + ': port must reference an endpoint on its housing')
            if e['id'] in port_owners: raise ValueError(e['id'] + ': endpoint used by multiple ports')
            port_owners[e['id']] = d['id']; ports[e['id']] = p
        params = settings(d.get('parameters'))
        allowed={'engine':{'inertia','friction','dynamicFriction'},'clutch':{'engageRPMStart','engageRPMEnd','lockTorque'},
                 'cvt':{'minGearRatio','maxGearRatio','dynamicFriction','parkLockTorque'},'splitter':{'lockTorque','primaryOutputID','defaultVirtualInertia'},
                 'reduction':{'gearRatio','direction'},'shaft':{'gearRatio','direction'},'differential':{'gearRatio'},'wheel':set()}[kind]
        if set(params)-allowed:raise ValueError(d['id']+': unsupported settings '+', '.join(sorted(set(params)-allowed)))
        for k, v in params.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(d['id'] + ': ' + k + ' must be a finite number')
        ratio = params.get('gearRatio', 1.)
        if ratio <= 0: raise ValueError(d['id'] + ': gearRatio must be positive; port axes specify orientation')
        if params.get('direction',1) not in (-1,1):raise ValueError(d['id']+': direction must be +1 or -1')
        if any(params.get(k,1)<=0 for k in ('inertia','minGearRatio','maxGearRatio','lockTorque','parkLockTorque','defaultVirtualInertia')):raise ValueError(d['id']+': inertia, ratios and capacities must be positive')
        if params.get('minGearRatio',.8)>params.get('maxGearRatio',3.):raise ValueError(d['id']+': CVT minimum exceeds its maximum ratio')
        if params.get('engageRPMStart',1600)>=params.get('engageRPMEnd',2300):raise ValueError(d['id']+': clutch engagement RPM range is reversed')
        if params.get('primaryOutputID',1) not in (1,2):raise ValueError(d['id']+': primary output must be port 1 or 2')
        if kind == 'wheel' and d.get('wheel') not in CORNERS: raise ValueError(d['id'] + ': choose an existing suspension hub')
    for kind in ('engine', 'cvt'):
        if sum(d['type'] == kind for d in devices.values()) != 1:
            raise ValueError('Driveline needs exactly one ' + kind + ' for the current vehicle controller')
    wheel_names = [d['wheel'] for d in devices.values() if d['type'] == 'wheel']
    if len(set(wheel_names)) != len(wheel_names): raise ValueError('Wheel hub has multiple torque inputs')
    adjacent = {e: [] for e in endpoints}; body_owners = set()
    for s in shafts.values():
        owner = s.get('member') or s.get('component')
        if owner in body_owners: raise ValueError(s['id'] + ': shaft physical owner is duplicated')
        body_owners.add(owner)
        if s.get('member') and any(v.get('component')==s.get('component') and not v.get('member') for v in shafts.values()):
            raise ValueError(s['id']+': whole-group and moving-member shaft ownership cannot overlap')
        if components is not None and s.get('component') not in components: raise ValueError(s['id'] + ': missing CAD owner')
        if s.get('member') and project is not None and 'JointWorkspace' in project and members.get(s['member'], {}).get('ComponentId') != s.get('component'):
            raise ValueError(s['id'] + ': moving member belongs to another component')
        ideal = s.get('representation','detailed') == 'ideal'
        if s.get('representation','detailed') not in ('ideal','detailed') or ideal and spec['version'] != 2:
            raise ValueError(s['id'] + ': unsupported shaft representation')
        if ideal and (s.get('member') or any(v['component']==s['component'] for v in devices.values())):
            raise ValueError(s['id'] + ': assign a separate CAD shaft group')
        travel = s.get('half_travel_m', 0)
        if type(travel) not in (int,float) or not math.isfinite(travel) or travel < 0 or travel and not ideal:
            raise ValueError(s['id'] + ': invalid ideal shaft half travel')
        for key in ('a', 'b'):
            e = endpoints.get(s.get(key))
            if not e or not (ideal and e['id'] in ports) and (e['component'] != s.get('component') or (e.get('member') or None) != (s.get('member') or None)):
                raise ValueError(s['id'] + ': both endpoints must belong to this shaft body/member')
        a, b = s['a'], s['b']
        if a==b:raise ValueError(s['id']+': choose two distinct shaft endpoints')
        if all(endpoints[k].get('position') is not None for k in (a,b)):
            length=np.linalg.norm(np.array(endpoints[a]['position'])-endpoints[b]['position'])
            if length<.001:raise ValueError(s['id']+': shaft endpoints must be separated by at least 1 mm')
            if travel>=length*.5:raise ValueError(s['id']+': half travel must be less than half the shaft length')
        adjacent[a].append((b, 'shaft', s['id'])); adjacent[b].append((a, 'shaft', s['id']))
    pairs = set();shaft_ends={e for s in shafts.values() for e in (s['a'],s['b'])}
    for link in links.values():
        a, b = link.get('a'), link.get('b'); kind = link.get('kind')
        if a not in endpoints or b not in endpoints or a == b: raise ValueError(link['id'] + ': select two distinct endpoints')
        pair = frozenset((a, b))
        if pair in pairs: raise ValueError(link['id'] + ': duplicate endpoint connection')
        pairs.add(pair)
        if kind not in ('spherical', 'slider', 'bearing', 'internal', 'direct'): raise ValueError(link['id'] + ': unsupported connection kind')
        ea, eb = endpoints[a], endpoints[b]
        if kind=='bearing' and ((a in shaft_ends)==(b in shaft_ends)):
            raise ValueError(link['id']+': a bearing connects one shaft endpoint to a separate support body')
        if kind in ('internal', 'direct'):
            if a not in ports or b not in ports or kind=='internal' and ea['component'] != eb['component']:
                raise ValueError(link['id'] + ': direct connection requires device ports; internal connections share a housing')
        else:
            if ea.get('position') is None or eb.get('position') is None:raise ValueError(link['id']+': capture both joint centres')
            if np.linalg.norm(np.array(ea['position'])-eb['position']) > 1e-4:
                raise ValueError(link['id'] + ': joint centres do not coincide; capture the actual shared centre')
            if kind == 'slider':
                travel = link.get('travel', 0)
                if isinstance(travel, bool) or not isinstance(travel, (int, float)) or not math.isfinite(travel) or travel <= 0:
                    raise ValueError(link['id'] + ': slider needs explicit positive half travel in metres')
                if abs(np.dot(vector(ea['axis'], a, True), vector(eb['axis'], b, True))) < .999:
                    raise ValueError(link['id'] + ': slider axes must align')
        if kind != 'bearing':
            adjacent[a].append((b, kind, link['id'])); adjacent[b].append((a, kind, link['id']))
    for s in shafts.values():
        legacy=s.get('legacy_plunge_m',0.)
        if isinstance(legacy,bool) or not isinstance(legacy,(int,float)) or not math.isfinite(legacy) or legacy<0:raise ValueError(s['id']+': invalid preserved plunge requirement')
        if s.get('representation')=='ideal':
            for end in (s['a'],s['b']):
                if end in ports and any(l['kind']=='bearing' and end in (l['a'],l['b']) for l in links.values()):
                    raise ValueError(s['id']+': use a detailed section for an explicit bearing')
                if end not in ports:
                    incident=[l for l in links.values() if end in (l['a'],l['b'])]
                    if len(incident)!=1 or incident[0]['kind']!='spherical' or not ({incident[0]['a'],incident[0]['b']}-{end}) <= ports.keys():
                        raise ValueError(s['id']+': ideal shaft ends must terminate on device ports')
            if legacy and abs(s.get('half_travel_m',0)-legacy)>1e-8:raise ValueError(s['id']+': preserve original half travel')
            continue
        if legacy and not any(l['kind']=='slider' and (l['a'] in (s['a'],s['b']) or l['b'] in (s['a'],s['b'])) and abs(l.get('travel',0.)-legacy)<1e-8 for l in links.values()):
            raise ValueError(s['id']+': preserve original '+str(legacy)+' m half plunge with a declared sliding interface and separate moving members; no fixed-length conversion is inferred')
    # Physical shafts cannot branch. Branches exist inside typed devices.
    bearing_sites={l[k] for l in links.values() if l['kind']=='bearing' for k in ('a','b')}
    for key, edges in adjacent.items():
        expected = 1 if key in ports else 0 if not edges and key in bearing_sites else 2
        if len(edges) != expected:
            raise ValueError(key + ': endpoint needs ' + str(expected) + ' torque-path connections; branching requires a device')
    routes = []; used_shafts = set()
    for source in sorted(ports):
        p = ports[source]
        if p['direction'] != 'output': continue
        previous = None; current = source; path = []; seen = set()
        while True:
            if current in seen: raise ValueError(source + ': shaft connection cycle')
            seen.add(current)
            edges = [v for v in adjacent[current] if v[0] != previous]
            if len(edges) != 1: raise ValueError(source + ': shaft route is disconnected or branches')
            nxt, kind, identity = edges[0]
            if kind == 'shaft': path.append(identity); used_shafts.add(identity)
            previous, current = current, nxt
            if current in ports:
                if ports[current]['direction'] != 'input': raise ValueError(source + ': output connects to another output')
                routes.append(dict(source=port_owners[source], port=p['index'], target=port_owners[current], shafts=path))
                break
    if used_shafts != set(shafts): raise ValueError('Every shaft must belong to a connected device-to-device torque path')
    incoming = {}
    for r in routes:
        if r['target'] in incoming: raise ValueError(r['target'] + ': multiple torque inputs')
        incoming[r['target']] = r
    for key,d in devices.items():
        if d['type']=='clutch':
            route=incoming.get(key)
            if not route or devices[route['source']]['type']!='engine' or route['shafts']:
                raise ValueError(key+': native centrifugal clutch must connect directly to the engine')
    root = next(d['id'] for d in devices.values() if d['type'] == 'engine')
    visited = set(); order = []
    def walk(key):
        if key in visited: raise ValueError(key + ': torque cycle or multiple parents')
        visited.add(key); order.append(key)
        for r in sorted((r for r in routes if r['source'] == key), key=lambda r: (r['port'], r['target'])): walk(r['target'])
    walk(root)
    if visited != set(devices): raise ValueError('Driveline contains devices disconnected from the engine')
    if not wheel_names: raise ValueError('Connect at least one driven wheel hub')
    wheel_ports={p['endpoint'] for device in devices.values() if device['type']=='wheel' for p in device['ports']}
    required={p['endpoint'] for device in devices.values() if device['type']=='engine' for p in device['ports']}
    required.update(end for shaft in shafts.values() if shaft.get('representation')!='ideal' for end in (shaft['a'],shaft['b']))
    for key in shaft_ends-wheel_ports:
        if endpoints[key].get('position') is None:raise ValueError(key+': capture the shaft attachment centre')
    for route in routes:
        if devices[route['target']]['type']=='wheel':
            required.update(p['endpoint'] for p in devices[route['source']]['ports'] if p['direction']=='output' and p['index']==route['port'])
    for key in required-wheel_ports:
        if endpoints[key].get('axis') is None:raise ValueError(key+': capture the attachment or reaction datum')
    return dict(devices=devices, endpoints=endpoints, shafts=shafts, routes=routes, incoming=incoming, order=order)


def native_names(data):
    return {key: ('mainEngine' if d['type'] == 'engine' else 'gearbox' if d['type'] == 'cvt' else 'drive_'+key)
            for key, d in data['devices'].items()}


def compile(spec, engine_nodes, cvt_node, parameters):
    """Compile topology; reuse the current device recipes, never their wiring."""
    from vehicle_drivetrain import generate
    data = validate(spec); names = native_names(data)
    recipe_parameters={k:v for k,v in parameters.items() if k not in ('rear_reduction','front_reduction','front_output_ratio')}
    part, old = generate('cvt_rear_drive', recipe_parameters, engine_nodes, cvt_node)
    engine = copy.deepcopy(part['mainEngine']); clutch = copy.deepcopy(part.pop('clutch')); cvt = copy.deepcopy(part['gearbox'])
    rows = [['type', 'name', 'inputName', 'inputIndex']]; devices = {}; terminal = {}; reductions = {}
    for identity in data['order']:
        d = data['devices'][identity]; name = names[identity]; kind = d['type']; opts = settings(d.get('parameters'))
        ratio = float(opts.get('gearRatio', 1))*opts.pop('direction',1)
        if kind == 'engine': parent, port = 'dummy', 0; reductions[identity] = 1.
        else:
            route = data['incoming'][identity]; parent = names[route['source']]; port = route['port']
            for shaft in route['shafts']:
                shaft_name = 'shaft_'+shaft
                rows.append(['shaft', shaft_name, parent, port, {'gearRatio': 1}])
                devices[shaft_name] = dict(type='shaft', inputName=parent, inputIndex=port, gearRatio=1)
                parent, port = shaft_name, 1
            reductions[identity] = reductions[route['source']] * ratio
        config = {}
        if kind == 'engine': config = engine
        elif kind == 'clutch': config = copy.deepcopy(clutch)
        elif kind == 'cvt': config = copy.deepcopy(cvt)
        elif kind == 'differential': opts['diffType'] = 'open'
        elif kind == 'splitter': opts.update(splitType='locked', primaryOutputID=int(opts.get('primaryOutputID',1)), defaultVirtualInertia=opts.get('defaultVirtualInertia',10))
        elif kind == 'wheel': opts['connectedWheel'] = d['wheel']; terminal[d['wheel']] = name
        if kind in ('shaft', 'reduction', 'differential'): opts['gearRatio'] = ratio
        if config:
            config.update(opts); part[name] = config; rowopts = {}
            if kind=='cvt' and not 0<config['minGearRatio']<=config['maxGearRatio']:raise ValueError(identity+': invalid effective CVT ratio range')
        else: rowopts = opts
        rows.append([TYPES[kind][0], name, parent, port, rowopts])
        devices[name] = dict(type=TYPES[kind][0], inputIndex=port, **({'inputName': parent} if kind != 'engine' else {}),
                             **({'gearRatio': ratio} if kind in ('shaft', 'reduction', 'differential') else {}))
        if kind=='splitter':devices[name]['primaryOutputID']=opts['primaryOutputID']
    part['powertrain'] = rows
    clutches = [names[k] for k, d in data['devices'].items() if d['type'] == 'clutch']
    contract = dict(version=2, template='driveline_graph', roles=dict(engine='mainEngine', transmission='gearbox',
                    **({'clutch': clutches[0]} if len(clutches) == 1 else {})), devices=devices,
                    driven_wheels=sorted(terminal), wheel_devices=terminal, device_ids=names,
                    wheel_reductions={d['wheel']: abs(reductions[k]) for k, d in data['devices'].items() if d['type'] == 'wheel'},
                    reduction_reference='Engine output, excluding variable CVT ratio',
                    wheel_rotation_signs={d['wheel']:1 if reductions[k]>0 else -1 for k,d in data['devices'].items() if d['type']=='wheel'},
                    graph_sha256=hashlib.sha256(json.dumps(spec, sort_keys=True, allow_nan=False).encode()).hexdigest(),
                    graph=copy.deepcopy(spec), assumptions=[v for v in old['assumptions'] if 'locked carrier takeoff' not in v and 'clutch engagement begins' not in v] + [
                        'Device operating defaults remain provisional unless explicitly supplied; graph connectivity does not qualify hardware settings.',
                        'Explicit CAD endpoint graph; positional shaft articulation and ideal torque routing. Spin animation, Cardan phasing and torsional rupture are not modeled.'])
    if 'engine_reference' in old: contract['engine_reference'] = old['engine_reference']
    return part, contract


def wheel_housings(spec):
    return {corner:value['component'] for corner,value in wheel_reactions(spec).items()}


def wheel_reactions(spec):
    data = validate(spec); result = {}
    for key, d in data['devices'].items():
        if d['type'] != 'wheel': continue
        route=data['incoming'][key];current = route['source']
        # React against the explicitly owned final drive device, including
        # standalone reductions or ideal shafts in another mounted housing.
        device=data['devices'][current]
        port=next(p for p in device['ports'] if p['direction']=='output' and p['index']==route['port'])
        result[d['wheel']] = dict(component=device['component'],axis=data['endpoints'][port['endpoint']]['axis'])
    return result
