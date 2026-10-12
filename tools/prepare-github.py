"""Inventory/export the files allowed by repository .gitignore rules.

Uses a temporary Git index, including before this workspace is a repository.
Does not stage, commit, publish, or delete anything in the source workspace.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def candidates():
    # A fresh Git directory avoids local excludes, tracked-file exceptions and
    # accidental dependence on the developer's current index or global ignores.
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    with tempfile.TemporaryDirectory(prefix='beamng-git-index-') as temp:
        git_dir = str(Path(temp) / 'index.git')
        subprocess.run(['git', 'init', '--bare', '--quiet', git_dir], check=True, env=env)
        result = subprocess.run(
            ['git', '--git-dir', git_dir, '--work-tree', str(ROOT),
             '-c', 'core.excludesFile=' + os.devnull,
             'ls-files', '--others', '--exclude-standard', '-z'],
            cwd=ROOT, env=env, check=True, capture_output=True)
    return sorted(p.decode('utf-8') for p in result.stdout.split(b'\0') if p)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Copy candidates into a new directory; never overwrites.')
    args = parser.parse_args()
    output = args.output.resolve() if args.output else None
    if output:
        if output.exists():
            parser.error('The output directory must not already exist.')
        if output.is_relative_to(ROOT) and not output.is_relative_to(ROOT / 'artifacts'):
            parser.error('Exports inside this workspace must be under ignored artifacts/.')
    records = []
    for name in candidates():
        path = ROOT / name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError('Review linked files before exporting: ' + name)
        data = path.read_bytes()
        records.append(dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
    manifest = ROOT / 'artifacts/github-manifest.json'
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(dict(files=records), indent=2) + '\n', encoding='utf-8')
    groups = Counter()
    for row in records:
        groups[row['path'].split('/')[0]] += row['bytes']
    print(f"{len(records)} candidate files; {sum(groups.values()) / 1024**2:.2f} MiB")
    for name, size in groups.most_common():
        print(f'  {name}: {size / 1024**2:.2f} MiB')
    print('Inventory: artifacts/github-manifest.json')
    if output:
        output.mkdir(parents=True)
        for row in records:
            destination = output / row['path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / row['path'], destination)
            if hashlib.sha256(destination.read_bytes()).hexdigest() != row['sha256']:
                raise RuntimeError('Source changed during export; retry into a new directory: ' + row['path'])
        print('Exported to: ' + str(output))


if __name__ == '__main__':
    main()
