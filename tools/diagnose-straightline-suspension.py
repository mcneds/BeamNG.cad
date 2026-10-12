"""Read-only wheel alignment against unchanged CAD kinematics at measured travel.

Uses commanded centred steering, not an inferred native actuator target. This
attributes compliance; it is neither a tire dynamics prediction nor acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle_motion import Predictor, rigid_fit, angles, angle_error


def rack_pose(mechanism, travel, inner, initial):
    """Substitute only the recorded rack point; preserve the original tie length."""
    rest = mechanism.p
    length = np.linalg.norm(rest['tie_outer']-rest['tie_inner'])
    def residual(x):
        pose = mechanism.pose(x)[0]
        constraints = mechanism.constraints(x, 0.).copy()
        constraints[-1] = np.linalg.norm(pose['tie_outer']-inner)-length
        return np.r_[constraints, pose['hub'][2]-rest['hub'][2]-travel]
    fit = least_squares(residual, initial, xtol=1e-12, ftol=1e-12, gtol=1e-12, max_nfev=300)
    if not fit.success or max(abs(fit.fun)) > 1e-7:
        raise ValueError('Recorded rack substitution did not solve')
    return mechanism.pose(fit.x)[0]


def diagnose(run, after=18., rack_substitution=False):
    files = ('build_manifest.json', 'motion.jsonl', 'completion.json', 'job.json')
    manifest = json.loads((run/files[0]).read_text())
    completion = json.loads((run/'completion.json').read_text())
    job = json.loads((run/'job.json').read_text())
    if completion.get('status') != 'completed':
        raise ValueError('Incomplete native recording')
    if job.get('scenario') != 'stock_straightline_diagnostic':
        raise ValueError('Expected controlled straight-line diagnostic')
    motion = [json.loads(line) for line in (run/'motion.jsonl').read_text().splitlines()]
    times = np.array([s['t'] for s in motion])
    if (len(times) < 10 or not np.isfinite(times).all() or
            np.any(np.diff(times) <= 0) or max(np.diff(times)) > .26 or
            times[-1] < job['duration']-.26):
        raise ValueError('Incomplete or nonmonotonic wheel telemetry')
    chassis = manifest['chassis_nodes']
    original = np.array([manifest['nodes'][n]['position'] for n in chassis])
    weights = np.array([manifest['nodes'][n]['mass_kg'] for n in chassis])
    predictor = Predictor(manifest)
    points = manifest['template_definition']['hardpoints']
    signs = {}
    samples = []
    for sample in motion:
        if (not np.isfinite(sample.get('steering_applied', np.nan)) or
                abs(sample['steering_applied']) > 1e-9 or
                sample.get('steering_source') != 'cadHarness' or
                sample.get('steering_filter') != 'FILTER_AI'):
            raise ValueError('Uncontrolled or nonzero steering input')
        world = sample.get('reference_positions', {})
        if any(n not in world for n in chassis):
            raise ValueError('Missing chassis capture')
        current = np.array([world[n] for n in chassis])
        if not np.isfinite(current).all():
            raise ValueError('Nonfinite chassis capture')
        rotation, translation = rigid_fit(original, current, weights)
        corners = {}
        for corner in manifest['wheels']:
            wheel = sample.get('wheels', {}).get(corner)
            if wheel is None:
                raise ValueError('Missing wheel capture: '+corner)
            axis = np.array(wheel['axis']) @ rotation.T
            center = (np.array(wheel['center'])-translation) @ rotation.T
            if not np.isfinite(axis).all() or not np.isfinite(center).all():
                raise ValueError('Nonfinite wheel geometry')
            signs.setdefault(corner, 1 if axis[0] > 0 else -1)
            actual = angles(axis*signs[corner])
            if sample['t'] < after:
                continue
            rest = {name: np.array(value) for name, value in points[corner].items()}
            travel = float(center[2]-rest['hub'][2])
            pose = predictor.solve(corner, travel, 0.)
            expected_axis = pose['hub_axis']-pose['hub']
            expected_axis *= 1 if rest['hub_axis'][0] > rest['hub'][0] else -1
            ideal = angles(expected_axis)
            error = angle_error(actual, ideal)
            corners[corner] = dict(travel_m=travel,
                actual_camber_deg=float(actual[0]), actual_toe_deg=float(actual[1]),
                ideal_camber_deg=float(ideal[0]), ideal_toe_deg=float(ideal[1]),
                camber_error_deg=float(error[0]), toe_error_deg=float(error[1]),
                hub_path_error_m=float(np.linalg.norm(center-pose['hub'])))
            if rack_substitution and corner.startswith('F'):
                mechanism = predictor.mechanisms[corner]
                if not mechanism.wishbone or not mechanism.translating_rack:
                    raise ValueError('Rack substitution requires front wishbones and translating rack')
                name = manifest['wheels'][corner].get('hardpoint_nodes', {}).get('tie_inner', corner+'_tie_inner')
                if name not in world:
                    raise ValueError('Missing rack endpoint capture: '+name)
                inner = (np.array(world[name])-translation) @ rotation.T
                if not np.isfinite(inner).all():
                    raise ValueError('Nonfinite rack endpoint capture')
                initial = predictor.previous[corner].copy()
                control = rack_pose(mechanism, travel, rest['tie_inner'], initial)
                if max(np.linalg.norm(control[n]-pose[n]) for n in ('hub', 'hub_axis')) > 1e-6:
                    raise ValueError('Substitution control disagrees with unchanged CAD kinematics')
                substituted = rack_pose(mechanism, travel, inner, initial)
                axis = substituted['hub_axis']-substituted['hub']
                axis *= 1 if rest['hub_axis'][0] > rest['hub'][0] else -1
                predicted = angles(axis)
                corners[corner]['rack_only_toe_deg'] = float(predicted[1])
                corners[corner]['toe_unexplained_by_rack_deg'] = float(angle_error(actual, predicted)[1])
        if corners:
            samples.append(dict(t=sample['t'], corners=corners))
    if len(samples) < 10:
        raise ValueError('Insufficient suspension samples')
    means = {corner: {key: float(np.mean([s['corners'][corner][key] for s in samples]))
                     for key in samples[0]['corners'][corner]}
             for corner in manifest['wheels']}
    axles = {axle: {key: float(np.mean([means[c][key] for c in corners]))
                   for key in ('actual_toe_deg', 'ideal_toe_deg', 'toe_error_deg',
                               'actual_camber_deg', 'ideal_camber_deg', 'camber_error_deg')}
             for axle, corners in dict(front=('FL', 'FR'), rear=('RL', 'RR')).items()}
    if rack_substitution:
        for key in ('rack_only_toe_deg', 'toe_unexplained_by_rack_deg'):
            axles['front'][key] = float(np.mean([means[c][key] for c in ('FL', 'FR')]))
    return dict(qualified=False, scope=__doc__, run=str(run.resolve()), after_s=after,
        steering_reference='Commanded centred rack; native actuator target not captured',
        means=means, axle_means=axles, samples=samples,
        hashes={name: hashlib.sha256((run/name).read_bytes()).hexdigest() for name in files},
        implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--after', type=float, default=18.)
    parser.add_argument('--rack-substitution', action='store_true', help='Measured rack endpoint only; original tie length and CAD pivots retained')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = diagnose(args.run, args.after, args.rack_substitution)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result['axle_means'], indent=2))
