"""Run the existing attachment checks with one owned Drive session across builds."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.models import HarnessProject
from frame_harness.session import DriveSession
from frame_harness.component_tests import SCENARIOS, SOURCE_HASHES, SOURCE_FILES, run_components, compact_success
from frame_harness.vehicle import intake
from frame_harness.build import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifests', nargs='+', type=Path)
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--startup-timeout', type=float, default=180.)
    parser.add_argument('--scenario', choices=tuple(SCENARIOS), help='Focused diagnostic; cannot qualify the full attachment sequence')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--mount-sites', action='store_true', help='Diagnostic only: apply force at mount sites instead of the whole panel')
    args = parser.parse_args()
    if args.repeats < 1: parser.error('Repeats must be positive')
    if args.mount_sites and args.scenario!='mount_load_release': parser.error('Mount-site diagnostic requires --scenario mount_load_release')
    if args.output.exists(): raise ValueError('Use a new report path')
    paths = [p.resolve() for p in args.manifests]
    manifests = [intake(p)[0] for p in paths]
    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    project = HarnessProject(userpath=args.profile, runs=paths[0].parent/'tests', startup_timeout=args.startup_timeout)
    report = dict(status='running', startup_timeout=args.startup_timeout, builds=[], diagnostic=bool(args.scenario) or args.repeats != 3,
                  scope='Production attachment checks on synthetic vehicles; real hardware strength unqualified')
    with DriveSession(project, 'vehicle') as session:
        for path, manifest, digest in zip(paths, manifests, hashes):
            session.project.runs = path.parent/'tests'
            breakable = [m for m in manifest['mounts'] if m['group']]
            scenarios = [s for s in SCENARIOS if s != 'rack_sweep' and
                         (s != 'mount_release' or breakable) and
                         (s != 'mount_load_release' or breakable and all(m.get('per_beam_strength_n', 0)>0 for m in breakable))]
            if args.scenario: scenarios = [args.scenario]
            record = dict(manifest=str(path), manifest_sha256=digest, required_runs=args.repeats*len(scenarios), runs=[])
            report['builds'].append(record)
            write_json(args.output, report)
            for repeat in range(args.repeats):
                for scenario in scenarios:
                    print(f'{path.parent.name}: attachment {len(record["runs"])+1}/{record["required_runs"]}: {scenario}', flush=True)
                    result = run_components(path, scenario, session, mount_load_application='mount_sites' if args.mount_sites else 'mass_distributed')
                    record['runs'].append(result)
                    write_json(args.output, report)
                    if result['status'] != 'passed': break
                if record['runs'][-1]['status'] != 'passed': break
            record['status'] = 'passed' if len(record['runs']) == record['required_runs'] and all(r['status']=='passed' for r in record['runs']) else 'failed'
            record['manifest_unchanged'] = hashlib.sha256(path.read_bytes()).hexdigest() == digest
            intake(path)
            if not record['manifest_unchanged']: record['status'] = 'failed'
            write_json(args.output, report)
    report['verifier_unchanged'] = SOURCE_HASHES == {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE_FILES}
    report['verifier_sha256'] = SOURCE_HASHES
    report['status'] = 'passed' if report['verifier_unchanged'] and all(b['status']=='passed' for b in report['builds']) else 'failed'
    write_json(args.output, report)
    # The owned process keeps its session log open until __exit__. Compact
    # only after shutdown, and preserve the result before optional cleanup.
    if not report['diagnostic']:
        for record in report['builds']:
            if record['status']=='passed':
                for run in record['runs']:compact_success(run['directory'])
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__': raise SystemExit(main())
