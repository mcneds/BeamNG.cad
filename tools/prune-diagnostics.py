"""Prune superseded BeamNG experiments, retaining sources and compact outcomes.

Dry run by default. A policy lists maintenance roots, protected builds/evidence,
settings and idle owned profiles. Nothing outside those roots is removed.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RAW_NAMES = {'motion_diagnostics.json', 'startup_diagnostics.json', 'startup_powertrain.json',
             'release_diagnostics.json', 'compiled.json', 'build_manifest.json', 'job.json',
             'frequency_analysis.json', 'motion_comparison.json', 'completion.json',
             'recorder_completion.json'}
SUMMARY_NAMES = {'result.json', 'metrics.json', 'probe.json', 'constraint_attribution.json',
                 'frequency-summary.json', 'completion-summary.json', 'motion-summary.json'}
INPUT_KEYS = {'GeometryDirectory', 'TemplateDefinitionPath', 'FrameBuildReceipt',
              'PhysicsBuildReceipt', 'PhysicsTemplateReceipt', 'LastBuildReceipt'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    path=Path(path);temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8');os.replace(temp,path)


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def linked(path):
    return path.is_symlink() or (os.name == 'nt' and bool(
        path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT))


def safe(path, root):
    path=Path(path).absolute();root=Path(root).absolute()
    if path==root or not path.is_relative_to(root) or path.resolve()!=path:
        raise ValueError('Unsafe maintenance path: '+str(path))
    current=path
    while current!=root:
        if current.exists() and linked(current):
            raise ValueError('Linked maintenance path: '+str(current))
        current=current.parent
    if root.resolve()!=root or linked(root):raise ValueError('Linked maintenance root')
    return path


def covered(path, protected):
    # Protected inputs are a set. Walk the short ancestor chain rather than
    # testing every protected CAD asset for every generated file.
    return path in protected or any(parent in protected for parent in path.parents)


def active_workers():
    import psutil
    found=[]
    tokens=('component_worker.py','calibration_worker.py','probe-drive-execution.py','test-synthetic-vehicle.py',
            'revise-wishbone-rigidity.py','revise-strain-damping.py','revise-monotone-rigidity.py','revise-angular-arms.py','revise-brake-reaction.py','revise-rigidity-mass.py','revise-wheel-support-mass.py','plan-rigidity-mass.py','screen-angular-arms.py','full_vehicle_worker.py','build_static_frame.py','prepare_frame.py',
            'probe-lbeam.py','probe-lbeam-force.py','probe-torsion-tangent.py','probe-filtered-damping.py','benchmark-drive-workers.py','plan-ballast-redistribution.py','frame_harness','vehicle_wizard')
    for process in psutil.process_iter(['pid','name','cmdline']):
        if process.pid==os.getpid():continue
        name=(process.info['name'] or '').lower();args=process.info['cmdline'] or []
        if name.startswith('beamng') or any(Path(a).name in tokens for a in args):found.append(process.pid)
    if found:raise RuntimeError('Active game/generation/test processes; retry after the batch: '+str(found))


def protections(policy):
    protected={Path(p).absolute() for p in policy.get('keep',[])};queue=[];seen=set();missing=[];references=[]
    for path in protected:
        if not path.exists():raise ValueError('Protected path missing: '+str(path))
        if path.is_dir() and (path/'project.snapshot.json').exists():queue.append(path/'project.snapshot.json')
    for name in policy.get('settings',[]):
        settings=Path(name);root=ET.parse(settings).getroot()
        for key in ('LastProjectPath','LastBuildReceipt','LastCalibrationGeneration'):
            value=root.findtext(key)
            if value:
                p=Path(value).absolute();protected.add(p.parent if p.name=='static_frame_build.json' else p)
                if p.is_file() and p.suffix=='.json':queue.append(p)
        selected=Path(str(settings)+'.projects.xml')
        if selected.exists():queue.extend(Path(e.get('path')) for e in ET.parse(selected).getroot().iter('Project'))
    def walk(data):
        if isinstance(data,dict):
            for key,value in data.items():
                if key in INPUT_KEYS and isinstance(value,str) and value:
                    p=Path(value).absolute();protected.add(p.parent if key.endswith('Receipt') else p)
                    references.append(p)
                    if p.is_file() and p.suffix=='.json':queue.append(p)
                elif isinstance(value,(dict,list)):walk(value)
        elif isinstance(data,list):
            for item in data:walk(item)
    while queue:
        p=queue.pop().absolute()
        if p in seen:continue
        seen.add(p);protected.add(p)
        if not p.exists():missing.append(str(p));continue
        walk(read(p))
    for p in references:
        if not p.exists():missing.append(str(p))
    return protected,sorted(set(missing)),references


def inventory(policy):
    protected,missing,references=protections(policy);roots=[Path(p).absolute() for p in policy['roots']]
    records=[];builds=[];skipped=[]
    for root in roots:
        if not root.is_dir() or root.resolve()!=root or root.parent==root:raise ValueError('Invalid maintenance root')
        for base,dirs,files in os.walk(root,followlinks=False):
            folder=Path(base)
            if covered(folder,protected):dirs[:]=[];continue
            for child in dirs[:]:
                p=folder/child
                if p.resolve()!=p or linked(p):
                    skipped.append(str(p));dirs.remove(child)
            # CAD inputs, rollback copies and provenance are never disposable.
            dirs[:]=[n for n in dirs if n not in ('geometry','provenance','source','__pycache__') and not n.startswith('runtime-')]
            if 'manifest.json' in files:
                try:m=read(folder/'manifest.json')
                except (ValueError,OSError):m={}
                if m.get('kind')=='exported_vehicle' and isinstance(m.get('files'),dict):
                    builds.append((root,folder,m))
            is_run=('probe.json' in files or 'job.json' in files or 'job-0.json' in files
                    or ('result.json' in files and ('compiled.json' in files or 'vehicle.csv' in files))
                    or bool(re.match(r'^\d{8}T\d{6}-',folder.name)))
            if is_run:
                candidates=[]
                for sub,subdirs,names in os.walk(folder,followlinks=False):
                    subdirs[:]=[n for n in subdirs if n not in ('geometry','provenance','source')
                                and not linked(Path(sub)/n) and not covered(Path(sub)/n,protected)]
                    for name in names:
                        p=Path(sub)/name;rel=p.relative_to(folder)
                        if covered(p,protected) or linked(p):continue
                        if p.suffix in ('.csv','.log') or name in RAW_NAMES or rel.parts[0] in ('build','vehicle','harness_source'):
                            safe(p,root);candidates.append(p)
                result={};assessment_status=None
                for name in ('result.json','completion.json','recorder_completion.json','probe.json'):
                    if (folder/name).exists():
                        try:
                            value=read(folder/name);result.update(value)
                            if name=='result.json':assessment_status=value.get('status')
                        except (ValueError,OSError):pass
                job={}
                if (folder/'job.json').exists():
                    try:job=read(folder/'job.json')
                    except (ValueError,OSError):pass
                # A completed recording can still have failed numerical checks.
                # Preserve its assessment when completion/probe metadata merges.
                status=assessment_status or result.get('status') or result.get('completion',{}).get('status') or 'unknown'
                if candidates:
                    records.append(dict(root=root,folder=folder,files=candidates,scenario=job.get('scenario','unknown'),
                        failed=status not in ('completed','passed','quick_passed'),mtime=folder.stat().st_mtime_ns))
                dirs[:]=[]
    # Keep one latest failure per scenario within the unpinned raw-data budget.
    retained=set();budget=int(policy.get('raw_budget_gib',10)*2**30);used=0;scenarios=set()
    if policy.get('retain_latest_failure',True):
        for run in sorted(records,key=lambda r:r['mtime'],reverse=True):
            size=sum(p.stat().st_size for p in run['files'])
            if run['failed'] and run['scenario'] not in scenarios and used+size<=budget:
                retained.add(run['folder']);used+=size;scenarios.add(run['scenario'])
    plans={};groups={}
    def add(path,root,group,kind,expected=None):
        path=safe(path,root)
        if covered(path,protected) or not path.is_file():return
        if path.suffix.lower() in ('.sldasm','.sldprt') or 'geometry' in path.relative_to(root).parts:return
        info=path.stat();plans[str(path)]=dict(path=str(path),root=str(root),group=str(group),kind=kind,
            bytes=info.st_size,mtime_ns=info.st_mtime_ns,sha256=expected)
        groups[str(group)]=kind
    for run in records:
        if run['folder'] not in retained:
            for p in run['files']:add(p,run['root'],run['folder'],'recording')
    for root,folder,m in builds:
        for name,hashed in m['files'].items():
            p=folder/name
            if not name.replace('\\','/').startswith('vehicles/'):raise ValueError('Unexpected generated asset: '+name)
            add(p,root,folder,'build',hashed)
        receipt=folder/'static_frame_build.json'
        if receipt.exists():
            r=read(receipt);name=r.get('zip_file','')
            if name and name.replace('\\','/').startswith('work/dist/'):
                add(folder/name,root,folder,'build',r.get('zip_sha256'))
    for value in policy.get('incomplete_builds',[]):
        folder=Path(value).absolute();root=next((r for r in roots if folder.is_relative_to(r)),None)
        if root is None:raise ValueError('Partial build outside roots')
        if not folder.exists():continue
        if (folder/'static_frame_build.json').exists():raise ValueError('Partial build has a completed receipt')
        for base,dirs,names in os.walk(folder,followlinks=False):
            dirs[:]=[n for n in dirs if n not in ('geometry','provenance','source')
                     and not linked(Path(base)/n) and not covered(Path(base)/n,protected)]
            for name in names:
                # The cleanup writes this marker before removing payloads. It
                # and retained outcomes must not become deletion candidates on
                # the next inventory of a partially generated build.
                if name not in SUMMARY_NAMES|{'diagnostics-pruned.json'}:
                    add(Path(base)/name,root,folder,'incomplete_build')
    return dict(files=list(plans.values()),groups=groups,protected=sorted(map(str,protected)),
        preexisting_missing_inputs=missing,references=[str(p) for p in references],
        retained_failure_runs=sorted(map(str,retained)),retained_failure_bytes=used,skipped_links=skipped)


def compact_summaries(folder):
    for source,target,transform in (
        ('frequency_analysis.json','frequency-summary.json',lambda d:{k:v for k,v in d.items() if k not in ('display_history','time_windows')}),
        ('motion_comparison.json','motion-summary.json',lambda d:{k:v for k,v in d.items() if k not in ('samples','history','time_series')}),
        ('completion.json','completion-summary.json',lambda d:{k:v for k,v in d.items() if k not in ('final_node_positions','final_relative_node_speeds')}),
        ('recorder_completion.json','completion-summary.json',lambda d:{k:v for k,v in d.items() if k not in ('final_node_positions','final_relative_node_speeds')})):
        if (folder/source).is_file():
            try:write(folder/target,transform(read(folder/source)))
            except ValueError:write(folder/target,dict(status='invalid_json',source=source,replay_available=False))


def apply(plan, audit, check_active=active_workers):
    check_active()
    # Check the entire plan before any deletion; repeat each check at unlink.
    def validate(item):
        p=safe(item['path'],item['root']);s=p.stat()
        if s.st_size!=item['bytes'] or s.st_mtime_ns!=item['mtime_ns']:raise ValueError('File changed since inventory: '+str(p))
        if item['sha256'] and digest(p)!=item['sha256']:raise ValueError('Generated asset differs from manifest: '+str(p))
        return p
    for index,item in enumerate(plan['files']):
        validate(item)
        if (index+1)%1000==0:print(f"Validated {index+1}/{len(plan['files'])} files",flush=True)
    removed=0;last=None
    journal=Path(str(audit)+'.deleted.jsonl')
    with journal.open('x',encoding='utf-8') as stream:
        for index,item in enumerate(plan['files']):
            group=Path(item['group'])
            if group!=last:
                check_active();compact_summaries(group)
                write(group/'diagnostics-pruned.json',dict(audit=str(audit),kind=item['kind'],replay_available=False,
                    note='Superseded diagnostics/assets pruned; original outcomes and qualification status unchanged.'))
                last=group
            p=validate(item);p.unlink();removed+=item['bytes']
            stream.write(json.dumps(dict(path=str(p),bytes=item['bytes']))+'\n');stream.flush()
            if (index+1)%1000==0:print(f"Pruned {index+1}/{len(plan['files'])} files; {removed/2**30:.2f} GiB logical",flush=True)
    return dict(removed_files=len(plan['files']),removed_logical_bytes=removed,journal=str(journal))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--policy',type=Path,required=True)
    parser.add_argument('--reviewed-audit',type=Path,help='Reuse a reviewed dry run; files and current protections are revalidated')
    parser.add_argument('--audit',type=Path,required=True);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    if args.audit.exists():raise ValueError('Use a fresh audit path')
    policy=read(args.policy);active_workers()
    sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
    from frame_harness.runner import exclusive_userpath
    from frame_harness.models import HarnessProject
    with ExitStack() as stack:
        for value in policy.get('profiles',[]):
            profile=Path(value)
            if not (profile/'.frame-harness-owned').is_file():raise ValueError('Not an owned harness profile')
            stack.enter_context(exclusive_userpath(HarnessProject(userpath=profile)))
        if args.reviewed_audit:
            plan=read(args.reviewed_audit)
            if plan['policy']!=policy:raise ValueError('Policy changed since reviewed inventory')
            protected,missing,references=protections(policy)
            if any(covered(Path(item['path']),protected) for item in plan['files']):
                raise ValueError('A planned deletion is now a protected input')
        else:plan=inventory(policy)
        plan.update(created_utc=datetime.now(timezone.utc).isoformat(),policy=policy)
        write(args.audit,plan)
        result=dict(applied=args.apply,files=len(plan['files']),logical_gib=sum(i['bytes'] for i in plan['files'])/2**30,
            groups=len(plan['groups']),audit=str(args.audit),retained_failure_runs=plan['retained_failure_runs'],
            preexisting_missing_inputs=plan['preexisting_missing_inputs'])
        if args.apply:result.update(apply(plan,args.audit))
        write(Path(str(args.audit)+'.summary.json'),result);print(json.dumps(result,indent=2))


if __name__=='__main__':main()
