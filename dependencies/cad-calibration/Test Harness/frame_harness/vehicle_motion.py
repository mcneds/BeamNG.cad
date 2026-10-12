"""Compare native motion with rigid-link kinematics, without fitting away damage.

Travel and the recorded actuator rest length are inputs, not predictions. Chassis
motion is removed by a proper, mass-weighted rigid fit. This diagnoses geometric
compliance; it is not a tire/road/load-dependent vehicle dynamics reference.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys
import numpy as np
from .build import write_json


def reference(manifest):
    definition = manifest.get('template_definition')
    if not definition:
        return None
    chassis = manifest['chassis_nodes']
    corners = {}
    for corner, points in definition['hardpoints'].items():
        wheel = manifest['wheels'][corner]
        # Compatibility with already sealed templates. New exports declare the
        # mapping explicitly, so namespaces never depend on a body display name.
        prefix = wheel['nodes']['axis_in'].removesuffix('axis_in')
        bindings = wheel.get('hardpoint_nodes', {k: prefix+k for k in points if prefix+k in manifest['nodes']})
        required = set(points)-{'hub','hub_axis'}
        if not required.issubset(bindings): raise ValueError('Missing semantic motion bindings for '+corner)
        corners[corner] = dict(points=bindings, axis=[wheel['nodes']['axis_in'], wheel['nodes']['axis_out']])
    owners = {owner for owner, role in manifest['component_roles'].items()
              if role and any(s in role for s in ('wishbone', 'upright', 'trailing_arm'))}
    bodies = {owner: list(manifest.get('mass_allocations', {}).get(owner, {})) or
              [n for n, v in manifest['nodes'].items() if v['component'] == owner] for owner in owners}
    steering=manifest.get('steering_contract')
    if definition.get('steering',{}).get('kind')=='translating_rack':
        if not steering or steering.get('kind')!='translating_rack':raise ValueError('Missing translating rack recording contract')
        bodies['steering_slider']=steering['slider_nodes'];bodies['steering_housing']=steering['housing_nodes']
    fixed=dict(manifest.get('fixed_attachment_contract', {}))
    # Legacy fixed-mount templates promise frame-fixed bodies, including groups
    # that have not received an explicit attachment repair. Monitor all of them
    # so a second tab/accessory group cannot silently drop out of the test.
    # Authored mounts can have moving parents and need their own relative frame.
    if 'attachment_contract' not in definition:
        released={v['child'] for v in manifest.get('mounts',[]) if v.get('group')}
        slider=definition.get('steering',{}).get('component')
        for owner in definition.get('fixed_mounts',{}):
            ids=list(manifest.get('mass_allocations',{}).get(owner,{}))
            if ids and owner not in released and owner!=slider:
                fixed.setdefault(owner,dict(nodes=ids))
    names = set(chassis)
    for attachment in fixed.values():
        names.update(attachment['nodes'])
    for group in bodies.values(): names.update(group)
    for corner in corners.values():
        names.update(corner['points'].values()); names.update(corner['axis'])
    shafts = {}
    for chain in manifest.get('shaft_chains', {}).values():
        for joint in chain['joints']:
            names.add(joint['node']); names.update(joint['support_nodes'])
        for section in chain['segments']:
            if section['component'] in shafts:raise ValueError('Duplicate shaft section in motion reference')
            ids=section['nodes']; length=section['length_m']; plunge=section['plunge_m']
            if len(ids)!=2 or not np.isfinite([length,plunge]).all() or not 0<=plunge<length*.5:
                raise ValueError('Invalid shaft section motion reference')
            if any(n not in manifest['nodes'] for n in ids):raise ValueError('Missing shaft section reference nodes')
            actual=np.linalg.norm(np.array(manifest['nodes'][ids[1]]['position'])-manifest['nodes'][ids[0]]['position'])
            if abs(actual-length)>1e-7:raise ValueError('Shaft section rest length differs from its reference nodes')
            shafts[section['component']]=section;names.update(ids)
    if any(name not in manifest['nodes'] for name in names):
        raise ValueError('Motion reference contains missing nodes')
    joints = {j['id']: j['nodes'] for j in manifest.get('joints', []) if all(n in names for n in j['nodes'])}
    return dict(version=2, chassis=chassis, corners=corners, bodies=bodies, joints=joints, shafts=shafts, steering=steering, fixed_components=fixed, nodes=sorted(names))


def rigid_fit(original, current, weights=None):
    original, current = np.asarray(original), np.asarray(current)
    weights = np.ones(len(original)) if weights is None else np.asarray(weights)
    weights = weights / weights.sum()
    a = weights @ original; b = weights @ current
    x = original-a; y = current-b
    if np.linalg.matrix_rank(x, tol=1e-8) < 2:
        raise ValueError('Chassis/body registration points are collinear')
    u, _, vt = np.linalg.svd((x*weights[:, None]).T @ y)
    rotation = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
    return rotation, b-a@rotation


def angles(axis):
    axis = np.asarray(axis, float)
    if np.linalg.norm(axis) < 1e-6: raise ValueError('Collapsed wheel axis')
    # Axis order is fixed by the initial +X axle; do not flip a damaged axis.
    return np.degrees([np.arctan2(axis[2], np.linalg.norm(axis[:2])), np.arctan2(axis[1], axis[0])])


def angle_error(actual, ideal):
    return (np.asarray(actual)-ideal+180) % 360-180


def hub_datum(reference_hub, original_axis, current_axis):
    """Recover the CAD bearing datum on the measured axle, not its mass centre."""
    original_axis=np.asarray(original_axis,float);current_axis=np.asarray(current_axis,float)
    center=original_axis.mean(axis=0);delta=original_axis[1]-original_axis[0]
    squared=float(delta@delta)
    if squared<1e-12:raise ValueError('Collapsed reference wheel axis')
    offset=np.asarray(reference_hub,float)-center
    fraction=float(offset@delta/squared)
    if np.linalg.norm(offset-fraction*delta)>1e-6:
        raise ValueError('CAD hub datum is not on the generated wheel axis')
    return current_axis.mean(axis=0)+fraction*(current_axis[1]-current_axis[0])


class Predictor:
    def __init__(self, manifest):
        wizard = Path(__file__).resolve().parents[2]/'Vehicle Wizard'
        if str(wizard) not in sys.path: sys.path.insert(0, str(wizard))
        from vehicle_wizard.kinematics import Mechanism
        definition = manifest['template_definition']
        class Model:
            data = dict(parameters=dict(travel_m=.16, steer_degrees=28) | definition.get('parameters', {}),
                        steering=definition.get('steering',{}),
                        corners={c: dict(template=definition['templates']['front_suspension' if c[0]=='F' else 'rear_suspension'], links=[])
                                 for c in definition['hardpoints']})
            def corner_points(self, corner):
                return {k: np.array(v, float) for k, v in definition['hardpoints'][corner].items()}
        self.mechanisms = {c: Mechanism(Model(), c) for c in definition['hardpoints']}
        self.previous = {}

    def solve(self, corner, height, extension):
        mechanism = self.mechanisms[corner]
        x, pose = mechanism.solve(height, extension, self.previous.get(corner))
        self.previous[corner] = x
        return pose


def turn_heading(records, scenario):
    """Unwrap chassis heading so crossing +/-180 degrees preserves turn sense."""
    yaw=np.degrees(np.unwrap(np.radians([s['yaw_deg'] for s in records])))
    # The fitted row-vector chassis rotation is negative for a left turn.
    signed=(yaw-yaw[0])*(-1 if scenario=='left_turn' else 1)
    active=np.array([s['t']>=4 for s in records])
    # Count cumulative backtracking from any previous extremum, including the
    # initial heading. Small rigid-fit noise is allowed; reversing a turn is not.
    reversal=np.maximum.accumulate(signed)-signed
    metrics=dict(requested_heading_change_deg=float(signed[-1]),
                 peak_turn_heading_reversal_deg=float(max(reversal[active])))
    return dict(turn_heading_requested=metrics['requested_heading_change_deg']>=45.,
                turn_heading_consistent=metrics['peak_turn_heading_reversal_deg']<=5.),metrics


def rack_actuator_target(sample,contract,half_travel):
    value=sample.get('rack_target_m')
    if value is None or not np.isfinite(value) or abs(value)>half_travel+.001:
        raise ValueError('Missing or invalid native rack actuator target')
    if 'actuators' in contract:
        targets=sample.get('rack_targets_m',[])
        if (not contract['actuators'] or len(targets)!=len(contract['actuators']) or
                not np.isfinite(targets).all() or any(abs(t-value)>1e-6 for t in targets)):
            raise ValueError('Missing or inconsistent paired rack actuator targets')
    return value


def compare(manifest, motion, scenario):
    ref = reference(manifest)
    if ref is None: return None
    samples = motion.get('samples', [])
    if motion.get('motion_reference_version') != 2 or len(samples) < 10:
        raise ValueError('Missing ideal-motion telemetry; rerun with the current recorder')
    time = np.array([s['t'] for s in samples])
    if not np.isfinite(time).all() or np.any(np.diff(time) <= 0) or max(np.diff(time)) > .6:
        raise ValueError('Incomplete or nonmonotonic motion telemetry')
    for sample in samples:
        if sample['t']<4:continue
        applied=sample.get('steering_applied')
        if applied is None or not np.isfinite(applied) or not np.isfinite(sample.get('steering_command',np.nan)):
            raise ValueError('Missing or invalid applied steering telemetry')
        if sample.get('control_source')!='cadHarness' or sample.get('control_filter')!='FILTER_AI':
            raise ValueError('Recording used an uncontrolled or assisted input source')
    original = {n: np.array(v['position'], float) for n, v in manifest['nodes'].items()}
    chassis = ref['chassis']; origin = np.array([original[n] for n in chassis])
    weights = np.array([manifest['nodes'][n]['mass_kg'] for n in chassis])
    predictor = Predictor(manifest); records = []; first_rotation = None; first_center = None
    for sample in samples:
        world = sample.get('reference_positions', {})
        if any(n not in world for n in ref['nodes']): raise ValueError('Motion telemetry is missing reference nodes')
        points = np.array([world[n] for n in ref['nodes']], float)
        if not np.isfinite(points).all(): raise ValueError('Nonfinite motion positions')
        r, translation = rigid_fit(origin, np.array([world[n] for n in chassis]), weights)
        local = {n: (np.array(world[n])-translation) @ r.T for n in ref['nodes']}
        chassis_errors = {n:float(np.linalg.norm(local[n]-original[n])) for n in chassis}
        worst_chassis = max(chassis_errors, key=chassis_errors.get)
        center = weights @ np.array([world[n] for n in chassis])/weights.sum()
        if first_rotation is None: first_rotation, first_center = r, center
        delta = (center-first_center) @ first_rotation.T
        relative_rotation = r @ first_rotation.T
        heading = np.degrees(np.arctan2(relative_rotation[1, 0], relative_rotation[1, 1]))
        row = dict(t=float(sample['t']), steering_command=float(sample['steering_command']),
                   steering_applied=sample.get('steering_applied'),
                   lateral_m=float(delta[0]), forward_m=float(-delta[1]), yaw_deg=float(heading),
                   chassis_shape_error_m=chassis_errors[worst_chassis], worst_chassis_node=worst_chassis,
                   bodies={}, corners={}, joints={}, shafts={}, fixed_components={})
        for owner, attachment in ref['fixed_components'].items():
            row['fixed_components'][owner]=float(max(np.linalg.norm(local[n]-original[n]) for n in attachment['nodes']))
        for owner, section in ref['shafts'].items():
            a,b=(local[n] for n in section['nodes']); length=float(np.linalg.norm(b-a))
            error=abs(length-section['length_m'])
            row['shafts'][owner]=dict(length_m=length,length_error_m=error,
                beyond_plunge_m=max(0.,error-section['plunge_m']))
        for name, ids in ref['joints'].items():
            child=ids[-1];parents=ids[:-1]
            stretch=max((abs(np.linalg.norm(local[n]-local[child])-np.linalg.norm(original[n]-original[child])) for n in parents),default=0.)
            row['joints'][name]=dict(max_attachment_length_error_m=float(stretch),
                                    parent_displacement_m=float(max((np.linalg.norm(local[n]-original[n]) for n in parents),default=0.)))
        for owner, names in ref['bodies'].items():
            initial = np.array([original[n] for n in names]); current = np.array([local[n] for n in names])
            br, bt = rigid_fit(initial, current)
            residual = np.linalg.norm(initial@br+bt-current, axis=1)
            row['bodies'][owner] = dict(shape_error_m=float(max(residual)), worst_node=names[int(np.argmax(residual))])
        for corner, mapping in ref['corners'].items():
            mechanism = predictor.mechanisms[corner]; p = mechanism.p
            a, b = (local[n] for n in mapping['axis'])
            hub=hub_datum(p['hub'],[original[n] for n in mapping['axis']],[a,b])
            actual = {k: local[n] for k, n in mapping['points'].items()}
            actual['hub'] = hub
            actual['hub_axis'] = hub + (b-a)/np.linalg.norm(b-a)*np.linalg.norm(p['hub_axis']-p['hub'])*(1 if p['hub_axis'][0]>p['hub'][0] else -1)
            extension = 0.; tie_error = 0.
            if mechanism.wishbone or mechanism.radius_toe or mechanism.ball_radius_toe:
                length = float(np.linalg.norm(p['tie_outer']-p['tie_inner']))
                target = sample.get('actuator_rest_lengths', {}).get(corner) if mechanism.front and not mechanism.translating_rack else length
                alignment = manifest['wheels'][corner].get('toe_link')
                if alignment:
                    target = sample.get('actuator_rest_lengths', {}).get(corner)
                    if (target is None or not np.isfinite(target)
                            or abs(target-float(alignment['reference_length_m']))>1e-6):
                        raise ValueError('Missing or changed native rear toe-link rest length for '+corner)
                if target is None or not np.isfinite(target): raise ValueError('Missing steering actuator target for '+corner)
                extension = target-length
                if mechanism.translating_rack:
                    extension=rack_actuator_target(sample,manifest['steering_contract'],mechanism.steering['half_travel_m'])
                tie_error = float(np.linalg.norm(actual['tie_outer']-actual['tie_inner'])-target)
            travel = float(hub[2]-p['hub'][2]); measured_angles = angles(b-a)
            item = dict(travel_m=travel, actual_camber_deg=float(measured_angles[0]), actual_toe_deg=float(measured_angles[1]),
                        axle_length_error_m=float(np.linalg.norm(b-a)-np.linalg.norm(original[mapping['axis'][1]]-original[mapping['axis'][0]])),
                        tie_length_error_m=tie_error, actuator_extension_m=extension,
                        actual={k:v.tolist() for k,v in actual.items()})
            try:
                pose = predictor.solve(corner, travel, extension)
                axis = pose['hub_axis']-pose['hub']; axis *= 1 if p['hub_axis'][0]>p['hub'][0] else -1
                expected_angles = angles(axis); error = angle_error(measured_angles, expected_angles)
                fixed = [k for k in actual if k.endswith(('inner_front','inner_rear')) or k in ('trailing_ball','hinge_inner','hinge_outer','tie_inner','radius_upper_inner','radius_lower_inner','shock_top')]
                point_error = {k:float(np.linalg.norm(actual[k]-pose[k])) for k in actual if k in pose}
                item.update(ideal={k:v.tolist() for k,v in pose.items()}, ideal_camber_deg=float(expected_angles[0]), ideal_toe_deg=float(expected_angles[1]),
                            camber_error_deg=float(error[0]), toe_error_deg=float(error[1]), hub_path_error_m=point_error['hub'],
                            mount_error_m=max([point_error[k] for k in fixed] or [0.]), point_errors_m=point_error, reachable=True)
            except ValueError as exc:
                item.update(reachable=False, reason=str(exc))
            row['corners'][corner] = item
        records.append(row)
    active = [s for s in records if s['t'] >= 4]
    if not active: raise ValueError('No motion samples after startup')
    checks = {'motion_reference_complete': True,'unassisted_control_source':True}; metrics = {}
    for owner in ref['fixed_components']:
        peak=max(s['fixed_components'][owner] for s in records)
        metrics[owner+'_peak_fixed_displacement_m']=peak
        checks[owner+'_fixed_attachment_holds']=peak<=.005
    # Provisional engineering screening limits, not material qualifications.
    limits = dict(camber_error_deg=2., toe_error_deg=2., hub_path_error_m=.01, mount_error_m=.005,
                  axle_length_error_m=.003, tie_length_error_m=.005)
    for corner in ref['corners']:
        values = [s['corners'][corner] for s in active]
        checks[corner+'_ideal_motion_reachable'] = all(v['reachable'] for v in values)
        for key, limit in limits.items():
            available = [abs(v[key]) for v in values if key in v]
            peak = max(available) if available else None
            metrics[corner+'_peak_'+key] = peak
            checks[corner+'_'+key] = peak is not None and peak <= limit and len(available)==len(values)
    for owner in ref['bodies']:
        peak = max(s['bodies'][owner]['shape_error_m'] for s in active)
        metrics[owner+'_peak_shape_error_m'] = peak; checks[owner+'_holds_shape'] = peak <= .005
    for joint in ref['joints']:
        peak=max(s['joints'][joint]['max_attachment_length_error_m'] for s in active)
        metrics[joint+'_peak_attachment_length_error_m']=peak;checks[joint+'_attachment_holds']=peak<=.003
    for owner in ref['shafts']:
        peak=max(s['shafts'][owner]['beyond_plunge_m'] for s in active)
        metrics[owner+'_peak_beyond_plunge_m']=peak;checks[owner+'_shaft_length_holds']=peak<=.003
    metrics['peak_chassis_shape_error_m'] = max(s['chassis_shape_error_m'] for s in active)
    checks['chassis_holds_reference'] = metrics['peak_chassis_shape_error_m'] <= .005
    if scenario in ('acceleration', 'braking', 'reverse'):
        metrics['peak_uncommanded_lateral_m'] = max(abs(s['lateral_m']) for s in active)
        metrics['peak_uncommanded_yaw_deg'] = max(abs(s['yaw_deg']) for s in active)
        checks['straight_steering_command'] = all(abs(s['steering_command']) < .01 for s in active)
        metrics['peak_applied_steering']=max(abs(s['steering_applied']) for s in active)
        checks['straight_applied_steering']=metrics['peak_applied_steering']<=1e-6
        checks['straight_lateral_drift'] = metrics['peak_uncommanded_lateral_m'] <= .5
        checks['straight_heading'] = metrics['peak_uncommanded_yaw_deg'] <= 5.
    if scenario in ('left_turn','right_turn'):
        turn_checks,turn_metrics=turn_heading(records,scenario)
        checks.update(turn_checks);metrics.update(turn_metrics)
    return dict(version=2, status='passed' if all(checks.values()) else 'failed', checks=checks, metrics=metrics, samples=records,
                limits=limits | dict(body_shape_error_m=.005, chassis_shape_error_m=.005, attachment_length_error_m=.003, lateral_drift_m=.5, yaw_deg=5.,
                                    minimum_turn_heading_deg=45., turn_heading_reversal_deg=5.),
                scope='Rigid-link geometry at measured hub travel and recorded actuator rest length. No prediction of tire forces, speed or natural frequency.',
                sampling_note='Graphics-rate snapshots diagnose geometric drift; they do not resolve high-frequency vibration spectra.')


def analyze_motion(directory, manifest, scenario, end_time, expected_job_id):
    path = Path(directory)/'motion_diagnostics.json'
    if not path.exists(): raise ValueError('Missing ideal-motion telemetry')
    motion = json.loads(path.read_text(encoding='utf-8'))
    if not expected_job_id or motion.get('job_id') != expected_job_id:
        raise ValueError('Ideal-motion recording job identity differs')
    if not motion.get('samples') or motion['samples'][0]['t'] > .6 or end_time-motion['samples'][-1]['t'] > .6:
        raise ValueError('Incomplete ideal-motion recording')
    result = compare(manifest, motion, scenario)
    write_json(Path(directory)/'motion_comparison.json', result)
    from .vehicle_motion_report import write_motion_report
    write_motion_report(directory, result)
    return result
