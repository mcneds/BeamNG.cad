"""Nonqualifying yaw-force response with an owned, suspended chassis fixture.

Preserves the exported vehicle; only staged chassis pins, gravity, neutral gear,
ignition and measured external forces differ. Production recording and compiled
graph validation remain active. A zero-amplitude control is required separately.
"""
import argparse, hashlib, importlib.util, json, sys, threading, time, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.build import write_json
from frame_harness.models import HarnessProject
from frame_harness.vehicle import intake
from frame_harness.vehicle_motion import reference
from frame_harness.component_tests import stage_components
spec=importlib.util.spec_from_file_location('drive_probe',ROOT/'tools/probe-drive-execution.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

HOOK=r'''
local excitationFile,excitationTime,excitationSamples
local originalStart=start
start=function(value)
  originalStart(value)
  if not running then return end
  excitationTime=0;excitationSamples=0
  excitationFile=assert(io.open(job.output..'/excitation.csv','w'))
  excitationFile:write('physics_s,yaw_moment_nm,fx_out_n,fy_out_n,fz_out_n\n')
end
local originalFinish=finish
finish=function(state,reason)
  if excitationFile then
    excitationFile:flush();excitationFile:close();excitationFile=nil
    assert(jsonWriteFile(job.output..'/excitation.json',{
      job_id=job.id,samples=excitationSamples,complete=state=='completed',
      timing='Force is applied after recording this physics step; response begins next step'
    },true))
  end
  originalFinish(state,reason)
end
local originalStep=onPhysicsStep
onPhysicsStep=function(dt)
  originalStep(dt)
  if not running then return end
  excitationTime=excitationTime+dt;excitationSamples=excitationSamples+1
  local moment=0
  local tau=excitationTime-job.excitation.start_s
  if tau>=0 and tau<job.excitation.duration_s then
    local count=#job.excitation.frequencies_hz
    for i,hz in ipairs(job.excitation.frequencies_hz) do
      -- Schroeder phases bound the multisine crest factor.
      moment=moment+job.excitation.amplitude_nm*math.sin(2*math.pi*hz*tau-math.pi*(i-1)*i/count)
    end
  end
  local pair=job.manifest.wheels[job.excitation.corner].nodes
  local a,b=byName[pair.axis_in].cid,byName[pair.axis_out].cid
  local d=position(b)-position(a);local square=d.x*d.x+d.y*d.y
  assert(square>1e-8,'Degenerate yaw fixture axle')
  local force=vec3(-d.y,d.x,0)*(moment/square)
  obj:applyForceVector(b,force);obj:applyForceVector(a,-force)
  excitationFile:write(string.format('%.12g,%.12g,%.12g,%.12g,%.12g\n',excitationTime,moment,force.x,force.y,force.z))
end
'''

def instrument(source):
    replacements={
        "controller.mainController.shiftToGearIndex(job.scenario=='reverse' and -1 or 2)":"controller.mainController.shiftToGearIndex(0)",
        'electrics.setIgnitionLevel(3)':'electrics.setIgnitionLevel(0)',
        'if t>1 and t<1.2 then electrics.setIgnitionLevel(2) end':'electrics.setIgnitionLevel(0)',
        "input.event('steering',steering,'FILTER_AI',nil,nil,nil,'cadHarness')":"input.event('steering',job.excitation.steering,'FILTER_AI',nil,nil,nil,'cadHarness')",
        'M.start=protected(start);M.onPhysicsStep=protected(onPhysicsStep);M.updateGFX=protected(updateGFX)':HOOK+'\nM.start=protected(start);M.onPhysicsStep=protected(onPhysicsStep);M.updateGFX=protected(updateGFX)'}
    for before,after in replacements.items():
        if source.count(before)!=1:raise ValueError('Production recorder hook changed: '+before)
        source=source.replace(before,after)
    return source

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--profile',type=Path,required=True)
    p.add_argument('--amplitude',type=float,required=True);p.add_argument('--steering',type=float,default=0.)
    p.add_argument('--test-timeout',type=float,default=120.)
    p.add_argument('--corner',choices=['FL','FR'],default='FR');a=p.parse_args()
    if not 0<=a.amplitude<=.05 or not -1<=a.steering<=1:p.error('Bounded input required: amplitude 0..0.05 Nm, steering -1..1')
    if not 120<=a.test_timeout<=600:p.error('Test timeout must be 120..600 seconds')
    import psutil
    m,folder=intake(a.manifest);a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    harness=ROOT/'dependencies/cad-calibration/Test Harness/frame_harness'
    paths=[a.manifest,Path(__file__),*sorted(f for f in harness.rglob('*') if f.suffix in ('.py','.lua'))]
    before={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in paths}
    cancelled=threading.Event();stopped=threading.Event();resources=[]
    result=dict(qualification_status='not_qualified',purpose=__doc__,manifest_sha256=before[str(a.manifest)],implementation=before)
    project=HarnessProject(userpath=a.profile,source=folder,runs=a.output.parent,test_timeout=a.test_timeout)
    with probe.ProbeSession(project,'vehicle',cancel=cancelled) as session:
        session.mode='null';mod=session.root/'mods/unpacked/vehicle_harness'
        recorder=mod/'lua/vehicle/extensions/vehicleharness/recorder.lua'
        recorder.write_text(instrument(recorder.read_text(encoding='utf-8')),encoding='utf-8')
        (a.output/'diagnostic-recorder.lua').write_bytes(recorder.read_bytes())
        visual="return {new=function() local function noop() end; return {camera=noop,capture=noop,draw=noop,update=noop,dispose=noop} end}"
        (mod/'lua/ge/extensions/visuals.lua').write_text(visual,encoding='utf-8')
        bridge=mod/'lua/ge/extensions/session_bridge.lua';source=bridge.read_text(encoding='utf-8')
        anchor="be:setEnabled(true);be:setSimulationTimeScale(1);status('spawning')"
        if source.count(anchor)!=1:raise ValueError('Deterministic stepping hook changed')
        bridge.write_text(source.replace(anchor,'be:setPhysicsDeterministic(true);'+anchor),encoding='utf-8')
        (a.output/'diagnostic-session-bridge.lua').write_bytes(bridge.read_bytes())
        expected,changed,written=stage_components(folder,mod/'vehicles'/m['model'],m['model'],m['chassis_nodes'],a.output)
        identity='corner-response-'+uuid.uuid4().hex;out=session.control/'results'/identity;out.mkdir(parents=True)
        ref=reference(m);selected=set()
        for corner in ('FL','FR'):
            selected.update(ref['corners'][corner]['points'].values());selected.update(ref['corners'][corner]['axis'])
        datum=sorted(m['chassis_nodes'])[:3];selected.update(datum)
        job=dict(id=identity,model=m['model'],config=m['config'],duration=16.,gravity=0.,spawn_z=m['spawn_z']+3.,
            scenario='corner_response',output='/settings/vehicle_harness/results/'+identity,manifest=m,motion_reference=ref,
            fixture_fixed_nodes=m['chassis_nodes'],expected_beams=expected,changed_files=changed,staging_bytes=written,
            excitation=dict(corner=a.corner,amplitude_nm=a.amplitude,steering=a.steering,start_s=6.,duration_s=4.,frequencies_hz=list(range(8,41))),
            frequency_capture=dict(start_s=6.,duration_s=8.,nodes=sorted(selected),chassis_nodes=datum,
                full_chassis_registration=True,loads=True,velocities=True,actuator_targets=True,wheels=True))
        write_json(a.output/'job.json',job);write_json(a.output/'build_manifest.json',m)
        def monitor():
            low=None;start=time.monotonic()
            while not stopped.is_set():
                available=psutil.virtual_memory().available;now=time.monotonic()
                resources.append(dict(wall_s=now-start,available_ram_bytes=available))
                low=(low or now) if available<384*1024**2 else None
                if low is not None and now-low>5:result['resource_abort']='Available RAM below 384 MiB for five seconds';cancelled.set()
                stopped.wait(1)
        watcher=threading.Thread(target=monitor,daemon=True);watcher.start()
        try:result['completion']=session.execute(job,a.output,out,capture=False)
        except Exception as error:result['error']=str(error);raise
        finally:
            session.close_process();stopped.set();watcher.join()
            session.archive_recording(out,a.output,archive_root=a.output.parent);session.archive_logs(a.output)
            result['sources_unchanged']=all(f.exists() and hashlib.sha256(f.read_bytes()).hexdigest()==before[str(f)] for f in paths)
            write_json(a.output/'probe.json',result);write_json(a.output/'resources.json',resources)

if __name__=='__main__':main()
