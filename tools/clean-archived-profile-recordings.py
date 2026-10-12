"""Remove only byte-verified duplicate recordings from an idle owned profile.

Dry run by default. Archives (including failed tests) are never modified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dependencies/cad-calibration/Test Harness'))
from frame_harness.models import HarnessProject
from frame_harness.runner import exclusive_userpath


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}


def clean(profile, archives, report, apply=False):
    profile=Path(profile).absolute();archives=Path(archives).absolute();report=Path(report).absolute()
    if profile.resolve()!=profile or archives.resolve()!=archives:
        raise ValueError('Linked cleanup roots are not supported')
    if not (profile/'.frame-harness-owned').is_file():raise ValueError('Not an owned profile')
    source=profile/'current/settings/vehicle_harness/results'
    if source.resolve()!=source or archives.is_relative_to(profile):raise ValueError('Unsafe cleanup roots')
    if report.exists():raise ValueError('Use a fresh audit report')
    result=dict(applied=apply,profile=str(profile),archives=str(archives),files=[],skipped=0,bytes=0)
    with exclusive_userpath(HarnessProject(userpath=profile)):
        index={}
        for status in archives.rglob('capture_status.json'):
            if status.resolve()!=status.absolute() or not status.is_file():continue
            data=read(status);key=(data.get('job_id'),data.get('session_id'))
            if all(key):index.setdefault(key,[]).append(status.parent)
        for folder in source.iterdir():
            if folder.resolve()!=folder.absolute() or not folder.is_dir():continue
            data=read(folder/'capture_status.json');key=(data.get('job_id'),data.get('session_id'))
            targets=index.get(key,[]) if data.get('job_id')==folder.name else []
            records=[(p,read(p/'compact-evidence.json')) for p in targets]
            for file in folder.iterdir():
                if file.resolve()!=file.absolute() or not file.is_file():continue
                hashed=digest(file);match=None
                for target,compact in records:
                    names=[file.name]+(['recorder_completion.json'] if file.name=='completion.json' else [])
                    for name in names:
                        archived=target/name
                        if archived.is_file() and archived.resolve()==archived.absolute() and digest(archived)==hashed:
                            match=dict(archive=str(archived),proof='identical_archived_file');break
                        if compact.get('discarded_sha256',{}).get(name)==hashed:
                            match=dict(archive=str(target/'compact-evidence.json'),proof='previously_compacted_hash');break
                    if match:break
                if not match:result['skipped']+=1;continue
                record=dict(source=str(file),sha256=hashed,bytes=file.stat().st_size,**match)
                # Persist the proof before each unlink; interrupted cleanup remains auditable.
                result['files'].append(record);result['bytes']+=record['bytes']
                if apply:
                    report.write_text(json.dumps(result,indent=2),encoding='utf-8')
                    if digest(file)!=hashed:raise ValueError('Recording changed during cleanup')
                    file.unlink()
            if apply and not any(folder.iterdir()):folder.rmdir()
        report.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return dict(applied=apply,files=len(result['files']),skipped=result['skipped'],bytes=result['bytes'],report=str(report))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('profile',type=Path);p.add_argument('archives',type=Path)
    p.add_argument('report',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
    print(json.dumps(clean(a.profile,a.archives,a.report,a.apply),indent=2))
