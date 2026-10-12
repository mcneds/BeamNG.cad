"""Discard optional successful-run diagnostics; never weaken qualification checks."""
import json
from pathlib import Path
from .build import sha256, write_json


def compact_recording_failure(run):
    marker=run/'compact-evidence.json'
    if not marker.exists():return None
    try:
        record=json.loads(marker.read_text())
        if record.get('version')!=1 or not record.get('recording_validated'):
            return 'Invalid compact recording receipt'
        if not {'result.json','metrics.json','telemetry_location.json'}<=record.get('retained_sha256',{}).keys():
            return 'Incomplete compact recording receipt'
        for name,expected in record['retained_sha256'].items():
            path=run/name
            if not path.resolve().is_relative_to(run.resolve()) or sha256(path)!=expected:
                return 'Compact recording evidence changed: '+name
    except (OSError,ValueError,KeyError):return 'Compact recording evidence missing or unreadable'
    return None


def apply_retention(job, state, keep=False, *, quick=None):
    job=Path(job).resolve(); study=job/'study'
    summary_name='build-result.json'
    if quick is not None:
        state=state|dict(status='completed' if quick['status']=='quick_passed' else quick['status'],runs=quick['runs'],acceptance={})
        summary_name='quick-result.json'
    # A pending visual review is not a crash. Keep its actual images for review.
    failed=(state.get('status') not in ('offline_complete','completed','completed_with_limitations')
            or any(not r.get('offline_accepted') for r in state.get('candidates',{}).values())
            or any(r.get('status')!='completed' for r in state.get('runs',[]))
            or any(any(reason!='Rendered mesh review missing or stale' for reason in a.get('reasons',[]))
                   for a in state.get('acceptance',{}).values()))
    result=dict(status=state.get('status'),full_report_saved=bool(keep or failed),
                retention_reason='requested' if keep else 'failure' if failed else 'successful diagnostics discarded',
                candidates={name:dict(offline_accepted=r.get('offline_accepted'),mass=r.get('mass'),
                                     qualification=state.get('acceptance',{}).get(name))
                            for name,r in state.get('candidates',{}).items()},
                recording_count=len(state.get('runs',[])),freed_bytes=0)
    if quick is not None:result.update(status=quick['status'],qualification_status='not_qualified',reasons=quick.get('reasons',[]))
    write_json(study/summary_name,result)
    if keep or failed:
        if failed:
            from .report import create_report, telemetry_cache
            from .damage import damage_report
            for record in state.get('runs',[]):
                run=Path(record['path'])
                if run.resolve().parent!=job/'tests':raise ValueError('Report path outside generation')
                if (run/'report.html').exists() or (run/'compact-evidence.json').exists():continue
                metrics=None
                try:
                    metrics=json.loads((run/'metrics.json').read_text())
                    with telemetry_cache():create_report(run);damage_report(run)
                except Exception as error:
                    (run/'report-error.log').write_text(str(error))
                finally:
                    # Optional rendering must not replace the validated, combined measurements.
                    if metrics is not None:write_json(run/'metrics.json',metrics)
        return result
    from .runner import saved_recording_failure
    plans=[]
    for record in state.get('runs',[]):
        run=Path(record['path']).resolve()
        if run.parent!=job/'tests':raise ValueError('Refusing cleanup outside this generation: '+str(run))
        if saved_recording_failure(run):raise ValueError('Invalid recording; retain all diagnostics: '+str(run))
        if (run/'compact-evidence.json').exists():continue
        location=json.loads((run/'telemetry_location.json').read_text())['directory']
        directory=run/location
        if directory.resolve().parent!=run:raise ValueError('Unsafe telemetry location')
        completion=json.loads((directory/'completion.json').read_text())
        if completion.get('status')!='completed':raise ValueError('Incomplete recording; retain diagnostics')
        preserve_captures='mesh-cut' in record['key'] or '-damage-' in record['key']
        remove=[]
        for path in run.rglob('*'):
            if path.resolve()!=path.absolute():raise ValueError('Refusing linked diagnostic path: '+str(path))
            if not path.is_file():continue
            relative=path.relative_to(run)
            if (relative.parts[0] in ('source','build','vehicle','harness_source') or
                path.suffix in ('.csv','.html','.log') or (path.suffix=='.png' and not preserve_captures)):
                remove.append(path)
        plans.append((run,remove))
    # Verify every path before any removal. Required inputs/artifacts live outside tests/.
    for run,remove in plans:
        removed=set(remove)
        kept={p.relative_to(run).as_posix():sha256(p) for p in run.rglob('*') if p.is_file() and p not in removed and p.name!='compact-evidence.json'}
        write_json(run/'compact-evidence.json',dict(version=1,recording_validated=True,retained_sha256=kept,
            note='Raw telemetry and duplicate build assets discarded after validated measurements. Full replay requires rerunning.'))
        for path in remove:
            result['freed_bytes']+=path.stat().st_size;path.unlink()
        for path in sorted((p for p in run.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):
            if not any(path.iterdir()):path.rmdir()
    # Keep the compact result, calibration artifacts and review evidence, not HTML reports.
    for path in ([] if quick is not None else study.glob('*.html')):
        result['freed_bytes']+=path.stat().st_size;path.unlink()
    write_json(study/summary_name,result)
    return result
