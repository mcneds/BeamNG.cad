"""Attribute recorded front toe to rack motion using the unchanged CAD linkage.

This is a kinematic substitution, not a causal tire-force model or qualification.
The native sample's suspension travel is held fixed. Only its rack endpoint is
substituted into the independent linkage; tie lengths and CAD pivots stay fixed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle_motion import Predictor, angles, angle_error
rack_pose = runpy.run_path(str(ROOT/'tools/diagnose-straightline-suspension.py'))['rack_pose']


def diagnose(run):
    inputs = ('build_manifest.json', 'motion_comparison.json', 'completion.json', 'job.json')
    manifest, motion, completion, job = [json.loads((run/name).read_text()) for name in inputs]
    if completion.get('status') != 'completed' or job.get('scenario') != 'acceleration':
        raise ValueError('Requires a complete acceleration recording')
    rows = motion['samples']
    times = np.array([r['t'] for r in rows])
    if len(rows) < 10 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0) or times[-1] < job['duration']-.26:
        raise ValueError('Incomplete motion history')
    predictor = Predictor(manifest)
    samples = []
    for row in rows:
        if row['t'] < 4: continue
        if not np.isfinite([row['steering_command'], row['steering_applied']]).all() or max(abs(row[k]) for k in ('steering_command', 'steering_applied')) > 1e-9:
            raise ValueError('Nonzero steering is outside this diagnostic')
        sample = {k: row[k] for k in ('t', 'lateral_m', 'forward_m', 'yaw_deg')}
        sample['corners'] = {}
        for corner in ('FL', 'FR', 'RL', 'RR'):
            data = row['corners'][corner]
            if not data.get('reachable'): raise ValueError('Unreachable linkage sample')
            detail = {k: data[k] for k in ('travel_m', 'actual_toe_deg', 'ideal_toe_deg', 'toe_error_deg')}
            if corner.startswith('F'):
                mechanism = predictor.mechanisms[corner]
                ideal = predictor.solve(corner, data['travel_m'], 0.)
                state = predictor.previous[corner].copy()
                control = rack_pose(mechanism, data['travel_m'], mechanism.p['tie_inner'], state)
                if max(np.linalg.norm(control[n]-ideal[n]) for n in ('hub', 'hub_axis')) > 1e-6:
                    raise ValueError('Substitution control disagrees with CAD reference')
                substituted = rack_pose(mechanism, data['travel_m'], np.array(data['actual']['tie_inner']), state)
                axis = substituted['hub_axis']-substituted['hub']
                axis *= 1 if mechanism.p['hub_axis'][0] > mechanism.p['hub'][0] else -1
                detail['rack_only_toe_deg'] = float(angles(axis)[1])
                detail['toe_unexplained_by_rack_deg'] = float(angle_error(data['actual_toe_deg'], detail['rack_only_toe_deg']))
            sample['corners'][corner] = detail
        samples.append(sample)
    windows = []
    for lo, hi in ((4, 8), (8, 12), (12, 17), (17, 26)):
        selected = [s for s in samples if lo <= s['t'] < hi]
        if not selected: continue
        summary = dict(start_s=lo, end_s=min(hi, times[-1]), samples=len(selected), axles={})
        for name, corners in dict(front=('FL', 'FR'), rear=('RL', 'RR')).items():
            summary['axles'][name] = {k: float(np.mean([s['corners'][c][k] for s in selected for c in corners]))
                                     for k in selected[0]['corners'][corners[0]]}
        windows.append(summary)
    return dict(qualified=False, scope=__doc__, run=str(run.resolve()), windows=windows, samples=samples,
                input_sha256={n: hashlib.sha256((run/n).read_bytes()).hexdigest() for n in inputs},
                implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists(): raise ValueError('Use a new diagnostic output path')
    result = diagnose(args.run)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result['windows'], indent=2))
