"""Generic completed-vehicle intake. Independent of the legacy frame calibration runner."""
from __future__ import annotations
from datetime import datetime,timezone
import contextlib
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
import numpy as np
from .build import sha256,write_json
from .capture import usable_capture
from .models import HarnessProject
from .runner import exclusive_userpath,prepare_userpath,read_json,check_recording_space

SCENARIOS={'settle':30.,'supported':18.,'articulation':24.,'acceleration':25.,'braking':30.,'reverse':18.,'left_turn':22.,'right_turn':22.}
# Appearance diagnostics are deliberately outside the driving acceptance schedule.
DIAGNOSTIC_SCENARIOS={'steering_visual':44.}


def finite_completion(completion):
    """Keep raw recorder evidence separately; never serialize or qualify NaNs."""
    try:json.dumps(completion,allow_nan=False)
    except (ValueError,TypeError):
        return dict(status='failed',reason='Recorder returned nonfinite or invalid completion data',
                    job_id=completion.get('job_id'),raw_evidence='recorder_completion.json')
    return completion


def intake(path):
    path=Path(path).resolve();m=read_json(path)
    if not m or m.get('kind')!='exported_vehicle' or m.get('version')!=1:raise ValueError('Expected an exported-vehicle manifest')
    import re
    if not re.fullmatch('[a-z][a-z0-9_]{1,45}',m['model']):raise ValueError('Invalid model ID')
    folder=(path.parent/m['vehicle_directory']).resolve()
    if not folder.is_relative_to(path.parent) or not folder.is_dir():raise ValueError('Vehicle directory outside build')
    if Path(m['config']).name!=m['config']:raise ValueError('Invalid config path')
    for name,digest in m['files'].items():
        file=(path.parent/name).resolve()
        if not file.is_relative_to(folder) or not file.is_file() or sha256(file)!=digest:raise ValueError('Build content differs: '+name)
    if not m['nodes'] or m.get('fixed_nodes'):raise ValueError('Exported vehicle must have a nonempty, unpinned graph')
    if not (folder/m['config']).is_file():raise ValueError('Missing default configuration')
    return m,folder


def rendered_meshes_loaded(directory,manifest,completion):
    evidence=read_json(Path(directory)/'render_meshes.json') or {}
    names=[name for group in manifest.get('component_meshes',{}).values() for name in group]
    counts=evidence.get('vertices',{})
    props=evidence.get('props',{})
    rigid={name for binding in manifest.get('coilover_render',{}).values() for kind in ('housing','shaft') for name in binding['meshes'][kind]}
    return bool(names and completion.get('job_id') and evidence.get('job_id')==completion['job_id'] and evidence.get('success') and
                all(props.get(name) is True if name in rigid else
                    props.get(name) is True or isinstance(counts.get(name),(int,float)) and counts[name]>0 for name in names))


def steering_compiled(contract,actual):
    """Compare engine-compiled locators/actuator, not just the exported JBeam."""
    rails=contract.get('rail_nodes',{});sliders=contract.get('rail_sliders',{})
    # Driveline sliding members can coexist with the steering rack. Their
    # native rails are audited independently against the driveline contract.
    actual=dict(actual,rails={k:v for k,v in actual.get('rails',{}).items() if not k.startswith('driveline_')},
                sliders={k:v for k,v in actual.get('sliders',{}).items() if not k.startswith('driveline_')})
    # A hydro acts on endpoint distance. The compiled beam can reverse id1/id2
    # without changing its identity; still require every declared pair once.
    hydros=actual.get('hydros',[])
    endpoints=[a.get('nodes',[]) for a in contract['actuators']] if 'actuators' in contract else [contract.get('actuator_nodes',[])]
    pairs=lambda rows: sorted(tuple(sorted(row)) for row in rows)
    return bool(rails and sliders and
                endpoints and all(len(row)==2 and len(set(row))==2 for row in endpoints+hydros) and
                len(set(pairs(endpoints)))==len(endpoints) and pairs(hydros)==pairs(endpoints) and
                set(actual.get('rails',{}))==set(rails) and
                set(actual.get('sliders',{}))==set(sliders) and
                all(actual['rails'][name].get('nodes')==nodes and actual['rails'][name].get('capped') is True for name,nodes in rails.items()) and
                all(actual['sliders'][name]==dict(rail=rail,attached=True,fixed=True) for name,rail in sliders.items()))


