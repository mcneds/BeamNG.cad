"""Benchmark one versus two cars in one owned Drive process; never qualifies builds.

Uses the unchanged production vehicle recorder and physics. Vehicle centers stay
in disjoint 40 m lane envelopes; all collisions stay enabled.
Solo controls use each lane's exact spawn position to expose parallel effects.
"""
import argparse
import copy
import csv
import hashlib
import importlib.util
from itertools import zip_longest
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('probe',HERE/'probe-drive-execution.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


class MultiSession(probe.ProbeSession):
    def command(self,**data):
        if data.get('action')=='run':
            job=data.pop('job')
            temporary=self.control/'multicar-job.tmp'
            probe.write_json(temporary,job)
            os.replace(temporary,self.control/'multicar-job.json')
            data.update(job_id=job['id'],job_file='/settings/vehicle_harness/multicar-job.json')
        super().command(**data)


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def recording_files(job):
    files=['vehicle.csv'];capture=job.get('frequency_capture')
    if capture:
        files.append('frequency.csv')
        for flag,name in [('velocities','frequency_velocities.csv'),('loads','frequency_loads.csv'),
                          ('wheels','frequency_wheels.csv'),('actuator_targets','frequency_targets.csv')]:
            if capture.get(flag):files.append(name)
    return files


def compare_csv(a,b,tolerance=1e-6):
    with Path(a).open(newline='') as x,Path(b).open(newline='') as y:
        left=csv.DictReader(x);right=csv.DictReader(y)
        if left.fieldnames!=right.fieldnames:raise ValueError('Telemetry columns changed')
        if not left.fieldnames:raise ValueError('Missing telemetry columns')
        maxima={k:0. for k in left.fieldnames};count=0;last=[-math.inf,-math.inf]
        clock='physics_s' if 'physics_s' in maxima else 't'
        for row,other in zip_longest(left,right):
            if row is None or other is None:raise ValueError('Unequal sample counts')
            count+=1
            for i,sample in enumerate((row,other)):
                now=float(sample[clock])
                if now<=last[i]:raise ValueError('Non-increasing telemetry clock')
                last[i]=now
            for k in maxima:
                v,w=float(row[k]),float(other[k])
                if not math.isfinite(v) or not math.isfinite(w):raise ValueError('Nonfinite telemetry')
                maxima[k]=max(maxima[k],abs(v-w))
        if not count:raise ValueError('Missing telemetry samples')
    return dict(samples=count,identical=sha(a)==sha(b),maximum_absolute_differences=maxima,
                tolerance=tolerance,within_tolerance=all(v<=tolerance for v in maxima.values()))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('recorded_job',type=Path,help='Existing reverse probe job.json; preserves exact capture settings')
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--profile',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    source=read(a.recorded_job)
    if source['scenario']!='reverse' or source['duration']!=18:raise ValueError('Only bounded 18 s reverse benchmark supported')
    original=read(a.recorded_job.parent/'probe.json')
    manifest,folder=probe.intake(a.manifest)
    if sha(a.manifest)!=original['manifest_sha256'] or source['manifest']!=manifest:
        raise ValueError('Recorded job is not bound to supplied manifest')
    before={str(f.relative_to(probe.HARNESS)):sha(f) for f in (probe.HARNESS/'frame_harness').rglob('*') if f.suffix in ('.py','.lua')}
    result=dict(qualification_status='not_qualified',manifest_sha256=sha(a.manifest),scenario='reverse',
                lane_x_m=[0,64],collisions='unchanged',implementation=before,batches=[],
                experiment_sha256={str(f.name):sha(f) for f in (Path(__file__),HERE/'multicar-probe-bridge.lua')})
    project=probe.HarnessProject(userpath=a.profile,source=folder,runs=a.output,startup_timeout=240)
    resources=[];stop=threading.Event();cancel=threading.Event();started=time.monotonic()
    import psutil
    with MultiSession(project,'vehicle',cancel=cancel) as session:
        session.mode='null';session.visible_for_evidence=False
        bridge=(HERE/'multicar-probe-bridge.lua').read_bytes()
        (session.root/'mods/unpacked/vehicle_harness/lua/ge/extensions/session_bridge.lua').write_bytes(bridge)
        (a.output/'diagnostic-session-bridge.lua').write_bytes(bridge)
        expected,changed,written=probe.stage_components(folder,
            session.root/'mods/unpacked/vehicle_harness/vehicles'/manifest['model'],manifest['model'],[],a.output)
        def monitor():
            low=None
            while not stop.is_set():
                row=dict(wall_s=time.monotonic()-started,available_ram_bytes=psutil.virtual_memory().available)
                if session.process:
                    try:
                        proc=psutil.Process(session.process.pid);members=[proc]+proc.children(recursive=True)
                        row['private_bytes']=sum(x.memory_info().private for x in members)
                    except (psutil.NoSuchProcess,psutil.AccessDenied):pass
                resources.append(row)
                if row['available_ram_bytes']<256*1024**2:
                    result['resource_abort']='Available RAM below 256 MiB';cancel.set()
                if row['available_ram_bytes']<384*1024**2:
                    low=low or time.monotonic()
                    if time.monotonic()-low>5:result['resource_abort']='Available RAM below 384 MiB for five seconds';cancel.set()
                else:low=None
                stop.wait(1)
        worker=threading.Thread(target=monitor,daemon=True);worker.start()
        try:
            for label,lanes in [('warmup',[0]),('solo0',[0]),('solo64',[64]),('paired',[0,64])]:
                session.retire();batch_run=a.output/label;batch_run.mkdir()
                batch_id='multi-'+uuid.uuid4().hex;output=session.control/'results'/batch_id;output.mkdir()
                children=[];archives=[]
                for lane in lanes:
                    child=copy.deepcopy(source);child_id=batch_id+'-lane'+str(lane)
                    child.update(id=child_id,session_id=session.id,lane_x=lane,output='/settings/vehicle_harness/results/'+child_id,
                                 expected_beams=expected,changed_files=[],staging_bytes=0)
                    child.pop('diagnostic',None)
                    directory=a.output/(label+'-lane'+str(lane));directory.mkdir()
                    native=session.control/'results'/child_id;native.mkdir()
                    probe.write_json(directory/'job.json',child);probe.write_json(directory/'build_manifest.json',manifest)
                    children.append(child);archives.append((native,directory))
                job=dict(id=batch_id,scenario='reverse',duration=18.,gravity=source['gravity'],
                    output='/settings/vehicle_harness/results/'+batch_id,children=children,
                    changed_files=changed if label=='warmup' else [])
                tick=time.monotonic();entry=dict(label=label,lanes=lanes)
                try:entry['completion']=session.execute(job,batch_run,output,capture=False)
                finally:
                    entry.update(wall_s=time.monotonic()-tick,timings=dict(session.last_timings))
                    session.archive_recording(output,batch_run,archive_root=a.output)
                    for native,directory in archives:session.archive_recording(native,directory,archive_root=a.output)
                    session.archive_logs(batch_run)
                    result['batches'].append(entry);probe.write_json(a.output/'benchmark.json',result)
                for _,directory in archives:
                    completion=read(directory/'completion.json');child=read(directory/'job.json')
                    if completion['job_id']!=child['id'] or completion['session_id']!=session.id or completion['status']!='completed':
                        raise ValueError('Missing/failed per-car completion')
                    if any(abs(pos[0]-child['lane_x'])>20 or abs(pos[1])>20 for pos in completion['final_node_positions'].values()):
                        raise ValueError('Final node outside isolation envelope')
                print(label,round(entry['wall_s'],2),'seconds',flush=True)
        except (Exception,KeyboardInterrupt) as exc:result['error']=str(exc) or type(exc).__name__
        finally:
            session.close_process();stop.set();worker.join()
    after={str(f.relative_to(probe.HARNESS)):sha(f) for f in (probe.HARNESS/'frame_harness').rglob('*') if f.suffix in ('.py','.lua')}
    result['sources_unchanged']=before==after and sha(a.manifest)==result['manifest_sha256']
    if not result.get('error'):
        comparisons={}
        for lane in [0,64]:
            one=a.output/(f'solo{lane}-lane{lane}');two=a.output/(f'paired-lane{lane}')
            comparisons[str(lane)]={name:compare_csv(one/name,two/name) for name in recording_files(source)}
        result['comparisons']=comparisons
        times={x['label']:x['wall_s'] for x in result['batches']}
        result['throughput_ratio']=(times['solo0']+times['solo64'])/times['paired']
        result['equivalent_at_tolerance']=all(r['within_tolerance'] for case in comparisons.values() for r in case.values())
        result['comparison_status']='matched' if result['equivalent_at_tolerance'] else 'different'
    probe.write_json(a.output/'resources.json',resources);probe.write_json(a.output/'benchmark.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('implementation','batches','comparisons')},indent=2),flush=True)
    if result.get('error') or not result['sources_unchanged']:raise SystemExit(1)
    if not result['equivalent_at_tolerance']:raise SystemExit(2)


if __name__=='__main__':main()
