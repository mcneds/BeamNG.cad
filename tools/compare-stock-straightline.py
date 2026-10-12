"""Matched stock/candidate straight-line diagnostic. Does not qualify or install builds."""
import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.models import HarnessProject
from frame_harness.build import write_json
from frame_harness.vehicle import intake
from frame_harness.component_tests import stage_components

spec = importlib.util.spec_from_file_location('probe', ROOT/'tools/probe-drive-execution.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
STOCK = {'utv': ('base.pc', 2), 'covet': ('15le_A.pc', 2), 'wigeon': ('base_4w.pc', 1)}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rack_motion(run, manifest):
    """Derive rack diagnostics from captured nodes and native hydro endpoints."""
    contract=manifest['steering_contract']
    names=set(manifest['chassis_nodes'])|set(contract['housing_nodes'])|{'FL_tie_inner','FR_tie_inner'}
    names.update(n for pair in contract['rail_nodes'].values() for n in pair)
    names.update(contract['actuator_nodes'])
    compiled=json.loads((run/'compiled.json').read_text())
    ids={node['id']:node['name'] for node in compiled['nodes'] if node.get('name')}
    samples=[]
    for line in (run/'motion.jsonl').read_text().splitlines():
        row=json.loads(line);positions=dict(row.get('reference_positions',{}))
        for hydro in row['hydros']:
            for endpoint in ('a','b'):
                name=ids.get(hydro[endpoint])
                if name in names:positions[name]=hydro[endpoint+'_world']
        if not names.issubset(positions) or abs(row['steering_applied'])>1e-9:
            raise ValueError('Incomplete rack node capture or nonzero applied steering')
        samples.append(dict(t=row['t'],reference_positions={n:positions[n] for n in names},rack_target_m=0))
    return dict(qualified=False,
        scope='Straight-line diagnostic; target is commanded centred rack, not measured actuator travel',
        samples=samples)


def analyze(run):
    completion = json.loads((run/'completion.json').read_text())
    if completion['status'] != 'completed':
        raise ValueError(str(completion))
    with (run/'straight.csv').open() as stream:
        rows = [{k: float(v) for k, v in r.items()} for r in csv.DictReader(stream)]
    if len(rows) < 490 or not all(math.isfinite(v) for r in rows for v in r.values()):
        raise ValueError('Incomplete or nonfinite telemetry')
    if any(b['t'] <= a['t'] for a, b in zip(rows, rows[1:])):
        raise ValueError('Nonmonotonic time')
    if abs(completion['physics_dt_min']-.0005)>1e-8 or abs(completion['physics_dt_max']-.0005)>1e-8:
        raise ValueError('Unexpected physics timestep')
    if rows[-1]['t']<24.99:
        raise ValueError('Recording ended early')
    base = min(rows, key=lambda r: abs(r['t']-4))
    moving = [r.copy() for r in rows if r['t'] >= base['t']]
    angle = base['heading_rad']
    for r in moving:
        x = r['forward_distance']-base['forward_distance']
        y = r['lateral_distance']-base['lateral_distance']
        r['settled_forward_m'] = x*math.cos(angle)+y*math.sin(angle)
        r['settled_lateral_m'] = -x*math.sin(angle)+y*math.cos(angle)
        r['heading_change_deg'] = math.degrees(r['heading_rad']-angle)
    windows = {}
    for distance in (10, 25, 50, 100, 200):
        for a, b in zip(moving, moving[1:]):
            if a['settled_forward_m'] <= distance <= b['settled_forward_m'] and b['settled_forward_m'] > a['settled_forward_m']:
                f=(distance-a['settled_forward_m'])/(b['settled_forward_m']-a['settled_forward_m'])
                windows[str(distance)]={key:a[key]+f*(b[key]-a[key]) for key in
                    ('t','speed','lateral_distance','settled_lateral_m','heading_change_deg')}
                break
    result = dict(samples=len(rows),duration_s=rows[-1]['t'],physics_dt_s=completion['physics_dt_min'],
        telemetry_sha256=sha(run/'straight.csv'),raw_peak_lateral_m=max(abs(r['lateral_distance']) for r in rows),
        settled_peak_lateral_m=max(abs(r['settled_lateral_m']) for r in moving),
        final_forward_m=moving[-1]['settled_forward_m'],final_speed_m_s=rows[-1]['speed'],
        final_heading_change_deg=moving[-1]['heading_change_deg'],
        peak_applied_steering=max(abs(r['steering_applied']) for r in rows),
        maximum_broken_beams=max(r['broken'] for r in rows),settled_start=base,distance_windows=windows)
    job_path=run/'job.json'
    job=json.loads(job_path.read_text()) if job_path.exists() else {}
    target=job.get('target_speed')
    if target:
        start_t=4+target+4
        steady=[r for r in rows if r['t']>=start_t]
        if len(steady)<200:raise ValueError('Insufficient constant-speed samples')
        origin=steady[0];angle=origin['heading_rad'];points=[]
        for r in steady:
            x=r['forward_distance']-origin['forward_distance'];y=r['lateral_distance']-origin['lateral_distance']
            points.append(dict(distance=x*math.cos(angle)+y*math.sin(angle),
                lateral=-x*math.sin(angle)+y*math.cos(angle),speed=r['speed'],t=r['t'],
                heading_change_deg=math.degrees(r['heading_rad']-angle)))
        cruise=dict(start_t=origin['t'],target_speed_m_s=target,
            speed_min=min(r['speed'] for r in steady),speed_max=max(r['speed'] for r in steady),
            speed_rms_error=math.sqrt(sum((r['speed']-target)**2 for r in steady)/len(steady)),
            maximum_broken_beams=max(r['broken'] for r in steady),windows={})
        for distance in (50,100,200):
            for a,b in zip(points,points[1:]):
                if a['distance']<=distance<=b['distance'] and b['distance']>a['distance']:
                    f=(distance-a['distance'])/(b['distance']-a['distance'])
                    cruise['windows'][str(distance)]={k:a[k]+f*(b[k]-a[k]) for k in
                        ('lateral','speed','t','heading_change_deg')}
                    break
        cruise['speed_within_5_percent']=all(abs(r['speed']-target)<=target*.05 for r in steady)
        result['cruise']=cruise
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--profile',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--models',nargs='+',choices=[*STOCK,'candidate'],default=[*STOCK,'candidate'])
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--coast-at',type=float)
    p.add_argument('--spawn-yaw',type=int,choices=(0,90,180,270),default=0,help='Diagnostic world-heading control; rotate the complete unchanged vehicle')
    p.add_argument('--target-speed',type=float,help='Shared speed controller and 1 m/s^2 ramp; m/s')
    p.add_argument('--speed-kp',type=float,default=.5)
    p.add_argument('--speed-ki',type=float,default=.2)
    p.add_argument('--fixed-cvt-ratio',type=float,help='Diagnostic ratio override after the speed ramp; never qualifies')
    p.add_argument('--fixed-cvt-after',type=float,default=14)
    p.add_argument('--native-clutch-defaults',action='store_true',help='Diagnostic native inertia-based clutch defaults; ignores candidate recoil bound and never qualifies')
    p.add_argument('--adaptive-clutch',action='store_true',help='Diagnostic passive compliance at actual CVT gearing, retaining the recoil bound')
    p.add_argument('--capture-rack-motion',action='store_true',help='Candidate chassis/rack node traces for compliance attribution; diagnostic only')
    a=p.parse_args()
    if a.fixed_cvt_ratio is not None and (a.models!=['candidate'] or not .8<=a.fixed_cvt_ratio<=3):
        p.error('Fixed CVT diagnostic requires only the candidate and a ratio within its existing range [.8,3]')
    if a.native_clutch_defaults and a.models!=['candidate']:
        p.error('Native clutch override requires only the candidate')
    if a.adaptive_clutch and (a.models!=['candidate'] or a.native_clutch_defaults):
        p.error('Adaptive compliance requires only the candidate and cannot combine with native-default override')
    if a.capture_rack_motion and a.models!=['candidate']:
        p.error('Rack motion capture requires only the candidate')
    a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    manifest,folder=intake(a.candidate)
    project=HarnessProject(userpath=a.profile,source=folder,runs=a.output,startup_timeout=240)
    sources=[Path(__file__),ROOT/'tools/straightline_recorder.lua',ROOT/'tools/probe-drive-execution.py']
    hashes={str(path):sha(path) for path in sources}
    report=dict(purpose=__doc__,qualified=False,implementation=hashes,candidate=str(a.candidate),
                candidate_sha256=sha(a.candidate),runs=[])
    for path in sources:
        (a.output/path.name).write_bytes(path.read_bytes())
    write_json(a.output/'comparison.json',report)
    with probe.ProbeSession(project,'vehicle') as session:
        session.mode='null'
        mod=session.root/'mods/unpacked/vehicle_harness/lua'
        recorder=ROOT/'tools/straightline_recorder.lua'
        (mod/'vehicle/extensions/vehicleharness/recorder.lua').write_bytes(recorder.read_bytes())
        bridge=mod/'ge/extensions/session_bridge.lua'
        source=bridge.read_text(encoding='utf-8')
        anchor="be:setEnabled(true);be:setSimulationTimeScale(1);status('spawning')"
        if source.count(anchor)!=1:raise ValueError('Deterministic hook changed')
        source=source.replace(anchor,'be:setPhysicsDeterministic(true);'+anchor)
        if a.spawn_yaw:
            rotation='rot=quat(0,0,0,1)'
            if source.count(rotation)!=1:raise ValueError('Spawn rotation hook changed')
            z,w={90:(math.sqrt(.5),math.sqrt(.5)),180:(1.,0.),270:(math.sqrt(.5),-math.sqrt(.5))}[a.spawn_yaw]
            source=source.replace(rotation,f'rot=quat(0,0,{z!r},{w!r})')
        bridge.write_text(source,encoding='utf-8')
        (a.output/'session_bridge.lua').write_text(source,encoding='utf-8')
        (a.output/'recorder.lua').write_bytes(recorder.read_bytes())
        (mod/'ge/extensions/visuals.lua').write_text(
            'return {new=function() local function noop() end; return {camera=noop,capture=noop,draw=noop,update=noop,dispose=noop} end}',encoding='utf-8')
        for label in a.models:
            if label!='candidate':
                archive=project.game/'content/vehicles'/(label+'.zip')
                with ZipFile(archive) as z:
                    data=z.read('vehicles/'+label+'/'+STOCK[label][0])
                    (a.output/(label+'-config.pc')).write_bytes(data)
                report.setdefault('stock_archives',{})[label]=dict(path=str(archive),size=archive.stat().st_size,
                    mtime_ns=archive.stat().st_mtime_ns,config_sha256=hashlib.sha256(data).hexdigest())
            for repeat in range(1,a.repeats+1):
                session.retire()
                run=a.output/(label+'-'+str(repeat));run.mkdir()
                changed=[]
                if label=='candidate':
                    model=manifest['model'];config=manifest['config'];spawn=manifest['spawn_z'];gear=2
                    _,changed,_=stage_components(folder,session.root/'mods/unpacked/vehicle_harness/vehicles'/model,model,[],run)
                else:model=label;config,gear=STOCK[label];spawn=1.0
                if a.target_speed and label=='wigeon':gear=2
                identity='straight-'+uuid.uuid4().hex
                output=session.control/'results'/identity;output.mkdir(parents=True)
                job=dict(id=identity,model=model,config=config,gear_index=gear,duration=45 if a.target_speed else 25,
                    scenario='stock_straightline_diagnostic',gravity=-9.81,spawn_z=spawn,
                    output='/settings/vehicle_harness/results/'+identity,changed_files=changed,
                    coast_at=a.coast_at,target_speed=a.target_speed,speed_kp=a.speed_kp,speed_ki=a.speed_ki,
                    fixed_cvt_ratio=a.fixed_cvt_ratio,fixed_cvt_after=a.fixed_cvt_after)
                job['spawn_yaw_degrees']=a.spawn_yaw
                job['native_clutch_defaults']=a.native_clutch_defaults
                if a.capture_rack_motion:
                    contract=manifest['steering_contract']
                    names=set(manifest['chassis_nodes'])|set(contract['housing_nodes'])|{'FL_tie_inner','FR_tie_inner'}
                    names.update(n for pair in contract['rail_nodes'].values() for n in pair)
                    names.update(contract['actuator_nodes'])
                    job['capture_node_names']=sorted(names)
                    write_json(run/'build_manifest.json',manifest)
                if a.adaptive_clutch:
                    part=json.loads((folder/manifest['main_jbeam']).read_text())[manifest['main_part']]
                    job['adaptive_clutch']=manifest['device_contract']['clutch_coupling']|dict(
                        engine_inertia_kg_m2=part['mainEngine']['inertia'],rear_reduction=manifest['device_contract']['rear_total_reduction'])
                write_json(run/'job.json',job)
                record=dict(label=label,repeat=repeat,run=str(run));start=time.monotonic()
                print(label,repeat,flush=True)
                try:
                    completion=session.execute(job,run,output,capture=False)
                    record['completion_status']=completion['status']
                except BaseException as error:
                    record['error']=str(error) or type(error).__name__
                    session.close_process()
                    raise
                finally:
                    record['wall_s']=time.monotonic()-start
                    session.archive_recording(output,run,archive_root=a.output)
                    session.archive_logs(run)
                    report['runs'].append(record)
                    write_json(a.output/'comparison.json',report)
                try:
                    record['metrics']=analyze(run)
                    if a.capture_rack_motion:
                        write_json(run/'motion_diagnostics.json',rack_motion(run,manifest))
                    record['measurement_status']='valid'
                except ValueError as error:
                    record['measurement_status']='invalid_measurement'
                    record['analysis_error']=str(error)
                    report['sources_unchanged']=hashes=={str(path):sha(path) for path in sources} and report['candidate_sha256']==sha(a.candidate)
                    write_json(a.output/'comparison.json',report)
                    raise
                write_json(a.output/'comparison.json',report)
                print(json.dumps(record['metrics']),flush=True)
    report['sources_unchanged']=hashes=={str(path):sha(path) for path in sources} and report['candidate_sha256']==sha(a.candidate)
    write_json(a.output/'comparison.json',report)


if __name__=='__main__':main()
