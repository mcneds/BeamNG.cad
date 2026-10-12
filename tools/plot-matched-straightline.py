"""Audit and plot batches using the same constant-speed controller and distance window."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, nargs='+', required=True)
    parser.add_argument('--suspension', type=Path, required=True)
    parser.add_argument('--rack', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evidence = dict(qualified=False, deterministic_repeats=True,
        scope='Same controller and 18 s cruise origin; adaptive-clutch candidate is experimental',
        batches=[], vehicles={})
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout='constrained')
    colours = dict(candidate='#d95f02', utv='#1f77b4', covet='#2ca02c', wigeon='#9467bd')
    controller = None
    labelled = set()
    for path in args.batch:
        batch = json.loads(path.read_text())
        if not batch.get('sources_unchanged'):
            raise ValueError('Batch sources changed or incomplete: '+str(path))
        evidence['batches'].append(dict(path=str(path), sha256=sha(path)))
        for run in batch['runs']:
            root = Path(run['run'])
            metrics = run['metrics']
            cruise = metrics['cruise']
            job = json.loads((root/'job.json').read_text())
            settings = tuple(job[k] for k in ('target_speed', 'speed_kp', 'speed_ki', 'duration'))
            if controller is None:
                controller = settings
            if (settings != controller or run['measurement_status'] != 'valid' or
                    not cruise['speed_within_5_percent'] or metrics['peak_applied_steering'] != 0 or
                    metrics['maximum_broken_beams'] != 0 or '200' not in cruise['windows'] or
                    sha(root/'straight.csv') != metrics['telemetry_sha256']):
                raise ValueError('Unmatched or invalid diagnostic: '+str(root))
            with (root/'straight.csv').open() as stream:
                rows = [{k: float(v) for k, v in row.items()} for row in csv.DictReader(stream)]
            rows = [r for r in rows if r['t'] >= cruise['start_t']]
            base = rows[0]
            angle = base['heading_rad']
            x, y, speed = [], [], []
            for row in rows:
                dx = row['forward_distance']-base['forward_distance']
                dy = row['lateral_distance']-base['lateral_distance']
                distance = dx*math.cos(angle)+dy*math.sin(angle)
                if 0 <= distance <= 200:
                    x.append(distance)
                    y.append(-dx*math.sin(angle)+dy*math.cos(angle))
                    speed.append(row['speed']*3.6)
            label = run['label']
            axes[0, 0].plot(x, y, color=colours[label], alpha=.7,
                label=label if label not in labelled else None)
            axes[0, 1].plot(x, speed, color=colours[label], alpha=.7)
            labelled.add(label)
            evidence['vehicles'].setdefault(label, []).append(dict(run=str(root),
                telemetry_sha256=metrics['telemetry_sha256'], speed_rms_error=cruise['speed_rms_error'],
                drift_100_m=cruise['windows']['100']['lateral'],
                drift_200_m=cruise['windows']['200']['lateral']))
    evidence['controller'] = dict(zip(('target_speed', 'kp', 'ki', 'duration'), controller))
    for label, runs in evidence['vehicles'].items():
        if len(runs) != 3:
            raise ValueError('Expected three deterministic repeats for '+label)
    suspension = json.loads(args.suspension.read_text())
    rack = json.loads(args.rack.read_text())
    for axle, corners in dict(front=('FL', 'FR'), rear=('RL', 'RR')).items():
        samples = suspension['samples']
        for kind, style in (('actual', '-'), ('ideal', '--')):
            axes[1, 0].plot([s['t'] for s in samples],
                [sum(s['corners'][c][kind+'_toe_deg'] for c in corners)/2 for s in samples],
                linestyle=style, label=axle+' '+kind, linewidth=1)
    for corner in ('FL', 'FR'):
        samples = rack['samples']
        axes[1, 1].plot([s['t'] for s in samples],
            [s['endpoints'][corner]['guide_deformation_m'][2]*1000 for s in samples], label=corner)
    axes[0, 0].set(title='Drift from cruise heading', xlabel='Cruise distance (m)', ylabel='Lateral displacement (m)')
    axes[0, 1].set(title='Actual speed: every sample within 5%', xlabel='Cruise distance (m)', ylabel='Speed (km/h)')
    axes[0, 1].axhline(controller[0]*3.6, color='black', linestyle=':', linewidth=1)
    axes[1, 0].set(title='Candidate axle mean toe: measured versus CAD ideal', xlabel='Simulated time (s)', ylabel='Toe (degrees)')
    axes[1, 1].set(title='Candidate rack guide vertical deformation', xlabel='Simulated time (s)', ylabel='Displacement (mm)')
    for ax in axes.flat:
        ax.grid(alpha=.25)
    for ax in (axes[0, 0], axes[1, 0], axes[1, 1]):
        ax.legend(fontsize=8)
    fig.suptitle('Matched-speed diagnostics: three deterministic repeats; no qualification')
    evidence['attribution'] = dict(suspension=str(args.suspension), suspension_sha256=sha(args.suspension),
        rack=str(args.rack), rack_sha256=sha(args.rack), axle_means=suspension['axle_means'])
    evidence['implementation_sha256'] = sha(Path(__file__))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix('.json').write_text(json.dumps(evidence, indent=2)+'\n')
    fig.savefig(args.output.with_suffix('.png'), dpi=140)
    fig.savefig(args.output.with_suffix('.svg'))
    print(json.dumps(evidence['vehicles'], indent=2))


if __name__ == '__main__':
    main()
