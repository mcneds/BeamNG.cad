"""Compare unassisted drift, ideal toe and native tire loads; no handling fit."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read_run(folder):
    paths = {name: folder / name for name in ('motion_diagnostics.json', 'motion_comparison.json', 'build_manifest.json')}
    raw = json.loads(paths['motion_diagnostics.json'].read_bytes())['samples']
    motion = json.loads(paths['motion_comparison.json'].read_bytes())['samples']
    manifest = json.loads(paths['build_manifest.json'].read_bytes())
    if any(abs(s['steering_applied']) > 1e-8 for s in motion if s['t'] >= 4):
        raise ValueError('Drift diagnostic requires uncommanded steering')
    active = [s for s in raw if s['t'] >= 4]
    if not active:
        raise ValueError('Missing active telemetry')
    corners = ('FL', 'FR', 'RL', 'RR')
    loads = {c: np.array([s['wheel_torques'][c]['tire_shape']['down_force_n'] for s in active]) for c in corners}
    if any(not np.isfinite(v).all() for v in loads.values()):
        raise ValueError('Invalid native wheel loads')
    result = dict(run=str(folder), files={k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in paths.items()},
                  mean_load_n={c: float(v.mean()) for c, v in loads.items()},
                  captured_hub_height_m={c: manifest['template_definition']['hardpoints'][c]['hub'][2] for c in corners},
                  ride_reference={c: manifest['wheels'][c]['ride_reference'] for c in corners},
                  mean_abs_axle_torque_imbalance_nm={axle: float(np.mean([
                      abs(abs(s['wheel_torques'][axle+'L']['propulsion_torque']) -
                          abs(s['wheel_torques'][axle+'R']['propulsion_torque'])) for s in active])) for axle in ('F', 'R')})
    return motion, active, loads, result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('runs', nargs='+', type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.subplots_adjust(left=.08, right=.98, bottom=.08, top=.9, hspace=.35, wspace=.22)
    report = dict(scope=__doc__, qualification_changed=False, runs=[])
    for folder in a.runs:
        motion, active, loads, result = read_run(folder)
        label = folder.name.removeprefix('actual-cad-').removesuffix('-20261011')
        report['runs'].append(result)
        rows = [s for s in motion if s['t'] >= 4]
        t = np.array([s['t'] for s in rows])
        axes[0, 0].plot([s['forward_m'] for s in rows], [s['lateral_m'] for s in rows], label=label)
        axes[0, 1].plot(t, [s['yaw_deg']-rows[0]['yaw_deg'] for s in rows], label=label)
        # Mean axle toe is a steering bias, not the axle's toe-in magnitude.
        for axle, style in [('F', '-'), ('R', '--')]:
            axes[1, 0].plot(t, [np.mean([s['corners'][axle+c]['ideal_toe_deg'] for c in ('L', 'R')]) for s in rows],
                            linestyle=style, label=label+' '+axle)
            axes[1, 1].plot([s['t'] for s in active], loads[axle+'L']-loads[axle+'R'], linestyle=style, label=label+' '+axle)
    for ax, title, x, y in zip(axes.flat,
            ['Unassisted path', 'Heading change after launch', 'Ideal linkage mean axle toe', 'Native tire load: left minus right'],
            ['Forward displacement (m)', 'Time (s)', 'Time (s)', 'Time (s)'],
            ['Lateral displacement (m)', 'Degrees', 'Degrees', 'Newtons']):
        ax.set(title=title, xlabel=x, ylabel=y); ax.grid(alpha=.2); ax.legend(fontsize=7)
    fig.suptitle('Drift diagnosis: generated setup comparisons, unassisted steering')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.output, dpi=150, bbox_inches='tight'); plt.close(fig)
    a.output.with_suffix('.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(report['runs'], indent=2))


if __name__ == '__main__':
    main()
