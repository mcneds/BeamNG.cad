"""Explicit maintenance for superseded test telemetry; dry run unless --apply.

Keeps measured results, calibration artifacts, reports and captures. Removes raw
CSV/log recordings and per-run copies of source/build/vehicle/harness assets.
This does not mark failed or historical tests as qualified or replayable.
"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re


def prune(roots, before, audit, apply=False):
    audit=Path(audit).absolute()
    if audit.exists():raise ValueError('Use a fresh audit path')
    plans=[];seen=set()
    for value in roots:
        root=Path(value).absolute()
        if root.resolve()!=root or not root.is_dir():raise ValueError('Invalid or linked maintenance root')
        for base,dirs,files in os.walk(root,followlinks=False):
            folder=Path(base)
            if folder.resolve()!=folder:raise ValueError('Linked directory in maintenance root')
            if not re.match(r'^\d{8}T\d{6}-',folder.name) or folder.name[:8]>=before:continue
            dirs[:]=[]
            if folder in seen:continue
            seen.add(folder);removed=[]
            for childbase,childdirs,childfiles in os.walk(folder,followlinks=False):
                for name in childdirs+childfiles:
                    path=Path(childbase)/name
                    if path.resolve()!=path or not path.is_relative_to(root):raise ValueError('Unsafe recording path')
                for name in childfiles:
                    path=Path(childbase)/name;relative=path.relative_to(folder)
                    if (relative.parts[0] in ('build','source','vehicle','harness_source') or path.suffix in ('.csv','.log')
                            or path.name in ('motion_diagnostics.json','startup_powertrain.json','recorder_completion.json')):
                        removed.append(dict(path=str(path),bytes=path.stat().st_size,mtime_ns=path.stat().st_mtime_ns))
            if removed:plans.append((folder,removed))
    total=sum(p['bytes'] for _,items in plans for p in items)
    record=dict(applied=apply,created_utc=datetime.now(timezone.utc).isoformat(),before=before,
                roots=[str(Path(p).absolute()) for p in roots],bytes=total,runs=len(plans),
                removed=[p for _,items in plans for p in items])
    audit.write_text(json.dumps(record,indent=2),encoding='utf-8')
    if apply:
        for folder,items in plans:
            (folder/'raw-recording-pruned.json').write_text(json.dumps(dict(
                date=record['created_utc'],audit=str(audit),removed_bytes=sum(p['bytes'] for p in items),
                reason='Superseded development recording; raw replay data and per-run asset copies removed at user request. Original results are unchanged.'),indent=2),encoding='utf-8')
            for item in items:
                path=Path(item['path']);stat=path.stat()
                if path.resolve()!=path or stat.st_size!=item['bytes'] or stat.st_mtime_ns!=item['mtime_ns']:
                    raise ValueError('Recording changed after cleanup preflight')
                path.unlink()
            for base,dirs,files in os.walk(folder,topdown=False):
                path=Path(base)
                if path!=folder and not any(path.iterdir()):path.rmdir()
    return dict(applied=apply,runs=len(plans),bytes=total,audit=str(audit))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('roots',nargs='+',type=Path);p.add_argument('--before',required=True)
    p.add_argument('--audit',required=True,type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
    if not re.fullmatch(r'\d{8}',a.before):p.error('--before must be YYYYMMDD')
    print(json.dumps(prune(a.roots,a.before,a.audit,a.apply),indent=2))
