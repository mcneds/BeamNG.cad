"""Compare recorded native torsion angles with the geometric dihedral model.

This checks the measured angle, not the native force law or integrator. Signed
angles may use the opposite convention; report both comparisons explicitly.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'beamng.cad/FramePipeline'),
               str(ROOT/'dependencies/cad-calibration/Test Harness')]
from frame_harness.build import node_table
from rigid_bracing import angle


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('run', type=Path)
args = parser.parse_args()
read = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
build = args.run.parent.parent
manifest = read(build/'manifest.json')
part = read(build/manifest['vehicle_directory']/manifest['main_jbeam'])[manifest['main_part']]
nodes = node_table(part)
bars = read(args.run/'compiled.json')['torsionbars']
samples = read(args.run/'motion_diagnostics.json')['samples']
result = []
for bar in bars:
    names = bar[:4]
    rest = angle(np.array([nodes[n]['position'] for n in names], dtype=float))
    measured = []
    for sample in samples:
        angles = sample.get('torsion_angles_rad')
        if angles is None:
            raise ValueError('Recording lacks native torsion angles; use the current recorder')
        actual = float(angles[str(bar[4]['cid'])])
        current = angle(np.array([sample['mechanism_positions'][n] for n in names]))
        delta = current-rest
        predicted = float(np.arctan2(np.sin(delta), np.cos(delta)))
        measured.append((predicted, actual))
    pairs = np.array(measured)
    error_same = float(np.max(np.abs(pairs[:, 0]-pairs[:, 1])))
    error_opposite = float(np.max(np.abs(pairs[:, 0]+pairs[:, 1])))
    denominator = float(pairs[:, 0]@pairs[:, 0])
    result.append(dict(nodes=names, cid=bar[4]['cid'],
                       peak_geometric_rad=float(np.max(np.abs(pairs[:, 0]))),
                       peak_native_rad=float(np.max(np.abs(pairs[:, 1]))),
                       peak_error_same_sign_rad=error_same,
                       peak_error_opposite_sign_rad=error_opposite,
                       native_per_geometric=float(pairs[:, 0]@pairs[:, 1]/denominator) if denominator>1e-14 else None))
result.sort(key=lambda v: min(v['peak_error_same_sign_rad'], v['peak_error_opposite_sign_rad']), reverse=True)
print(json.dumps(dict(run=str(args.run), torsion_count=len(result),
                     worst_sign_independent_error_rad=max((min(v['peak_error_same_sign_rad'],v['peak_error_opposite_sign_rad']) for v in result),default=0),
                     bars=result), indent=2))
