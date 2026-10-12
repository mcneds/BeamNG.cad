"""Owned-session tests for component-only exports; no fabricated wheel data."""
from __future__ import annotations
from datetime import datetime,timezone
import csv
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid
import numpy as np
from .build import beam_table, write_json
from .models import HarnessProject
from .runner import read_json, check_recording_space
from .session import DriveSession
from .capture import usable_capture
from .vehicle import intake,rendered_meshes_loaded

SCENARIOS={'component_settle':15.,'component_load':12.,'mount_release':12.,'mount_load_release':14.,'rack_sweep':16.}
SOURCE_FILES=(Path(__file__),Path(__file__).parent/'session.py',Path(__file__).parent/'capture.py',Path(__file__).parent/'assets.py',*(Path(__file__).parent/'lua'/name for name in ('component_recorder.lua','vehicle_bridge.lua','vehicle_recorder.lua','session_bridge.lua','visuals.lua')))
SOURCE_HASHES={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE_FILES}


def analyze(run,manifest,scenario,completion):
    result={'status':'failed','recording_status':completion.get('status','incomplete'),'scenario':scenario,'directory':str(run),'checks':{},'metrics':{}}
    if completion.get('status')!='completed':return result|{'reason':completion.get('reason','Recording incomplete'),
        'telemetry_failure':completion.get('telemetry_failure')}
    with (run/'component.csv').open() as f:rows=list(csv.DictReader(f))
    if len(rows)!=completion.get('samples') or len(rows)<10:return result|{'reason':'Incomplete telemetry'}
    data={k:np.array([float(r[k]) for r in rows]) for k in rows[0]};t=data['t']
    if any(not np.isfinite(v).all() for v in data.values()) or np.any(np.diff(t)<=0) or t[-1]<SCENARIOS[scenario]-.05:
        return result|{'reason':'Invalid telemetry or early completion'}
    compiled=read_json(run/'compiled.json') or {};checks=result['checks'];metrics=result['metrics']
    if manifest.get('component_meshes'):checks['rendered_component_meshes_loaded']=rendered_meshes_loaded(run,manifest,completion)
    checks['compiled_mass']=abs(compiled.get('mass_kg',0)-manifest['expected_dry_mass_kg'])<max(.01,manifest['expected_dry_mass_kg']*.005)
    expected_nodes=len(manifest['nodes'])
    if manifest.get('allows_generated_wheel_graph'):
        for name,wheel in manifest.get('wheels',{}).items():
            contract=wheel.get('tire_contract',{});actual=compiled.get('generated_wheels',{}).get(name,{})
            checks[name+'_generated_wheel_graph']=bool(contract) and all(actual.get(k)==contract.get(k) for k in ('wheel_section','hub_nodes','tread_nodes'))
            expected_nodes+=contract.get('hub_nodes',0)+contract.get('tread_nodes',0)
    checks['compiled_nodes']=compiled.get('node_count')==expected_nodes
    for name,expected in manifest.get('required_controllers',{}).items():
        actual=compiled.get('controllers',{}).get(name,{})
        checks['controller_'+name]=name in compiled.get('controllers',{}) and all(actual.get(k)==value for k,value in expected.items())
    checks['internal_structure_intact']=max(data['internal_broken'])==0
    for label in ('first_mount','release','final'):
        checks['capture_'+label]=usable_capture(run/(label+'.png'))
    metrics['maximum_relative_speed']=float(max(data['relative_speed']))
    metrics['final_displacement_m']=float(data['maximum_component_displacement'][-1])
    if scenario=='mount_release':
        events=(read_json(run/'mount_events.json') or {}).get('events',{})
        first=events.get('first',{}).get('mounts',{});released=events.get('release',{}).get('mounts',{})
        seen=set();first_groups=set()
        for mount in manifest['mounts']:
            if mount['group'] and mount['child'] not in seen:first_groups.add(mount['group']);seen.add(mount['child'])
        expected_first={m['id'] for m in manifest['mounts'] if m['group'] in first_groups}
        checks['independent_mount_failure']=bool(expected_first) and all(
            first.get(m['id'],{}).get('broken')==(len(m['edges']) if m['id'] in expected_first else 0) for m in manifest['mounts'])
        checks['all_breakable_mounts_release']=all(released.get(m['id'],{}).get('broken')==(len(m['edges']) if m['group'] else 0) for m in manifest['mounts'])
        supported={manifest['nodes'][n]['component'] for n in manifest['chassis_nodes']}
        while True:
            expanded=supported|{v for m in manifest['mounts'] if not m['group'] and (m['parent'] in supported or m['child'] in supported) for v in (m['parent'],m['child'])}
            if expanded==supported:break
            supported=expanded
        detachable={m['child'] for m in manifest['mounts'] if m['group']}-supported
        for child in detachable:
            key='displacement_'+child
            metrics['final_displacement_'+child]=float(data[key][-1]) if key in data else None
        checks['every_detached_part_moves']=all(metrics['final_displacement_'+c] is not None and metrics['final_displacement_'+c]>.05 for c in detachable)
        metrics['detachable_components']=sorted(detachable)
    elif scenario=='mount_load_release':
        checks['release_travel_guard']=completion.get('travel_guard')=='detached_translation_removed_v1' and 'maximum_guarded_displacement' in data and max(data['maximum_guarded_displacement'])<=100
        metrics['maximum_guarded_displacement_m']=float(max(data['maximum_guarded_displacement'])) if 'maximum_guarded_displacement' in data else None
        record=read_json(run/'mount_events.json') or {};events=record.get('events',{}).get('natural',[])
        checks['natural_recording_identity']=record.get('job_id')==completion.get('job_id') and bool(record.get('job_id'))
        checks['force_induced_failure']=bool(events) and all(3<=e.get('time',0)<=SCENARIOS[scenario] and
            np.isfinite(e.get('applied_force_n',np.nan)) and e['applied_force_n']>0 for e in events)
        final=events[-1].get('mounts',{}) if events else {}
        checks['all_breakable_mounts_release']=all(final.get(m['id'],{}).get('broken')==(len(m['edges']) if m['group'] else 0) for m in manifest['mounts'])
        metrics['first_recorded_failure_force_n']=events[0].get('applied_force_n') if events else None
        metrics['failure_events']=len(events)
        result['qualification_scope']='Generated connector failure under a force ramp; thresholds are not calibrated physical bolt strengths.'
    else:
        checks['no_broken_mounts']=max(data['broken'])==0
        tail=t>t[-1]-2;metrics['settled_relative_speed']=float(np.percentile(data['relative_speed'][tail],95))
        checks['settled']=metrics['settled_relative_speed']<.15
        if scenario=='component_load':checks['bounded_displacement']=max(data['maximum_component_displacement'])<.15
        if scenario=='rack_sweep':
            record=read_json(run/'rack_motion.json') or {};rack=record.get('samples',[]);native=read_json(run/'rack_compiled.json') or {}
            checks['rack_recording_complete']=bool(completion.get('job_id')) and record.get('job_id')==completion['job_id'] and len(rack)==len(rows)
            checks['native_rails_loaded']=native.get('job_id')==completion.get('job_id') and native.get('rails')==3 and native.get('slidenodes')==3
            contract=manifest['steering_contract']
            if 'actuators' in contract:
                from .vehicle_motion import rack_actuator_target
                pairs=lambda rows:sorted(tuple(sorted(row)) for row in rows)
                expected=[a['nodes'] for a in contract['actuators']]
                checks['native_actuators_loaded']=bool(expected) and pairs(native.get('actuators',[]))==pairs(expected)
                try:
                    for sample in rack:
                        rack_actuator_target(dict(rack_target_m=sample.get('target_m'),rack_targets_m=sample.get('targets_m',[])),contract,contract['half_travel_m'])
                    checks['rack_targets_agree']=bool(rack)
                except ValueError:checks['rack_targets_agree']=False
            array=np.array([[s.get(k,np.nan) for k in ('t','target_m','shift_m','error_m','housing_error_m')] for s in rack])
            checks['rack_telemetry_finite']=bool(rack) and np.isfinite(array).all()
            if checks['rack_telemetry_finite'] and checks['rack_recording_complete']:
                travel=manifest['steering_contract']['half_travel_m']
                metrics.update(rack_error_m=float(max(array[:,3])),housing_error_m=float(max(array[:,4])),rack_range_m=float(np.ptp(array[:,2])))
                checks['rack_tracks_actuator']=metrics['rack_error_m']<.002
                checks['housing_stays_mounted']=metrics['housing_error_m']<.001
                checks['rack_moves_both_directions']=min(array[:,2])<-.8*travel and max(array[:,2])>.8*travel
    result['checks']={k:bool(v) for k,v in checks.items()}
    result['status']='passed' if all(checks.values()) else 'failed'
    result['reason']=None if result['status']=='passed' else ', '.join(k for k,v in checks.items() if not v)
    return result


