"""CAD-owned shaft sections with explicit, supported articulation points.

This is a positional chain, coupled to the existing ideal powertrain device.
It does not simulate Cardan phasing, rotating meshes or shaft torsional failure.
"""
from __future__ import annotations
import math
import re
import numpy as np
import components as c


SHAFT_ROLES = frozenset(('front_propshaft', 'cvt_output_shaft'))
REPEATABLE_ROLES = SHAFT_ROLES | {'shaft_carrier'}


def validate(definition, components):
    """Validate before preparing the frame, or creating any output graph.

    Legacy two-end declarations remain valid. Multiple CAD groups with the same
    role must be accounted for by exactly one explicitly ordered chain.
    """
    by_id = {v['Id']: v for v in components}
    if len(by_id) != len(components):
        raise ValueError('Duplicate component identity in shaft inputs')
    fixed = definition.get('fixed_mounts', {})
    legacy = definition.get('shafts', {})
    halfshafts = definition.get('halfshafts', {})
    if set(legacy) & set(halfshafts):
        raise ValueError('A shaft cannot also be declared as a halfshaft')
    used = set(legacy) | set(halfshafts)
    if not used <= set(by_id):raise ValueError('Shaft declaration references a missing CAD component')
    fixed_shafts=set(definition.get('fixed_shafts',[]))
    if len(fixed_shafts)!=len(definition.get('fixed_shafts',[])) or fixed_shafts&used:raise ValueError('Duplicate shaft representation')
    for owner in fixed_shafts:
        if owner not in by_id or by_id[owner].get('MvpRole') not in SHAFT_ROLES or owner not in fixed:
            raise ValueError('Fixed shaft geometry needs an explicit rigid housing/frame attachment')
        points=np.asarray(fixed[owner],float)
        if points.ndim!=2 or points.shape[1]!=3 or len(points)<3 or not np.isfinite(points).all() or np.linalg.matrix_rank(points-points[0],tol=1e-8)<2:
            raise ValueError('Fixed shaft needs three non-collinear rigid support sites')
    used|=fixed_shafts
    result = {}; chain_roles = set(); carriers = set()
    for chain_id, chain in definition.get('shaft_chains', {}).items():
        if set(chain)-{'role','joints','segments'}:raise ValueError('Unknown shaft chain fields: '+chain_id)
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', chain_id):
            raise ValueError('Shaft chain identity must contain only letters, digits and underscores')
        role = chain.get('role')
        if role not in SHAFT_ROLES or role in chain_roles:
            raise ValueError('Shaft chains need a supported, unique shaft role')
        chain_roles.add(role)
        if role == 'front_propshaft' and definition['templates']['drivetrain'] != 'cvt_rear_front_output':
            raise ValueError('Front propshaft chain requires a geared front-output drivetrain')
        joints = chain.get('joints', []); segments = chain.get('segments', [])
        if not segments or len(joints) != len(segments)+1:
            raise ValueError(chain_id+': provide one more joint than shaft sections')
        normalized = []; parent_roles = []
        for index, joint in enumerate(joints):
            if set(joint)-{'position','parent_component'}:raise ValueError(chain_id+': unknown joint fields; only supported positional joints are implemented')
            parent = joint.get('parent_component')
            if parent not in by_id or parent not in fixed:
                raise ValueError(chain_id+': each joint needs an explicit mounted housing or carrier component; unsupported intermediate joints are not implemented')
            parent_role = by_id[parent].get('MvpRole'); parent_roles.append(parent_role)
            if 0 < index < len(joints)-1:
                if parent_role != 'shaft_carrier':
                    raise ValueError(chain_id+': intermediate joints need a separate shaft_carrier CAD group')
                carriers.add(parent)
            elif parent_role not in ('front_diff', 'rear_final_drive', 'rear_diff', 'cvt'):
                raise ValueError(chain_id+': shaft ends must attach to drivetrain housings')
            if len(fixed[parent]) < 3:
                raise ValueError(chain_id+': shaft support needs at least three reviewed mounting points')
            mount_points=np.asarray(fixed[parent],float)
            if mount_points.ndim!=2 or mount_points.shape[1]!=3 or not np.isfinite(mount_points).all() or np.linalg.matrix_rank(mount_points-mount_points[0],tol=1e-8)<2:
                raise ValueError(chain_id+': shaft support mounts must be finite, non-collinear points')
            if by_id[parent].get('Template')!='bulk':
                raise ValueError(chain_id+': shaft housing/carrier requires a bulk physical representation')
            point = np.asarray(joint.get('position'), float)
            if point.shape != (3,) or not np.isfinite(point).all():
                raise ValueError(chain_id+': joint position must be three finite BeamNG coordinates')
            normalized.append(dict(position=point.tolist(), parent_component=parent))
        expected = {'front_diff', 'rear_final_drive'} if role == 'front_propshaft' else {'cvt', 'rear_final_drive' if definition['templates']['drivetrain']=='cvt_rear_front_output' else 'rear_diff'}
        if {parent_roles[0], parent_roles[-1]} != expected:
            raise ValueError(chain_id+': shaft endpoints do not match the selected drivetrain')
        sections = []
        for index, section in enumerate(segments):
            if set(section)-{'component','plunge_m'}:raise ValueError(chain_id+': unknown shaft section fields')
            owner = section.get('component')
            if owner not in by_id or by_id[owner].get('MvpRole') != role:
                raise ValueError(chain_id+': each section needs its own CAD component tagged '+role)
            if owner in used or owner in fixed:
                raise ValueError(chain_id+': shaft section has duplicate physical ownership: '+str(owner))
            used.add(owner)
            a = np.array(normalized[index]['position']); b = np.array(normalized[index+1]['position'])
            length = float(np.linalg.norm(b-a))
            if not math.isfinite(length) or length < .001:
                raise ValueError(chain_id+': shaft section must be at least 1 mm long')
            # No default slip joint: a reviewed zero means a fixed-length rod.
            plunge = section.get('plunge_m')
            if isinstance(plunge, bool) or not isinstance(plunge, (int, float)) or not math.isfinite(plunge) or not 0 <= plunge < length*.5:
                raise ValueError(chain_id+': specify finite plunge_m >= 0 and below half the section length')
            sections.append(dict(component=owner, plunge_m=float(plunge), length_m=length,
                                 axis=((b-a)/length).tolist()))
        result[chain_id] = dict(role=role, joints=normalized, segments=sections,
                               powertrain_device='frontPropshaft' if role=='front_propshaft' else 'rearReduction')
    for role in SHAFT_ROLES:
        owners = {v['Id'] for v in components if v.get('MvpRole') == role}
        declared = {s['component'] for chain in result.values() if chain['role']==role for s in chain['segments']}
        if declared:
            if declared != owners:
                raise ValueError(role+': chain must account for every CAD section; remove stale assignments')
        elif owners<=fixed_shafts:continue
        elif len(owners) > 1:
            raise ValueError(role+': multiple CAD sections require an ordered shaft_chains definition')
        elif owners and not owners <= set(legacy):
            raise ValueError(role+': missing shaft endpoints or shaft_chains definition')
    assigned_carriers = {v['Id'] for v in components if v.get('MvpRole')=='shaft_carrier'}
    if assigned_carriers != carriers:
        raise ValueError('Every shaft_carrier CAD group must support a declared intermediate shaft joint')
    return result