def analyze(directory,manifest,scenario,completion):
    path=Path(directory)/'vehicle.csv';result={'status':'failed','recording_status':completion.get('status','incomplete'),'qualification_status':'not_qualified','scenario':scenario,'directory':str(directory),'metrics':{},'checks':{},'reason':completion.get('reason')}
    from .vehicle_assessment import assess
    result['assessment']=assess(result)
    if completion.get('status')!='completed':return result
    with path.open(encoding='utf-8') as stream:rows=list(csv.DictReader(stream))
    if len(rows)<10 or len(rows)!=completion.get('samples'):result['reason']='Incomplete telemetry';return result
    data={k:np.array([float(row[k]) for row in rows]) for k in rows[0]};t=data['t'];metrics=result['metrics'];checks=result['checks']
    if not all(np.isfinite(v).all() for v in data.values()):result['reason']='Nonfinite telemetry';return result
    if t[-1]<(SCENARIOS|DIAGNOSTIC_SCENARIOS)[scenario]-.15 or np.any(np.diff(t)<=0):result['reason']='Recording ended early or timestamps are not increasing';return result
    metrics.update(peak_speed_kmh=float(max(data['speed'])*3.6),broken_beams=int(max(data['broken'])),peak_relative_node_speed_m_s=float(max(data['relative_node_speed'])))
    if scenario in ('supported','articulation'):
        clearance=completion.get('fixture_minimum_clearance_m')
        metrics['fixture_minimum_clearance_m']=clearance
        checks['suspended_tires_clear_ground']=isinstance(clearance,(int,float)) and np.isfinite(clearance) and clearance>=.25
    checks['no_broken_beams']=metrics['broken_beams']==0
    checks['capture_saved']=usable_capture(Path(directory)/'final.png')
    if manifest.get('component_meshes'):checks['rendered_component_meshes_loaded']=rendered_meshes_loaded(directory,manifest,completion)
    metadata=read_json(Path(directory)/'compiled.json') or {};mass=metadata.get('mass_kg',0)
    diagnostic=metadata.get('diagnostic') or (read_json(Path(directory)/'job.json') or {}).get('diagnostic')
    if diagnostic:
        result['diagnostic']=diagnostic
        checks['qualification_without_diagnostic_intervention']=False
    if diagnostic in ('balance_ballast','symmetric_ballast'):
        intervention=read_json(Path(directory)/'diagnostic-ballast.json') or {}
        weights=intervention.get('weights',[intervention])
        actual={w.get('node'):metadata.get('actual_nodes',{}).get(w.get('node'),{}).get('mass_kg') for w in weights}
        checks['diagnostic_counterweight_compiled']=(all(isinstance(actual[w.get('node')],(int,float)) and
            abs(actual[w['node']]-w['expected_node_mass_kg'])<1e-5 for w in weights) and
            abs(mass-intervention['expected_total_mass_kg'])<1e-3)
        result['diagnostic_details']=intervention|dict(actual_node_masses_kg=actual)
    metrics['compiled_mass_kg']=mass;checks['mass_matches']=abs(mass-manifest['expected_dry_mass_kg'])<max(1.,manifest['expected_dry_mass_kg']*.025)
    loaded=manifest.get('numerical_mass',{}).get('nodes',{})
    if loaded:
        # Check the actual engine graph, including joint supports and torque
        # reactions, rather than relying on total mass or wheel axles alone.
        actual=metadata.get('actual_nodes',{})
        failures={}
        valid=lambda x: type(x) in (int,float) and np.isfinite(x) and x>0
        for name,row in loaded.items():
            target=row.get('target_kg');value=actual.get(name,{}).get('mass_kg')
            if not valid(target) or not valid(value) or value<target-1e-6:
                failures[name]=dict(target_kg=target if valid(target) else None,
                                    actual_mass_kg=value if valid(value) else None)
        checks['loaded_node_mass_floors_compiled']=not failures
        metrics['loaded_node_mass_floor_count']=len(loaded)
        metrics['loaded_node_mass_floor_failures']=failures
    if manifest.get('steering_contract',{}):
        checks['rack_actuator_and_rails_compiled']=steering_compiled(manifest['steering_contract'],metadata.get('steering',{}))
    drive_rails=(manifest.get('driveline_physics') or {}).get('rails',[])
    if drive_rails:
        actual=metadata.get('steering',{})
        checks['driveline_rails_compiled']=all(actual.get('rails',{}).get(r['id'])==dict(nodes=[r['a'],r['b']],capped=True) and
            actual.get('sliders',{}).get(r['slider'])==dict(rail=r['id'],attached=True,fixed=True) for r in drive_rails)
    if manifest.get('collision_policy'):
        expected=manifest['collision_policy']['frame_nodes']
        actual=metadata.get('actual_nodes',{})
        checks['frame_collision_policy_compiled']=bool(expected) and all(
            actual.get(name,{}).get(key)==value for name,options in expected.items() for key,value in options.items())
    for device,expected in manifest.get('device_contract',{}).get('devices',{}).items():
        if expected.get('torqueReactionNodes'):
            checks[device+'_torque_reaction_nodes']=metadata.get('device_graph',{}).get(device,{}).get('torqueReactionNodes')==expected['torqueReactionNodes']
        if expected.get('inertiaChildren'):
            checks[device+'_inertia_children']=metadata.get('device_graph',{}).get(device,{}).get('inertiaChildren')==expected['inertiaChildren']
    for key,device in (('clutch_coupling','clutch'),('carrier_coupling','rearCarrierTakeoff'),('parking_lock','gearbox')):
        budget=manifest.get('device_contract',{}).get(key)
        if budget:
            actual=metadata.get('device_graph',{}).get(device,{})
            expected=(('parkLockSpring',budget['spring_nm_rad']),('parkLockDamp',budget['damping_nm_s_rad'])) if key=='parking_lock' else (
                ('lockSpring',budget['lock_spring_nm_rad2']),('lockDamp',budget['damping_nm_s_rad']))
            checks[key+'_compiled']=all(isinstance(actual.get(k),(int,float)) and np.isfinite(actual[k]) and
                abs(actual[k]-v)<=max(1e-8,abs(v)*1e-5) for k,v in expected)
    for device,budget in manifest.get('device_contract',{}).get('coupling_budgets',{}).items():
        actual=metadata.get('device_graph',{}).get(device,{})
        checks[device+'_coupling_budget_compiled']=all(isinstance(actual.get(k),(int,float)) and np.isfinite(actual[k]) and
            abs(actual[k]-value)<=max(1e-8,abs(value)*1e-5) for k,value in budget['expected'].items())
    for name,expected in manifest.get('required_controllers',{}).items():
        actual=metadata.get('controllers',{}).get(name,{})
        checks['controller_'+name]=name in metadata.get('controllers',{}) and all(actual.get(key)==value for key,value in expected.items())
    for name,wheel in manifest.get('wheels',{}).items():
        allocation=wheel.get('mass_allocation')
        if allocation:
            masses=[metadata.get('actual_nodes',{}).get(wheel['nodes'][key],{}).get('mass_kg') for key in ('axis_in','axis_out')]
            checks[name+'_loaded_axle_mass']=all(isinstance(value,(int,float)) and np.isfinite(value) and
                value>=allocation['minimum_support_node_kg']-1e-6 for value in masses)
        if wheel.get('reaction_nodes'):
            actual=metadata.get('tire_physics',{}).get(name,{}).get('reaction_nodes',{})
            checks[name+'_torque_reaction_nodes']=all(actual.get(k)==v for k,v in wheel['reaction_nodes'].items())
        expected=wheel.get('tire_contract')
        if expected:
            actual=metadata.get('tire_physics',{}).get(name,{})
            if expected.get('axle_nodes'):
                checks[name+'_wheel_axle_direction']=actual.get('axle_nodes')==expected['axle_nodes'] and actual.get('wheel_direction')==expected['wheel_direction']
            if 'reinforcement_l_beams' in expected:
                checks[name+'_tire_reinforcement']=actual.get('reinforcement_l_beams')==expected['reinforcement_l_beams']
            checks[name+'_pressure_tire_collision']=all(actual.get(k)==expected[k] for k in ('wheel_section','tread_nodes','hub_nodes')) and \
                actual.get('collision_nodes')==expected['tread_nodes'] and actual.get('self_collision_nodes')==0 and \
                bool(actual.get('pressure_group')) and 0<float(actual.get('pressure_pa',0))<1e8
    if scenario=='settle':
        tail=t>t[-1]-5;metrics['settled_relative_speed_m_s']=float(np.percentile(data['relative_node_speed'][tail],95));checks['settled']=metrics['settled_relative_speed_m_s']<.15
        checks['stays_upright']=bool(np.min(data['up_z'][tail])>.65);checks['low_drift']=float(max(data['speed'][tail]))<.25
    elif scenario=='acceleration':checks['20kmh_within_20s']=bool(np.any((t<=24)&(t>=4)&(data['forward_speed']>=20/3.6)))
    elif scenario=='braking':
        start=np.flatnonzero(data['brake']>.9);checks['reached_test_speed']=bool(len(start) and data['speed'][start[0]]>=19.5/3.6)
        stop=np.flatnonzero((data['brake']>.9)&(data['speed']<1/3.6));distance=float(data['distance'][stop[0]]-data['distance'][start[0]]) if len(start) and len(stop) else None
        metrics['stopping_distance_m']=distance;checks['stop_within_10m']=distance is not None and distance<=10
    elif scenario=='reverse':metrics['reverse_displacement_m']=float(-min(data['forward_distance']));checks['reverse_5m']=metrics['reverse_displacement_m']>=5
    elif scenario in ('left_turn','right_turn'):
        displacement=float(data['lateral_distance'][-1]);metrics['lateral_displacement_m']=displacement
        # A complete circle returns to the starting line. Assess the path rather
        # than its last point, and reject movement into the opposite half-plane.
        lateral=data['lateral_distance'][t>=4]*(1 if scenario=='left_turn' else -1)
        metrics['requested_lateral_excursion_m']=float(max(lateral))
        metrics['opposite_lateral_excursion_m']=float(max(0.,-min(lateral)))
        checks['turns_requested_direction']=metrics['requested_lateral_excursion_m']>2 and metrics['opposite_lateral_excursion_m']<=.5
        checks['stays_upright']=bool(np.min(data['up_z'])>.65)
    elif scenario=='supported':
        rear=(np.abs(data['av_RL'])+np.abs(data['av_RR']))/2;front=(np.abs(data['av_FL'])+np.abs(data['av_FR']))/2
        contract=manifest.get('device_contract')
        if contract:
            tail=t>14
            for corner in manifest['expected_wheel_names']:
                speed=float(np.mean(np.abs(data['av_'+corner][tail])))
                driven=max((float(np.mean(np.abs(data['av_'+c][tail]))) for c in contract['driven_wheels']),default=0.)
                checks[corner+'_drive_matches']=speed>1 if corner in contract['driven_wheels'] else speed<max(1.,driven*.15)
                if corner in contract['driven_wheels']:
                    velocity=data['av_'+corner][tail]
                    coherence=float(abs(np.sum(velocity))/max(np.sum(abs(velocity)),1e-9))
                    metrics[corner+'_spin_direction_coherence']=coherence
                    checks[corner+'_no_spin_reversal']=coherence>=.95
            if contract.get('template')=='driveline_graph':
                from .driveline_checks import sampled_checks
                graph_checks,graph_metrics=sampled_checks(contract,(read_json(Path(directory)/'motion_diagnostics.json') or {}).get('samples',[]))
                checks.update(graph_checks);metrics.update(graph_metrics)
            elif len(contract['driven_wheels'])==4:
                ratio=float(np.mean(front[tail])/max(np.mean(rear[tail]),1e-9));metrics['front_rear_speed_ratio']=ratio
                checks['geared_axle_ratio']=abs(ratio-contract['front_rear_speed_ratio'])<.05
        else:
            rwd=(t>6)&(t<8);awd=t>14;checks['rwd_rear_drive']=float(np.mean(rear[rwd]))>1
            checks['rwd_front_disconnected']=float(np.mean(front[rwd]))<max(1.,float(np.mean(rear[rwd]))*.15)
            checks['4wd_all_wheels']=all(float(np.mean(np.abs(data['av_'+c][awd])))>1 for c in manifest['expected_wheel_names'])
        checks['cvt_changes_ratio']=float(np.ptp(data['cvt_ratio']))>.02
    elif scenario=='articulation':
        for c in manifest['expected_wheel_names']:
            travel=float(np.ptp(data['travel_'+c]));metrics[c+'_travel_m']=travel;checks[c+'_moves']=.005<travel<.5
    motion_keys=set()
    if manifest.get('template_definition'):
        from .vehicle_motion import analyze_motion
        try:
            motion=analyze_motion(directory,manifest,scenario,float(t[-1]),completion.get('job_id'))
            checks.update(motion['checks']);metrics.update(motion['metrics'])
            motion_keys.update(motion['checks'])
        except (ValueError,KeyError,TypeError) as exc:
            checks['motion_reference_complete']=False
            metrics['motion_reference_error']=str(exc)
            motion_keys.add('motion_reference_complete')
    result['status']='passed' if all(checks.values()) else 'failed';result['reason']=None if result['status']=='passed' else ', '.join(k for k,v in checks.items() if not v)
    if result['status']=='passed':result['qualification_status']='scenario_verified'
    if scenario in DIAGNOSTIC_SCENARIOS:result['qualification_status']='diagnostic_only'
    result['assessment']=assess(result,motion_keys,validated=True,expected_motion=bool(manifest.get('template_definition')))
    return result


