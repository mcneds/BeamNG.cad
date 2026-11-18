"""Summarize owned crash probes; optionally audit an observed positive tangent.

The tangent calculation excludes geometric prestress, nonlinear stops, filtered
damping and wheel L-beams. It is a diagnostic indicator, not a full native
integrator model or physical qualification.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import eigsh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dependencies/cad-calibration/Test Harness'))
from frame_harness.torsion import gradient


def tangent(compiled, snapshot=None):
    nodes = compiled['actual_nodes']
    count = max(n['cid'] for n in nodes.values()) + 1
    mass = np.zeros(count)
    points = np.zeros((count, 3))
    names = {}
    by_name = {}
    for name, node in nodes.items():
        i = node['cid']
        mass[i], points[i], names[i], by_name[name] = node['mass_kg'], node['position'], name, i
    broken = set()
    if snapshot:
        broken = {b['cid'] for b in snapshot.get('beams', []) if b['broken']}
        for key, node in snapshot['nodes'].items():
            points[int(key)] = node['p']
    if not np.isfinite(points).all() or not np.isfinite(mass).all() or np.any(mass <= 0):
        raise ValueError('Finite positions and positive masses for contiguous native node IDs required')
    rows, cols, values = [], [], []
    column = 0

    def add(ids, vectors, spring, damp):
        nonlocal column
        weight = np.sqrt(.0005**2 * spring + .001 * damp)
        for index, vector in zip(ids, vectors):
            for axis in range(3):
                rows.append(index * 3 + axis)
                cols.append(column)
                values.append(vector[axis] * weight / np.sqrt(mass[index]))
        column += 1

    for beam in compiled['beams']:
        if beam['cid'] in broken or beam['beam_type'] == 4:
            continue
        a, b = beam['a'], beam['b']
        direction = points[b] - points[a]
        length = np.linalg.norm(direction)
        if length < 1e-9:
            raise ValueError('Collapsed axial constraint')
        direction /= length
        damp = 0 if beam.get('damp_cutoff_hz', 0) else beam['damp']
        add([a, b], [-direction, direction], beam['spring'], damp)
    # Broken consecutive support beams also disable native angular constraints.
    broken_pairs = {frozenset((b['a'], b['b'])) for b in compiled['beams'] if b['cid'] in broken}
    for bar in compiled.get('torsionbars', []):
        ids = [by_name[n] for n in bar[:4]]
        if any(frozenset((a, b)) in broken_pairs for a, b in zip(ids, ids[1:])):
            continue
        add(ids, gradient(points[ids]), bar[4]['spring'], bar[4]['damp'])
    matrix = coo_matrix((values, (rows, cols)), shape=(count * 3, column)).tocsr()
    eig, vector = eigsh(matrix @ matrix.T, k=1, which='LA', tol=1e-7,
                        v0=np.random.default_rng(0).normal(size=count * 3))
    participation = np.sum(vector.reshape(count, 3)**2, axis=1)
    return dict(step_seconds=.0005, step_eigenvalue=float(eig[0]), theoretical_limit=4.,
                top_nodes=[dict(name=names[i], participation=float(participation[i]))
                           for i in np.argsort(participation)[-8:][::-1]], limitations=__doc__)


def summarize(run):
    job = json.loads((run / 'job.json').read_text())
    probe = json.loads((run / 'probe.json').read_text())
    result = dict(run=str(run), scenario=probe['scenario'], candidate=probe['candidate'],
                  sources_unchanged=probe.get('sources_unchanged'), qualification_status='not_qualified')
    if not (run / 'completion.json').exists():
        return result | dict(status='incomplete', error=probe.get('error', 'Missing completion'))
    completion = json.loads((run / 'completion.json').read_text())
    session = json.loads((run / 'session.json').read_text())
    if completion['job_id'] != job['id'] or completion['session_id'] != session['session_id']:
        raise ValueError('Recording identity mismatch')
    data = np.genfromtxt(run / 'disturbance.csv', delimiter=',', names=True)
    if data.size < 2 or any(not np.isfinite(data[name]).all() for name in data.dtype.names):
        raise ValueError('Missing or nonfinite disturbance telemetry')
    if np.any(np.diff(data['physics_s']) <= 0):
        raise ValueError('Nonmonotone physics timestamps')
    compiled = json.loads((run / 'compiled.json').read_text())
    names = {n['cid']: name for name, n in compiled['actual_nodes'].items()}
    index = int(np.argmax(data['max_node_speed']))
    result.update(status=completion['status'], reason=completion.get('reason'),
                  physics_end_s=float(data['physics_s'][-1]), peak_node_speed_m_s=float(data['max_node_speed'][index]),
                  peak_node=names[int(data['fastest_cid'][index])], maximum_broken_beams=int(max(data['broken'])),
                  excitation=job['excitation'])
    if (run / 'obstacle.json').exists():
        obstacle = json.loads((run / 'obstacle.json').read_text())
        if obstacle['job_id'] != job['id']:
            raise ValueError('Obstacle identity mismatch')
        result['obstacle'] = obstacle
    log = (run / 'beamng.log').read_text(errors='replace') if (run / 'beamng.log').exists() else ''
    result['native_instability_messages'] = [line for line in log.splitlines() if 'Instability detected' in line]
    # Completion alone is deliberately not called a pass: a damaged or floppy
    # candidate can finish without an explosion and still be physically wrong.
    result['runaway_detected'] = (result['peak_node_speed_m_s'] > 1000 or bool(result['native_instability_messages'])
                                  or completion.get('reason') in ('Physics instability', 'Nonfinite node velocity',
                                                                  'Nonfinite or unstable telemetry'))
    vehicle = np.atleast_1d(np.genfromtxt(run / 'vehicle.csv', delimiter=',', names=True))
    if vehicle.size:
        result['final_up_z'] = float(vehicle['up_z'][-1])
        result['final_relative_node_speed_m_s'] = float(vehicle['relative_node_speed'][-1])
        result['final_forward_distance_m'] = float(vehicle['forward_distance'][-1])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--tangent', action='store_true')
    args = parser.parse_args()
    result = []
    for run in args.runs:
        item = summarize(run)
        if args.tangent and (run / 'compiled.json').exists():
            compiled = json.loads((run / 'compiled.json').read_text())
            item['undeformed_tangent'] = tangent(compiled)
            item['onset_tangents'] = []
            for file in sorted(run.glob('onset-*.json')):
                snapshot = json.loads(file.read_text())
                item['onset_tangents'].append(dict(snapshot=file.name, physics_s=snapshot['physics_s'],
                                                   **tangent(compiled, snapshot)))
        result.append(item)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    for item in result:
        print(item['scenario'], item['candidate'], item['status'], item.get('peak_node_speed_m_s'), item.get('reason'))


if __name__ == '__main__':
    main()
