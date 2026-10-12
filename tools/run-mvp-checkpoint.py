"""Fresh synthetic MVP builds and native qualification checks, without installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--primary-project', type=Path, required=True)
    parser.add_argument('--variant-project', type=Path, required=True)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--game', type=Path, default=Path('D:/SteamLibrary/steamapps/common/BeamNG.drive'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    environment = os.environ | {'OPENBLAS_NUM_THREADS': '1', 'PYTHONUNBUFFERED': '1',
        'PYTHONPATH': os.pathsep.join(str(ROOT/'dependencies/cad-calibration'/name)
                                   for name in ('Test Harness', 'Vehicle Wizard'))}
    report = dict(status='running', scope='Synthetic native-mate MVP fixtures; not the user vehicle',
                  profile=str(args.profile), runs=[], projects={})
    report_path = args.output/'checkpoint.json'

    def save():
        temporary = report_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        temporary.replace(report_path)

    def execute(label, argv):
        log = args.output/(label+'.log')
        print('START '+label, flush=True)
        start = time.monotonic()
        with log.open('w', encoding='utf-8') as stream:
            code = subprocess.call([sys.executable, *map(str, argv)], cwd=ROOT,
                                   env=environment, stdout=stream, stderr=subprocess.STDOUT)
        report['runs'].append(dict(label=label, exit_code=code, wall_s=time.monotonic()-start,
                                   log=str(log), command=[sys.executable, *map(str, argv)]))
        save()
        print('END '+label+' exit='+str(code), flush=True)
        return code == 0

    worker = ROOT/'beamng.cad/FramePipeline/component_worker.py'
    save()
    for name, source in [('primary', args.primary_project), ('variant', args.variant_project)]:
        raw = source.read_bytes()
        snapshot = args.output/(name+'-input.json')
        snapshot.write_bytes(raw)
        report['projects'][name] = dict(source=str(source), sha256=hashlib.sha256(raw).hexdigest())
        build = args.output/name
        if not execute(name+'-generate', [worker, 'vehicle', '--project', snapshot, '--output', build]):
            continue
        manifest = build/'manifest.json'
        execute(name+'-acceptance', [ROOT/'tools/test-synthetic-vehicle.py', manifest,
                                   '--scenario', 'acceptance', '--profile', args.profile, '--game', args.game])
        # Attachment behavior is independently useful even when driving fails.
        execute(name+'-mounts', [worker, 'verify', '--mounts-only', '--manifest', manifest,
                               '--game', args.game, '--profile', args.profile, '--repeats', '3'])
    report['sources_unchanged'] = all(hashlib.sha256(Path(value['source']).read_bytes()).hexdigest() == value['sha256']
                                    for value in report['projects'].values())
    report['status'] = 'passed' if len(report['runs']) == 6 and all(r['exit_code'] == 0 for r in report['runs']) and report['sources_unchanged'] else 'failed'
    save()
    print('MVP_CHECKPOINT '+report['status'], flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