def run_vehicle(manifest_path,scenario='settle',*,project=None,progress=print,cancel=None,session=None,diagnostic=None):
    if scenario not in SCENARIOS and scenario not in DIAGNOSTIC_SCENARIOS:raise ValueError('Unknown vehicle scenario')
    if diagnostic not in (None,'no_aero','no_self_collision','balance_ballast','symmetric_ballast','drop','drop_no_internal_static'):raise ValueError('Unknown diagnostic intervention')
    drop=diagnostic in ('drop','drop_no_internal_static')
    if drop and scenario!='settle':raise ValueError('Drop diagnostic requires settling')
    if diagnostic and (scenario not in ('settle','acceleration') or diagnostic=='no_aero' and scenario!='acceleration'):
        raise ValueError('Diagnostic intervention requires a settling or acceleration pilot')
    manifest_path=Path(manifest_path).resolve();m,folder=intake(manifest_path);project=project or HarnessProject.load()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:6]
    run=manifest_path.parent/'tests'/(stamp+'-'+scenario);run.mkdir(parents=True)
    write_json(run/'build_manifest.json',m)
    from .session import DriveSession
    with (contextlib.nullcontext(session) if session is not None else DriveSession(project,'vehicle',cancel)) as active:
        active.retire()
        root=active.root;check_recording_space(root,run)
        mod=root/'mods/unpacked/vehicle_harness';vehicle=mod/'vehicles'/m['model']
        for vm,name in [('ge','vehicle_bridge'),('vehicle','vehicle_recorder')]:
            target=mod/'lua'/vm/'extensions/vehicleharness'/(name.removeprefix('vehicle_')+'.lua');target.parent.mkdir(parents=True,exist_ok=True)
            data=(Path(__file__).parent/'lua'/(name+'.lua')).read_bytes()
            if not target.is_file() or target.read_bytes()!=data:target.write_bytes(data)
        control=root/'settings/vehicle_harness';control.mkdir(parents=True,exist_ok=True)
        output=control/'results'/stamp;output.mkdir(parents=True)
        job={'id':stamp,'model':m['model'],'config':m['config'],'scenario':scenario,'duration':(SCENARIOS|DIAGNOSTIC_SCENARIOS)[scenario],
             'gravity':0 if scenario in ('supported','articulation') else -9.81,'spawn_z':m['spawn_z'] if scenario not in ('supported','articulation') else 2,
             'output':'/settings/vehicle_harness/results/'+stamp,'manifest':m,'diagnostic':diagnostic}
        if drop:job.update(spawn_z=job['spawn_z']+3.,drop_height_m=3.)
        from .vehicle_motion import reference
        job['motion_reference']=reference(m)
        job['fixture_fixed_nodes']=[]
        if scenario in ('supported','articulation'):
            # The owned smallgrid test surface is z=0. Measure every native
            # tread node throughout recording rather than trusting spawn_z.
            job.update(fixture_ground_z=0,fixture_minimum_clearance_m=.25)
            job['fixture_fixed_nodes']=m.get('chassis_nodes',[])
            if len(job['fixture_fixed_nodes'])<3:raise ValueError('Supported tests need at least three chassis nodes in the manifest')
        from .component_tests import stage_components
        staging_diagnostic={'drop':None,'drop_no_internal_static':'no_internal_static'}.get(diagnostic,diagnostic)
        expected,changed,written=stage_components(folder,vehicle,m['model'],job['fixture_fixed_nodes'],run,diagnostic=staging_diagnostic)
        write_json(control/'job.json',job);write_json(run/'job.json',job)
        job['expected_beams']=expected
        job.update(session_id=active.id,changed_files=changed,staging_bytes=written)
        write_json(run/'job.json',job)
        completion={}
        try:
            completion=active.execute(job,run,output)
        except KeyboardInterrupt:
            completion={'status':'cancelled','reason':'Test cancelled','job_id':stamp}
            active.close_process()
        except Exception as exc:
            completion={'status':'failed','reason':str(exc),'job_id':stamp}
            active.close_process()
        finally:
            active.archive_recording(output,run,archive_root=manifest_path.parent/'tests')
            active.archive_logs(run)
        if completion.get('job_id')!=stamp:completion={'status':'failed','reason':'Recording job identity differs'}
        if (run/'completion.json').is_file():shutil.copy2(run/'completion.json',run/'recorder_completion.json')
        completion=finite_completion(completion)
        write_json(run/'completion.json',completion)
        from .progress import emit
        emit('Analyze recording',completed=0,total=1,detail=scenario)
        try:result=analyze(run,m,scenario,completion)
        except Exception as exc:result={'status':'failed','reason':'Analysis failed: '+str(exc),'directory':str(run),'scenario':scenario}
        if diagnostic:
            result.update(diagnostic=diagnostic,qualification_status='diagnostic_only')
            if drop:result['drop_height_m']=job['drop_height_m']
        write_json(run/'result.json',result)
        from .vehicle_report import write_report
        try:write_report(run,result)
        except Exception as exc:progress('Report graphics unavailable: '+str(exc))
        emit('Analyze recording',completed=1,total=1,detail=scenario+': '+result['status'])
        (run/'report.txt').write_text(json.dumps(result,indent=2),encoding='utf-8');progress(result['status']+': '+str(result.get('reason') or scenario));return result


