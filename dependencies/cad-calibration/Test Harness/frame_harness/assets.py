"""Shared immutable inputs and differential staging for one owned Drive batch."""
from pathlib import Path
import shutil
from .build import sha256, write_json


class BatchAssets:
    def __init__(self, root):
        self.root = Path(root).resolve()/'verification-assets'
        self.files = {}

    def capture(self, source):
        source = Path(source).resolve()
        # Recheck bytes, not just timestamp/size, before reuse.
        digest = sha256(source)
        destination = self.root/digest/source.name
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        if sha256(destination) != digest:
            raise ValueError('Shared verification input changed: '+str(destination))
        return destination, digest

    def snapshot(self, sources, receipt):
        records = {}
        for name, source in sources.items():
            target, digest = self.capture(source)
            records[name] = dict(path=str(target), sha256=digest)
        write_json(receipt, dict(version=1, files=records))
        return records


def stage_vehicle(source, destination, model='fh_mochi', assets=None):
    """Called only after retiring the entity inside the exclusively owned profile."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    wanted = {p.relative_to(source).as_posix(): p for p in source.rglob('*') if p.is_file()}
    for name, record in (assets or {}).items():
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Unsafe shared asset destination')
        path = Path(record['path'])
        if sha256(path) != record['sha256']:
            raise ValueError('Shared staged asset changed: '+name)
        wanted[name] = path
    changed = []; written = 0
    for old in destination.rglob('*'):
        if old.resolve() != old.absolute():
            raise ValueError('Linked vehicle staging path is not supported')
        if old.is_file() and old.relative_to(destination).as_posix() not in wanted:
            changed.append('/vehicles/'+model+'/'+old.relative_to(destination).as_posix()); old.unlink()
    for name, path in wanted.items():
        target = destination/name
        data = path.read_bytes()
        if name == 'base.pc':
            import json
            config = json.loads(data); config['model'] = model
            data = json.dumps(config, sort_keys=True).encode('utf-8')
        if target.is_file() and target.read_bytes() == data:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data); written += len(data)
        changed.append('/vehicles/'+model+'/'+name)
    return changed, written
