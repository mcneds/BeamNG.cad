"""Fast nondestructive screening; deliberately separate from full qualification."""
from dataclasses import asdict
import json
import math
from pathlib import Path
import time

from .build import sha256, write_json
from .generation import scenario, load_artifact
from .models import ParameterSet
from .progress import emit
from .runner import run_test, saved_recording_failure
from .session import DriveSession


def quick_plan(config):
    return [scenario(config, name) for name in ('spring', 'idle', 'flex', 'torsion')]


def screen_result(record, report):
    reasons=[]; m=record.get('metrics',{}); name=record['scenario']
    if record['status']!='completed':return [record.get('failure_reason') or record['status']]
    if name=='spring':
        error=m.get('spring_relative_error')
        return [] if isinstance(error,(float,int)) and math.isfinite(error) and error<.01 else ['Spring instrument calibration failed']
    def number(key):
        value=m.get(key)
        return value if isinstance(value,(float,int)) and math.isfinite(value) else float('inf')
    if abs(number('measured_mass_kg')/report['mass']['target_mass_kg']-1)>.001:reasons.append('Mass differs by more than 0.1%')
    if number('broken_beams') or number('max_rest_length_change_m')>1e-5:reasons.append('Damage in a nondestructive test')
    if m.get('mesh_load_valid') is not True or m.get('render_controller_valid') is False:reasons.append('Mesh/controller loading failed')
    if name=='idle':
        if number('final_shape_rms_m')>.005 or number('tail_world_speed_rms_m_s')>.05:reasons.append('Idle shape/motion limits exceeded')
    else:
        ref=report['responses'][name]['reference']
        if not ref or not m.get('hold_settled') or abs(number('held_deflection_m')/(100*ref['compliance_m_n'])-1)>.1:
            reasons.append('Settled stiffness differs from reference by more than 10%')
        if m.get('position_velocity_consistent') is not True or m.get('applied_force_consistent') is not True:
            reasons.append('Measurement cross-check failed')
    return reasons


def batch_progress(records, completed, total, detail):
    times=[r.get('metrics',{}).get('performance',{}).get('total_seconds') for r in records]
    times=[t for t in times if isinstance(t,(int,float)) and t>0]
    if times:
        seconds=sum(times)/len(times)*max(0,total-completed)
        detail+=f' | estimated remaining {seconds/60:.1f} min'
    emit('Test batch',completed=completed,total=total,detail=detail)


def run_quick(project, output, state, case, *, save_report=False):
    output=Path(output); config=state['config']; report=state['candidates'][case]
    if not report['offline_accepted']:raise ValueError('Quick check requires accepted offline calibration')
    load_artifact(project,output/case/'calibration.json')
    plan=quick_plan(config)
    identity=dict(mode='quick',version=1,calibration=state['identity'],case=case,
                  artifact=sha256(output/case/'calibration.json'),scenarios=[asdict(s) for s in plan],
                  game=str(project.executable.resolve()),game_sha256=sha256(project.executable))
    path=output/'quick-verification.json'
    quick=json.loads(path.read_text()) if path.exists() else dict(identity=identity,runs=[])
    if quick['identity']!=identity:raise ValueError('Quick verification inputs changed; start a new generation')
    quick.update(status='testing',mode='quick',qualification_status='not_qualified',reasons=[])
    started=time.monotonic()
    try:
        with DriveSession(project) as session:
            for i,test in enumerate(plan):
                batch_progress(quick['runs'],i,len(plan),'Quick: '+test.name)
                existing=[r for r in quick['runs'] if r['scenario']==test.name]
                record=existing[-1] if existing else None
                if not record or record['status']=='cancelled' or saved_recording_failure(Path(record['path'])):
                    params=ParameterSet(name='instrument-spring') if test.name=='spring' else ParameterSet(name=case,calibration=str(output/case/'calibration.json'))
                    record=asdict(run_test(project,test,params,session=session,save_report=save_report))|{'key':'quick-'+test.name}
                    quick['runs'].append(record)
                reasons=screen_result(record,report)
                write_json(path,quick)
                if reasons:
                    quick.update(status='cancelled' if record['status']=='cancelled' else 'quick_failed',reasons=reasons)
                    break
            else:quick['status']='quick_passed'
    except KeyboardInterrupt:
        quick['status']='cancelled'
    except Exception as error:
        quick.update(status='quick_failed',reasons=[str(error)])
        write_json(path,quick)
        raise
    finally:
        quick['elapsed_seconds']=time.monotonic()-started
        write_json(path,quick)
    batch_progress(quick['runs'],len(quick['runs']),len(plan),'Quick check finished')
    return quick
