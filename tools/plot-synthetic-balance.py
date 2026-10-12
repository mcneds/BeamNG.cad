"""Plot recorded drift, preserving failures and separating diagnostic interventions."""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

p = argparse.ArgumentParser()
p.add_argument('artifacts', type=Path)
p.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'docs/images/mass-balance-diagnostic.png')
a = p.parse_args()
groups = [('s', 'Original CAD'), ('t', 'Caster revision'), ('u', 'Tire pretension'),
          ('v', 'Rear toe revision'), ('w', 'Balanced CAD\n+ caster')]
rows = []
for candidate, label in groups:
    directory = a.artifacts / ('variant-vehicle-' + candidate)
    for source in sorted((directory / 'tests').glob('*-acceleration/result.json')):
        result = json.loads(source.read_text(encoding='utf-8'))
        diagnostic = result.get('diagnostic')
        job = source.with_name('job.json')
        if job.exists():
            diagnostic = json.loads(job.read_text(encoding='utf-8')).get('diagnostic') or diagnostic
        # Diagnostic outcomes remain failures by design, even when their drift is low.
        if diagnostic:
            continue
        drift = result.get('metrics', {}).get('peak_uncommanded_lateral_m')
        if drift is None:
            continue
        rows.append(dict(group=label, drift_m=drift, status=result['status'],
                         source=str(source.relative_to(a.artifacts)),
                         sha256=hashlib.sha256(source.read_bytes()).hexdigest(), diagnostic=None))
for run, label in [('20261007T165259-1838ba-acceleration', 'Test-only\ncentered weight'),
                   ('20261007T165806-a03596-acceleration', 'Equal weight\nsymmetric control')]:
    source = a.artifacts / 'variant-vehicle-s/tests' / run / 'result.json'
    result = json.loads(source.read_text(encoding='utf-8'))
    rows.append(dict(group=label, drift_m=result['metrics']['peak_uncommanded_lateral_m'],
                     status=result['status'], source=str(source.relative_to(a.artifacts)),
                     sha256=hashlib.sha256(source.read_bytes()).hexdigest(), diagnostic=True))
labels = [label for _, label in groups] + ['Test-only\ncentered weight', 'Equal weight\nsymmetric control']
fig, ax = plt.subplots(figsize=(12, 5.6), layout='constrained')
fig.set_facecolor('#f5f8fa'); ax.set_facecolor('#ffffff')
for i, label in enumerate(labels):
    selected = [r for r in rows if r['group'] == label]
    for j, row in enumerate(selected):
        offset = (j - (len(selected) - 1) / 2) * .085
        color = '#8062ae' if row['diagnostic'] else '#248675' if row['status'] == 'passed' else '#c64f42'
        ax.scatter(i + offset, row['drift_m'], c=color, s=65,
                   marker='D' if row['diagnostic'] else 'o', zorder=3)
    ax.text(i, 2.21, f'n={len(selected)}', ha='center', color='#546672', fontsize=10)
ax.axhline(.5, color='#465b64', linestyle='--', linewidth=1.3)
ax.text(-.42, .54, 'Existing drift limit: 0.50 m', color='#465b64', fontsize=10)
ax.axvline(4.5, color='#c0c7ce', linewidth=1)
ax.set(xticks=range(len(labels)), xticklabels=labels, ylim=(0, 2.4),
       ylabel='Peak uncommanded lateral displacement (m)',
       title='Alternate suspension: recorded acceleration drift')
ax.grid(axis='y', alpha=.18)
ax.spines[['top', 'right']].set_visible(False)
fig.supxlabel('Normal CAD revisions at left; purple controls alter only the owned test copy and cannot qualify a vehicle.\n'
              'All available completed normal acceleration records for these revisions are included. No steering assist.', fontsize=10)
a.output.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(a.output, dpi=160)
a.output.with_suffix('.json').write_text(json.dumps(dict(
    scope='Synthetic functional drift comparison. Not tire/material validation or proof of unique causation.',
    normal_candidates=[x for x, _ in groups], recordings=rows), indent=2)+'\n', encoding='utf-8')
print(f'{len(rows)} recordings: {a.output}')
