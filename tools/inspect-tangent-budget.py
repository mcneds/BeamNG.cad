"""Read-only rest/current-pose screening of the explicit native vehicle graph.

This excludes generated pressure-tire constraints, nonlinear stop engagement,
and geometric stiffness from prestress. It can expose a violated screen, but a
passing value cannot prove stability of the complete native simulation.
"""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'beamng.cad/FramePipeline'),
               str(ROOT/'dependencies/cad-calibration/Test Harness')]
from frame_harness.build import node_table
from rigid_bracing import budget_connections


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('run', type=Path)
parser.add_argument('--time', type=float, nargs='+', default=[4, 8, 12, 20, 29])
args = parser.parse_args()
read = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
build = args.run.parent.parent
manifest = read(build/'manifest.json')
part = read(build/manifest['vehicle_directory']/manifest['main_jbeam'])[manifest['main_part']]
motion = read(args.run/'motion_diagnostics.json')
if abs(motion['physics_dt_max']-.0005) > 1e-8:
    raise ValueError('This screening requires the recorded 0.5 ms physics step')
nodes = node_table(part)
baseline = budget_connections(part, nodes, [], limit=1e6)['final_step_eigenvalue']
samples = []
seen = set()
for time in args.time:
    sample = min(motion['samples'], key=lambda value: abs(value['t']-time))
    if sample['t'] in seen:
        continue
    seen.add(sample['t'])
    current = copy.deepcopy(nodes)
    positions = sample['mechanism_positions']
    if set(nodes)-set(positions):
        raise ValueError('Recording lacks complete explicit positions; rerun with the current recorder')
    for name, node in current.items():
        node['position'] = positions[name]
    value = budget_connections(part, current, [], limit=1e6)['final_step_eigenvalue']
    samples.append(dict(t=sample['t'], step_eigenvalue=value, fastest_node=sample.get('fastest_node'),
                        component_speed=sample['component_speed']))
print(json.dumps(dict(rest_step_eigenvalue=baseline,
                     declared_limit=manifest['connection_budget']['step_limit'],
                     samples=samples, limitations=__doc__.strip()), indent=2))
