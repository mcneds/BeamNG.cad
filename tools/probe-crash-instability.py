"""Owned, nonqualifying large-disturbance experiments on a sealed vehicle.

Pull is a declared force waveform, NOT the interactive node grabber. Overhang
uses a native procedural collision box and an imposed initial vehicle velocity.
Candidate changes affect only the staged fixture; no installation or receipt.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dependencies/cad-calibration/Test Harness'))
from frame_harness.build import beam_table, write_json
from frame_harness.models import HarnessProject
from frame_harness.vehicle import intake
from frame_harness.vehicle_motion import reference

spec = importlib.util.spec_from_file_location('crash_base', ROOT / 'tools/probe-corner-response.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

HOOK = r'''
local crashFile,crashTime,crashStep,crashLaunched,crashPeak,crashHistory
local crashStart=start
start=function(value)
  crashStart(value)
  if not running then return end
  crashTime=0;crashStep=0;crashLaunched=false;crashPeak=0;crashHistory={}
  crashFile=assert(io.open(job.output..'/disturbance.csv','w'))
  crashFile:write('physics_s,force_x_n,force_y_n,force_z_n,max_node_speed,fastest_cid,broken\n')
end
local crashFinish=finish
finish=function(state,reason)
  if crashFile then crashFile:flush();crashFile:close();crashFile=nil end
  crashFinish(state,reason)
end
local function snapshot(label)
  local state={job_id=job.id,session_id=job.session_id,physics_s=crashTime,nodes={}}
  for _,n in ipairs(nodes) do
    local p=position(n.cid);local vel=obj:getNodeVelocityVector(n.cid)
    state.nodes[tostring(n.cid)]={name=n.name,p={p.x,p.y,p.z},v={vel.x,vel.y,vel.z}}
  end
  state.beams={}
  for _,b in pairs(v.data.beams) do
    state.beams[#state.beams+1]={cid=b.cid,broken=obj:beamIsBroken(b.cid),length=obj:getBeamLength(b.cid),rest=obj:getBeamRestLength(b.cid)}
  end
  jsonWriteFile(job.output..'/'..label..'.json',state,false)
end
local crashPhysics=onPhysicsStep
onPhysicsStep=function(dt)
  crashPhysics(dt)
  if not running then return end
  crashTime=crashTime+dt;crashStep=crashStep+1
  local e=job.excitation;local tau=crashTime-e.start_s
  local force=0
  if e.kind=='pull' and tau>=0 and tau<e.duration_s then
    force=e.force_n*math.sin(2*math.pi*e.frequency_hz*tau)
    obj:applyForceVector(byName[e.node].cid,vec3(e.axis[1],e.axis[2],e.axis[3])*force)
  elseif e.kind=='overhang' and tau>=0 and not crashLaunched then
    crashLaunched=true
    local dir=obj:getDirectionVector();dir.z=0;dir:normalize()
    local roof=-math.huge
    for _,name in ipairs(job.manifest.chassis_nodes) do roof=math.max(roof,position(byName[name].cid).z) end
    obj:queueGameEngineLua(string.format([[
      local veh=be:getObjectByID(%d);local dir=vec3(%g,%g,0)
      local center=veh:getPosition()+dir*6;center.z=%g
      local obstacle=scenetree.findObject('cadCrashOverhang');assert(obstacle,'Missing crash fixture')
      obstacle:setPosition(center);be:reloadCollision()
      jsonWriteFile(%q,{job_id=%q,center={center.x,center.y,center.z},size={8,1,.6},
        bottom_z=center.z-.3,settled_roof_z=%g,velocity={dir.x*%g,dir.y*%g,0}},true)
      veh:applyClusterVelocityScaleAdd(veh:getRefNodeId(),0,dir.x*%g,dir.y*%g,0)
    ]],obj:getId(),dir.x,dir.y,roof,job.output..'/obstacle.json',job.id,roof,e.speed_m_s,e.speed_m_s,e.speed_m_s,e.speed_m_s))
  end
  local maximum,fastest=0,-1
  for _,n in ipairs(nodes) do
    local speed=obj:getNodeVelocityVector(n.cid):length()
    if speed~=speed then snapshot('nonfinite');finish('failed','Nonfinite node velocity');return end
    if speed>maximum then maximum=speed;fastest=n.cid end
  end
  if maximum>math.max(30,crashPeak*2) then
    jsonWriteFile(job.output..'/before-onset-'..tostring(crashStep)..'.json',
      {job_id=job.id,session_id=job.session_id,samples=crashHistory},false)
    crashPeak=maximum;snapshot('onset-'..tostring(crashStep))
  end
  if e.kind~='control' and crashTime>=e.start_s and crashStep%4==0 then
    local row={physics_s=crashTime,nodes={}}
    for _,n in ipairs(nodes) do local p=position(n.cid);local vel=obj:getNodeVelocityVector(n.cid)
      row.nodes[tostring(n.cid)]={p={p.x,p.y,p.z},v={vel.x,vel.y,vel.z}}
    end
    crashHistory[#crashHistory+1]=row
    if #crashHistory>16 then table.remove(crashHistory,1) end
  end
  if crashStep%10==0 or maximum>100 then
    local broken=0;for _,b in pairs(v.data.beams) do if obj:beamIsBroken(b.cid) then broken=broken+1 end end
    crashFile:write(string.format('%.12g,%.12g,%.12g,%.12g,%.12g,%d,%d\n',crashTime,force*e.axis[1],force*e.axis[2],force*e.axis[3],maximum,fastest,broken))
  end
  if crashStep%200==0 then crashFile:flush() end
  if maximum>1000 then snapshot('divergence');finish('failed','Node speed exceeded 1000 m/s');return end
end
'''


def instrument(source):
    return base.instrument(source).replace(base.HOOK, HOOK)


def stage(source, destination, manifest, run, candidate):
    """Copy physics inputs only; keep expected native properties synchronized."""
    destination.mkdir(parents=True, exist_ok=True)
    expected, changed, torsions = [], [], []
    for path in source.rglob('*'):
        if not path.is_file() or path.suffix not in ('.jbeam', '.pc', '.lua'):
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == '.jbeam':
            parts = json.loads(path.read_bytes())
            for part in parts.values():
                part.pop('flexbodies', None)
                part.pop('props', None)
                if candidate in ('structural-half', 'structural-damp-quarter'):
                    spring_factor = .5 if candidate == 'structural-half' else 1.
                    damp_factor = .5 if candidate == 'structural-half' else .25
                    for section in ('beams', 'hydros'):
                        for row in part.get(section, [])[1:]:
                            if isinstance(row, list) and row[-1].get('beamType', '|NORMAL') != '|BOUNDED':
                                for key in ('beamSpring', 'beamDamp'):
                                    if key in row[-1]:
                                        row[-1][key] *= spring_factor if key == 'beamSpring' else damp_factor
                    for row in part.get('torsionbars', [])[1:]:
                        if isinstance(row, list):
                            row[-1]['spring'] *= spring_factor
                            row[-1]['damp'] *= damp_factor
                elif candidate == 'no-angular':
                    part['torsionbars'] = part.get('torsionbars', [])[:1]
                elif candidate == 'angular-quarter':
                    for row in part.get('torsionbars', [])[1:]:
                        if isinstance(row, list):
                            row[-1]['spring'] *= .25
                            row[-1]['damp'] *= .25
                elif candidate == 'no-internal-static':
                    defaults = {}
                    for row in part.get('nodes', [])[1:]:
                        if isinstance(row, dict):
                            defaults.update(row)
                        elif (defaults | row[-1]).get('collision', True) is False:
                            row[-1]['staticCollision'] = False
                expected.extend(beam_table(part))
                torsions.extend(row for row in part.get('torsionbars', [])[1:] if isinstance(row, list))
            write_json(target, parts)
            write_json(run / ('fixture-' + path.name), parts)
        else:
            shutil.copy2(path, target)
        changed.append('/vehicles/' + manifest['model'] + '/' + path.relative_to(source).as_posix())
    manifest['torsionbars'] = torsions
    return expected, changed


def run_case(session, a, m, source, hashes, inputs, result, node):
    session.retire()
    session.mode = 'null'
    session.visible_for_evidence = False
    mod = session.root / 'mods/unpacked/vehicle_harness'
    recorder = mod / 'lua/vehicle/extensions/vehicleharness/recorder.lua'
    recorder.write_text(instrument((ROOT / 'dependencies/cad-calibration/Test Harness/frame_harness/lua/vehicle_recorder.lua').read_text()), encoding='utf-8')
    (a.output / 'diagnostic-recorder.lua').write_bytes(recorder.read_bytes())
    (mod / 'lua/ge/extensions/visuals.lua').write_text('return {new=function() local function noop() end;return {camera=noop,capture=noop,draw=noop,update=noop,dispose=noop} end}')
    bridge = mod / 'lua/ge/extensions/session_bridge.lua'
    text = (ROOT / 'dependencies/cad-calibration/Test Harness/frame_harness/lua/session_bridge.lua').read_text()
    anchor = "be:setEnabled(true);be:setSimulationTimeScale(1);status('spawning')"
    assert text.count(anchor) == 1
    setup = "FS:directoryCreate(job.output,true);be:setPhysicsDeterministic(true);"
    # Runtime selection also works when a matrix reuses the loaded GE module.
    main_part = json.loads((source / m['main_jbeam']).read_bytes())[m['main_part']]
    ref = main_part['refNodes'][1][0]
    roof = max(m['nodes'][n]['position'][2] for n in m['chassis_nodes']) + m['spawn_z'] - m['nodes'][ref]['position'][2]
    bottom = roof - .30
    setup += ("local old=scenetree.findObject('cadCrashOverhang');if old then old:delete() end;"
              "if job.excitation.kind=='overhang' then local obstacle=createObject('ProceduralMesh');obstacle.canSave=false;"
                  "obstacle:registerObject('cadCrashOverhang');scenetree.MissionGroup:add(obstacle.obj);"
                  # Native createCube takes (Y extent, X extent, Z extent).
                  "local mesh=require('util/trackBuilder/proceduralPrimitives').createCube(vec3(1,8,.6),'track_editor_A_border',1);"
                  "obstacle:createMesh({{mesh}});obstacle:setPosition(vec3(0,-6," + str(bottom + .3) + "));end;be:reloadCollision();")
    if a.scenario == 'overhang':
        result['obstacle_initial_placement'] = dict(center=[0, -6, bottom + .3], size=[8, 1, .6],
                                                   note='Repositioned at launch from native direction and settled roof height; see obstacle.json')
    bridge.write_text(text.replace(anchor, setup + anchor), encoding='utf-8')
    (a.output / 'diagnostic-session-bridge.lua').write_bytes(bridge.read_bytes())
    expected, changed = stage(source, mod / 'vehicles' / m['model'], m, a.output, a.candidate)
    identity = 'crash-' + uuid.uuid4().hex
    out = session.control / 'results' / identity
    out.mkdir(parents=True)
    job = dict(id=identity, model=m['model'], config=m['config'], duration=a.duration, gravity=-9.81,
               spawn_z=m['spawn_z'], scenario='crash_diagnostic', manifest=m, motion_reference=reference(m),
               fixture_fixed_nodes=[], expected_beams=expected, changed_files=changed,
               output='/settings/vehicle_harness/results/' + identity,
               excitation=dict(kind=a.scenario, node=node, force_n=a.force, axis=a.axis,
                               start_s=3., duration_s=4., frequency_hz=2., speed_m_s=a.speed, steering=0.))
    write_json(a.output / 'job.json', job)
    write_json(a.output / 'build_manifest.json', m)
    try:
        result['completion'] = session.execute(job, a.output, out, capture=False)
    except Exception as error:
        result['error'] = str(error)
    finally:
        if result.get('error'):
            session.close_process()
        if out.exists():
            session.archive_recording(out, a.output, archive_root=a.output.parent)
        else:
            result['recording_missing'] = True
        session.archive_logs(a.output)
        result['sources_unchanged'] = all(hashlib.sha256(f.read_bytes()).hexdigest() == hashes[str(f)] for f in inputs)
        result['instrumentation_sha256'] = {name: hashlib.sha256((a.output / name).read_bytes()).hexdigest()
                                           for name in ('diagnostic-recorder.lua', 'diagnostic-session-bridge.lua')}
        write_json(a.output / 'probe.json', result)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest', type=Path)
    p.add_argument('--profile', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--scenario', choices=['control', 'pull', 'overhang'], default='pull')
    p.add_argument('--candidate', choices=['baseline', 'no-angular', 'angular-quarter', 'no-internal-static', 'structural-half', 'structural-damp-quarter'], default='baseline')
    p.add_argument('--suite', choices=['screening', 'mitigation', 'damping', 'confirmation'],
                   help='Run declared controls and candidate comparisons in one owned session')
    p.add_argument('--duration', type=float, default=10., help='Recording duration, 10..30 seconds')
    p.add_argument('--test-timeout', type=float, default=180., help='Wall-clock recording allowance; does not change simulated duration')
    p.add_argument('--node', help='Explicit node name; defaults to the highest chassis node')
    p.add_argument('--force', type=float, default=10000.)
    p.add_argument('--speed', type=float, default=15.)
    p.add_argument('--axis', type=float, nargs=3, default=[1., 0., 0.])
    a = p.parse_args()
    if not 0 <= a.force <= 100000 or not 0 < a.speed <= 40:
        p.error('Force must be 0..100000 N and speed >0..40 m/s')
    if not 10 <= a.duration <= 30:
        p.error('Duration must be 10..30 seconds')
    if not math.isfinite(a.test_timeout) or a.test_timeout < 30:
        p.error('Test timeout must be finite and at least 30 seconds')
    if not all(math.isfinite(x) for x in a.axis) or not math.isclose(sum(x*x for x in a.axis), 1.):
        p.error('Axis must be a finite unit vector')
    m, source = intake(a.manifest)
    m = copy.deepcopy(m)
    node = a.node or max(m['chassis_nodes'], key=lambda n: m['nodes'][n]['position'][2])
    if node not in m['nodes']:
        p.error('Unknown explicit node')
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=False)
    inputs = [a.manifest, *[f for f in source.rglob('*') if f.is_file() and f.suffix in ('.jbeam', '.pc', '.lua')]]
    hashes = {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in inputs}
    result = dict(qualification_status='not_qualified', purpose=__doc__, source_hashes=hashes,
                  candidate=a.candidate, scenario=a.scenario)
    project = HarnessProject(userpath=a.profile, source=source, runs=a.output.parent,
                             startup_timeout=360., test_timeout=a.test_timeout)
    with base.probe.ProbeSession(project, 'vehicle', cancel=threading.Event()) as session:
        original_output = a.output
        suites = {
            'screening': [('control', 'baseline'), ('pull', 'baseline'), ('pull', 'angular-quarter'),
                          ('pull', 'no-angular'), ('overhang', 'baseline'), ('overhang', 'angular-quarter'),
                          ('overhang', 'no-internal-static')],
            'mitigation': [('control', 'structural-half'), ('pull', 'baseline'), ('pull', 'structural-half'),
                           ('overhang', 'baseline'), ('overhang', 'structural-half'), ('overhang', 'no-internal-static')],
            'damping': [('control', 'structural-damp-quarter'), ('pull', 'structural-damp-quarter'),
                        ('overhang', 'baseline'), ('overhang', 'structural-half'), ('overhang', 'structural-damp-quarter')],
            'confirmation': [('pull', a.candidate), ('overhang', a.candidate)],
        }
        cases = suites[a.suite] if a.suite else [(a.scenario, a.candidate)]
        for index, (scenario, candidate) in enumerate(cases):
            a.scenario, a.candidate = scenario, candidate
            if a.suite:
                a.output = original_output / f'{index:02d}-{scenario}-{candidate}'
                a.output.mkdir()
            result = dict(qualification_status='not_qualified', purpose=__doc__, source_hashes=hashes,
                          candidate=candidate, scenario=scenario)
            run_case(session, a, copy.deepcopy(m), source, hashes, inputs, result, node)
            print('Case:', scenario, candidate, result.get('completion', {}).get('status'),
                  result.get('completion', {}).get('reason'), result.get('error'), flush=True)
            if result.get('error'):
                break
    print(json.dumps({k: v for k, v in result.items() if k not in ('source_hashes', 'completion')}, indent=2))
    print('Completion:', result.get('completion', {}).get('status'), result.get('completion', {}).get('reason'))
    if result.get('error'):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