def generate(graph, chains, components, meshes, bindings, supports):
    """One shared positional joint at each carrier; independent masses/skins."""
    by_id = {v['Id']: v for v in components}; contracts = {}
    for chain_id, chain in chains.items():
        from frame_harness.progress import emit
        emit('Connect articulated shafts',completed=len(contracts),total=len(chains),detail=chain_id)
        nodes = ['shaft_chain_'+chain_id+'_joint_'+str(i) for i in range(len(chain['joints']))]
        if any(n in graph.nodes for n in nodes):
            raise ValueError('Shaft chain node identity collides with existing structure: '+chain_id)
        data = []
        for section in chain['segments']:
            owner = section['component']; mesh, moments, _ = c.read_geometry(by_id[owner])
            if not math.isfinite(moments[0]) or moments[0] <= 0:
                raise ValueError(owner+': shaft section requires positive CAD mass')
            if owner in meshes:
                raise ValueError('Shaft section already has a physical representation: '+owner)
            data.append((mesh, moments))
        for index, (node, joint) in enumerate(zip(nodes, chain['joints'])):
            incident = [i for i in (index-1, index) if 0 <= i < len(data)]
            owners = [chain['segments'][i]['component'] for i in incident]
            mass = sum(data[i][1][0]/2 for i in incident)
            options = dict(nodeWeight=float(mass), collision=False, selfCollision=False,
                           group=[owner+'_structure' for owner in owners])
            graph.nodes[node] = dict(position=joint['position'], options=options); graph.owners[node] = owners[0]
            graph.part['nodes'].append([node, *joint['position'], options])
        joint_contracts = []
        for node, joint in zip(nodes, chain['joints']):
            parent = joint['parent_component']; point = np.array(joint['position'])
            support = supports(graph, parent, point)
            graph.spherical(node+'_support', support, node, parent_owner=parent)
            joint_contracts.append(dict(node=node, support_nodes=support, **joint))
        segments = []
        for index, section in enumerate(chain['segments']):
            owner = section['component']; mesh, moments = data[index]; pair = nodes[index:index+2]
            plunge = section['plunge_m']
            if plunge:
                graph.beam(*pair, beamType='|BOUNDED', beamSpring=0, beamDamp=0,
                           shortBoundRange=plunge, longBoundRange=plunge, boundZone=.01,
                           beamLimitSpring=20000, beamLimitDamp=50, dampCutoffHz=100)
            else:
                graph.beam(*pair, beamSpring=20000, beamDamp=50)
            graph.groups[owner] = pair; graph.mass_allocations[owner] = {n:moments[0]/2 for n in pair}
            for joint in joint_contracts[index:index+2]:
                for n in joint['support_nodes']:
                    group = owner+'_structure'
                    if group not in graph.nodes[n]['options']['group']:graph.nodes[n]['options']['group'].append(group)
            graph.reports[owner] = dict(target_mass_kg=moments[0], actual_mass_kg=moments[0],
                allocation_method='endpoint_lumped', shaft_chain=chain_id,
                center_error_m=float(np.linalg.norm((graph.point(pair[0])+graph.point(pair[1]))/2-moments[1])),
                limitations=['Endpoint mass approximation; bending, spin inertia, Cardan phasing and rupture are uncalibrated. Mesh follows its section without spin animation.'])
            meshes[owner] = mesh; bindings[owner] = [owner+'_structure']
            segments.append(section | dict(nodes=pair, mass_kg=moments[0]))
        contracts[chain_id] = dict(role=chain['role'], powertrain_device=chain['powertrain_device'],
            joints=joint_contracts, segments=segments,
            scope='Supported positional chain; ideal existing powertrain connection; joint angular speed variation, visual spin and torsional failure unmodeled')
    return contracts
