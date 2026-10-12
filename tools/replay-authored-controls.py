"""Replay immutable archived packages in an isolated evidence directory."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('output', type=Path)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
archive = Path('H:/beamng project programs/builds/synthetic-mvp-20261007')
results = []
for name in ('primary-vehicle-bt', 'variant-vehicle-w'):
    source = archive / name
    target = a.output / name
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('tests', '__pycache__'))
    manifest_hash = hashlib.sha256((source / 'manifest.json').read_bytes()).hexdigest()
    command = [sys.executable, str(ROOT / 'tools/test-synthetic-vehicle.py'),
               str(target / 'manifest.json'), '--profile', 'H:/BeamNGCadHarness/joints-v41-drive']
    completed = subprocess.run(command, check=False)
    if hashlib.sha256((target / 'manifest.json').read_bytes()).hexdigest() != manifest_hash:
        raise ValueError('Control manifest changed')
    results.append(dict(source=str(source), output=str(target), manifest_sha256=manifest_hash,
                        returncode=completed.returncode))
    (a.output / 'controls.json').write_text(json.dumps(results, indent=2) + '\n')
raise SystemExit(0 if all(r['returncode'] == 0 for r in results) else 1)