def stage_components(source,vehicle,model,fixed,run,diagnostic=None):
    if diagnostic not in (None,'no_aero','no_self_collision','balance_ballast','symmetric_ballast','no_internal_static'):raise ValueError('Unknown diagnostic intervention')
    from .assets import stage_vehicle
    expected=[];overrides={};ballast=None;ballast_applied=0
    if diagnostic in ('balance_ballast','symmetric_ballast'):
        from .vehicle_diagnostics import balance_ballast
        ballast=balance_ballast(read_json(Path(run)/'build_manifest.json'),symmetric=diagnostic=='symmetric_ballast')
    # Construct final fixture JBeams outside the watched game tree. Updating
    # unchanged DAE/material files can queue a reload after recording starts.
    with tempfile.TemporaryDirectory(prefix='fixture-',dir=run) as temporary:
        for file in source.glob('*.jbeam'):
            parts=read_json(file)
            for part in parts.values():
                if diagnostic=='no_internal_static':
                    defaults={}
                    for row in part.get('nodes',[])[1:]:
                        if isinstance(row,dict):defaults.update(row);continue
                        options=defaults|(row[-1] if isinstance(row[-1],dict) else {})
                        if options.get('collision',True) is False:
                            if not isinstance(row[-1],dict):row.append({})
                            row[-1]['staticCollision']=False
                for row in part.get('nodes',[])[1:]:
                    if ballast and isinstance(row,list):
                        for weight in ballast['weights']:
                            if row[0]==weight['node']:
                                if not isinstance(row[-1],dict):row.append({})
                                row[-1]['nodeWeight']=weight['expected_node_mass_kg'];ballast_applied+=1
                    if isinstance(row,list) and row[0] in fixed:
                        if not isinstance(row[-1],dict):row.append({})
                        row[-1]['fixed']=True
                expected.extend(beam_table(part))
                if diagnostic=='no_self_collision':
                    # Owned test copy only. Keep terrain collision, tire
                    # pressure and all material properties unchanged.
                    for row in part.get('nodes',[])[1:]:
                        if isinstance(row,list):
                            if not isinstance(row[-1],dict):row.append({})
                            row[-1]['selfCollision']=False
                if diagnostic=='no_aero':
                    # Owned test copy only. Explicit row values override any
                    # section defaults; pressure and collision remain enabled.
                    for section in ('triangles','pressureWheels'):
                        for row in part.get(section,[])[1:]:
                            if isinstance(row,list):
                                if not isinstance(row[-1],dict):row.append({})
                                # Native zero-aero noncollidable tire triangles
                                # lose their pressure group. Retain negligible
                                # positive tire drag and verify pressure normally.
                                row[-1].update(dragCoef=1e-6 if section=='pressureWheels' else 0,liftCoef=0,skinDragCoef=0)
            path=Path(temporary)/file.name;write_json(path,parts)
            overrides[file.name]={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        if ballast:
            if ballast_applied!=len(ballast['weights']):raise ValueError('Diagnostic counterweight node is missing or duplicated')
            write_json(Path(run)/'diagnostic-ballast.json',ballast)
        changed,written=stage_vehicle(source,vehicle,model,overrides)
    return expected,changed,written


def run_components(manifest_path,scenario,session,gearbox_mode='neutral',mount_load_application='mass_distributed'):
    if scenario not in SCENARIOS:raise ValueError('Unknown component test')
    if gearbox_mode not in ('neutral','park'):raise ValueError('Unsupported fixture gearbox mode')
    if mount_load_application not in ('mass_distributed','mount_sites'):raise ValueError('Unknown mount load application')
    if mount_load_application!='mass_distributed' and scenario!='mount_load_release':raise ValueError('Mount-site diagnostic requires force release')
    path=Path(manifest_path).resolve();manifest,source=intake(path)
    if 'mounts' not in manifest.get('capabilities',[]):raise ValueError('This build does not declare component mounting capabilities')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+scenario+'-'+uuid.uuid4().hex[:6]
    run=path.parent/'tests'/stamp;run.mkdir(parents=True)
    session.retire();root=session.root;check_recording_space(root,run)
    mod=root/'mods/unpacked/vehicle_harness';vehicle=mod/'vehicles'/manifest['model']
    if not vehicle.resolve().is_relative_to(mod.resolve()):raise ValueError('Unsafe staging directory')
    fixed=manifest['chassis_nodes'] if scenario!='component_settle' else []
    expected,changed,written=stage_components(source,vehicle,manifest['model'],fixed,run)
    write_json(run/'staging.json',dict(changed_files=changed,written_bytes=written))
    output=session.control/'results'/stamp;output.mkdir(parents=True)
    job={'id':stamp,'session_id':session.id,'model':manifest['model'],'config':manifest['config'],'duration':SCENARIOS[scenario],
         'scenario':scenario,'gravity':-9.81 if scenario=='component_settle' else 0,'spawn_z':manifest['spawn_z'],
         'fixture_fixed_nodes':fixed,'expected_beams':expected,'manifest':manifest,'fixture_gearbox_mode':gearbox_mode,
         'output':'/settings/vehicle_harness/results/'+stamp,
         'changed_files':changed,'mount_load_application':mount_load_application,'travel_guard':'detached_translation_removed_v1'}
    write_json(run/'job.json',job);write_json(run/'build_manifest.json',manifest)
    completion={}
    try:completion=session.execute(job,run,output)
    except KeyboardInterrupt:
        completion={'status':'cancelled','reason':'Test cancelled'};session.close_process()
    except Exception as error:completion={'status':'failed','reason':str(error)};session.close_process()
    finally:
        session.archive_recording(output,run)
        session.archive_logs(run)
    if completion.get('status')=='completed' and (completion.get('job_id')!=stamp or completion.get('session_id')!=session.id):
        completion={'status':'failed','reason':'Recording identity mismatch'}
    if (run/'completion.json').is_file():shutil.copy2(run/'completion.json',run/'recorder_completion.json')
    write_json(run/'completion.json',completion)
    try:result=analyze(run,manifest,scenario,completion)
    except Exception as error:result={'status':'failed','scenario':scenario,'directory':str(run),'reason':str(error)}
    result['fixture_gearbox_mode']=gearbox_mode
    result['mount_load_application']=mount_load_application
    if mount_load_application!='mass_distributed':
        result['qualification_status']='diagnostic_only'
        result['qualification_scope']='Force applied at mount sites; cannot qualify distributed loading of the component'
    write_json(run/'result.json',result)
    print(result['status']+': '+str(result.get('reason') or scenario),flush=True)
    return result


def compact_success(run):
    """Retain measurements and images; optional raw/duplicate diagnostics go."""
    run=Path(run).resolve();remove=[];retained={};discarded={}
    previous=run/'compact-evidence.json'
    if previous.is_file():discarded.update(json.loads(previous.read_text(encoding='utf-8')).get('discarded_sha256',{}))
    for path in run.iterdir():
        if path.resolve()!=path.absolute():raise ValueError('Refusing linked diagnostic path')
        if not path.is_file():continue
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if path.suffix in ('.csv','.log') or path.name in ('job.json','build_manifest.json','motion_diagnostics.json','startup_powertrain.json','release_diagnostics.json','recorder_completion.json'):
            discarded[path.name]=digest;remove.append(path)
        elif path.name!='compact-evidence.json':retained[path.name]=digest
    locked=[]
    for path in remove:
        try:path.unlink()
        except PermissionError:
            # Optional storage cleanup must not invalidate completed evidence.
            # Keep the file and its hash when Windows still holds a handle.
            retained[path.name]=discarded.pop(path.name);locked.append(path.name)
    if (run/'report.html').is_file() and 'vehicle.csv' in discarded:
        from .vehicle_report import write_report
        write_report(run,json.loads((run/'result.json').read_text(encoding='utf-8')))
        retained['report.html']=hashlib.sha256((run/'report.html').read_bytes()).hexdigest()
    write_json(run/'compact-evidence.json',dict(version=1,retained_sha256=retained,discarded_sha256=discarded,
        retained_locked=locked,
        reason='Successful measurements validated; keep full reports to retain raw replay diagnostics.'))


def verify(manifest_path,game,profile,repeats=3,save_report=False):
    path=Path(manifest_path).resolve();project=HarnessProject(game=Path(game),userpath=Path(profile),runs=path.parent/'tests')
    manifest,_=intake(path)
    breakable=[m for m in manifest['mounts'] if m['group']]
    scenarios=[s for s in SCENARIOS if s!='rack_sweep' and (s!='mount_release' or breakable) and
               (s!='mount_load_release' or breakable and all(m.get('per_beam_strength_n',0)>0 for m in breakable))]
    results=[]
    owned=DriveSession(project,'vehicle');owned.visible_for_evidence=True
    with owned as session:
        for repeat in range(repeats):
            for scenario in scenarios:
                print(f'Component verification {len(results)+1}/{repeats*len(scenarios)}: {scenario}',flush=True)
                from .progress import emit
                emit('Test batch',completed=len(results),total=repeats*len(scenarios),detail=f'{len(results)+1}/{repeats*len(scenarios)}: {scenario}')
                result=run_components(path,scenario,session);results.append(result)
                write_json(path.parent/'component-verification.json',{'status':'running','results':results,'manifest_sha256':__import__('hashlib').sha256(path.read_bytes()).hexdigest()})
                if result['status']!='passed':break
            if results[-1]['status']!='passed':break
    passed=len(results)==repeats*len(scenarios) and all(r['status']=='passed' for r in results)
    unchanged=SOURCE_HASHES=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE_FILES}
    passed=passed and unchanged
    result={'status':'passed' if passed else 'failed','results':results,'repeats':repeats,
            'recording_status':'completed' if len(results)==repeats*len(scenarios) and all(r.get('recording_status')=='completed' for r in results) else 'incomplete',
            'qualification_status':'mounting_verified' if passed and repeats>=3 else 'screening_passed' if passed else 'not_qualified',
            'full_report_saved':save_report or not passed,
            'manifest_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'verifier_sha256':SOURCE_HASHES,'verifier_unchanged':unchanged,
            'scope':'Mounting/stability scenarios; real panel stiffness and material rupture unqualified'}
    if passed and not save_report:
        for record in results:compact_success(record['directory'])
    write_json(path.parent/'component-verification.json',result);return result