def run_acceptance(manifest_path,*,project=None,progress=print,cancel=None,save_report=False):
    results=[]
    if (cancel and cancel.is_set()) or (os.environ.get('BEAMNG_CAD_CANCEL') and Path(os.environ['BEAMNG_CAD_CANCEL']).exists()):
        from .progress import emit
        emit('Vehicle verification finished',completed=0,total=3*len(SCENARIOS),outcome='cancelled')
        return dict(status='failed',reason='Test cancelled before recording',directory=str(Path(manifest_path).resolve().parent/'tests'),
                    required_runs=3*len(SCENARIOS),completed_runs=0,runs=[],recording_status='cancelled',qualification_status='not_qualified')
    manifest_path=Path(manifest_path).resolve();manifest_hash=sha256(manifest_path)
    sources=[p for p in Path(__file__).parent.rglob('*') if p.suffix in ('.py','.lua')]
    implementation={p.relative_to(Path(__file__).parent).as_posix():sha256(p) for p in sources}
    from .session import DriveSession
    project=project or HarnessProject.load()
    with DriveSession(project,'vehicle',cancel) as active:
        for repeat in range(3):
            for scenario in SCENARIOS:
                if cancel and cancel.is_set():break
                progress(f'Acceptance repeat {repeat+1}/3: {scenario}')
                from .progress import emit
                emit('Test batch',completed=len(results),total=3*len(SCENARIOS),detail=f'{scenario}, repeat {repeat+1}/3')
                results.append(run_vehicle(manifest_path,scenario,project=project,progress=progress,cancel=cancel,session=active))
                if results[-1]['status']!='passed':break
            if cancel and cancel.is_set() or results and results[-1]['status']!='passed':break
    directory=Path(manifest_path).resolve().parent/'tests';result={'status':'passed' if len(results)==3*len(SCENARIOS) and all(r['status']=='passed' for r in results) else 'failed',
        'directory':str(directory),'required_runs':3*len(SCENARIOS),'completed_runs':len(results),'runs':results,
        'manual_review':['CAD hardpoint accuracy','Full-travel mesh clearance','Real material rupture and mesh separation']}
    unchanged=sha256(manifest_path)==manifest_hash and implementation=={p.relative_to(Path(__file__).parent).as_posix():sha256(p) for p in sources}
    intake(manifest_path)
    if not unchanged:result.update(status='failed',reason='Build manifest or verification implementation changed during recording')
    result.update(manifest_sha256=manifest_hash,verifier_sha256=implementation,verifier_unchanged=unchanged,
                  recording_status='completed' if len(results)==3*len(SCENARIOS) and all(r.get('recording_status')=='completed' for r in results) else 'incomplete',
                  qualification_status='template_scenarios_verified' if result['status']=='passed' else 'not_qualified',
                  full_report_saved=save_report or result['status']!='passed')
    if not result['full_report_saved']:
        from .component_tests import compact_success
        for run in results:compact_success(run['directory'])
    write_json(directory/'acceptance.json',result)
    from .vehicle_report import write_acceptance_report
    write_acceptance_report(directory,result)
    from .progress import emit
    emit('Vehicle verification finished',completed=len(results),total=3*len(SCENARIOS),outcome=result['status'])
    return result
