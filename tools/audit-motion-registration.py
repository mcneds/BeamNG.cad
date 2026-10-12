"""Compare full and bounded chassis registration on identical recorded samples."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle_motion import rigid_fit, Predictor, angles, angle_error, hub_datum


def analyze(run):
    files = ['build_manifest.json', 'job.json', 'motion_diagnostics.json', 'frequency.json']
    manifest, job, motion, meta = [json.loads((run / n).read_bytes()) for n in files]
    full = job['motion_reference']['chassis']
    subset = meta['config']['chassis_nodes']
    original = {n: np.array(v['position']) for n, v in manifest['nodes'].items()}
    predictor = Predictor(manifest)
    rows = []
    for sample in motion['samples']:
        if not meta['config']['start_s'] <= sample['t'] <= sum(meta['config'][k] for k in ('start_s', 'duration_s')):
            continue
        world = sample['reference_positions']
        fits = [rigid_fit(np.array([original[n] for n in ids]), np.array([world[n] for n in ids]),
                         np.array([manifest['nodes'][n]['mass_kg'] for n in ids])) for ids in (full, subset)]
        values = {}
        for corner in ('FL', 'FR'):
            mapping = job['motion_reference']['corners'][corner]
            p = predictor.mechanisms[corner].p
            errors = []
            travels = []
            for rotation, translation in fits:
                axis_points = [(np.array(world[n])-translation) @ rotation.T for n in mapping['axis']]
                hub = hub_datum(p['hub'], [original[n] for n in mapping['axis']], axis_points)
                travel = float(hub[2]-p['hub'][2])
                extension = sample['actuator_rest_lengths'][corner]-np.linalg.norm(p['tie_outer']-p['tie_inner'])
                pose = predictor.solve(corner, travel, extension)
                expected = (pose['hub_axis']-pose['hub'])*(1 if p['hub_axis'][0]>p['hub'][0] else -1)
                errors.append(float(angle_error(angles(axis_points[1]-axis_points[0]), angles(expected))[1]))
                travels.append(travel)
            values[corner] = dict(full_toe_error_deg=errors[0], subset_toe_error_deg=errors[1],
                                  difference_deg=errors[1]-errors[0], travel_difference_m=travels[1]-travels[0])
        rows.append(dict(time_s=sample['t'], corners=values))
    if len(rows) < 10:
        raise ValueError('Insufficient shared-time motion samples')
    statistics_audit = None
    if meta['config'].get('full_chassis_registration'):
        files += ['frequency.csv', 'frequency_chassis.csv']
        data = np.loadtxt(run/'frequency.csv', delimiter=',', skiprows=1)
        statistics = np.loadtxt(run/'frequency_chassis.csv', delimiter=',', skiprows=1)
        if statistics.shape != (len(data), 13) or not np.array_equal(statistics[:,0], data[:,0]):
            raise ValueError('Incomplete chassis statistics')
        weights = np.array([manifest['nodes'][n]['mass_kg'] for n in full]);weights /= weights.sum()
        rest = np.array([original[n] for n in full]);center = weights @ rest
        captured = data[:,2:].reshape(len(data),len(meta['nodes']),3)
        errors = [];lags = []
        for sample in motion['samples']:
            indices = np.flatnonzero(abs(data[:,1]-sample['t']) < 1e-8)
            if not len(indices):continue
            world = sample['reference_positions']
            expected = np.array([world[n] for n in meta['nodes']])
            distances = np.max(np.linalg.norm(captured[indices]-expected,axis=2),axis=1)
            best = int(np.argmin(distances))
            if distances[best]>1e-8:continue
            index = indices[best];points = np.array([world[n] for n in full])
            h = ((rest-center)*weights[:,None]).T @ (points-points[0])
            errors.append(float(max(abs(statistics[index,1:]-np.r_[weights@points,h.ravel()]))))
            lags.append(float(sample['t']-data[index,0]))
        if len(errors)<10 or max(errors)>1e-8:raise ValueError('Native statistics differ from full node recording')
        statistics_audit = dict(status='passed',matched_position_samples=len(errors),maximum_absolute_statistic_error=max(errors),
                               control_minus_physics_time_s=[min(lags),max(lags)],
                               note='Matched by identical positions within the control interval, not by treating control time as physics time.')
    return dict(scope=__doc__, full_chassis_nodes=len(full), subset_chassis_nodes=len(subset), samples=len(rows),
                statistics_audit=statistics_audit,
                corners={c: dict(max_toe_difference_deg=max(abs(r['corners'][c]['difference_deg']) for r in rows),
                                 max_travel_difference_m=max(abs(r['corners'][c]['travel_difference_m']) for r in rows)) for c in ('FL', 'FR')},
                history=rows, evidence_sha256={n:hashlib.sha256((run/n).read_bytes()).hexdigest() for n in files})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    report = analyze(args.run)
    (args.run/'motion_registration_audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'history'}, indent=2))
