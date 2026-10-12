"""Nonqualifying equal-force suspension rate sweep in an owned native fixture.

Chassis pinned, gravity zero, engine off and gearbox neutral. All four corners
receive a smooth upward bias equal to the declared preload times motion ratio;
one corner additionally receives a sinusoidal hub force. Geometry, masses,
spring/damper laws and stops are unchanged. This is a load-rate experiment,
not a change of physics timestep, nor a physical shock specification.
"""
import argparse, hashlib, importlib.util, json, math, sys, threading, time, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('corner_probe',ROOT/'tools/probe-corner-response.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
probe=base.probe
from frame_harness.build import write_json
from frame_harness.models import HarnessProject
from frame_harness.vehicle import intake
from frame_harness.vehicle_motion import reference
from frame_harness.component_tests import stage_components

HOOK=r'''
local rateFile,rateTime,rateSamples
local originalStart=start
start=function(value)
  originalStart(value)
  if not running then return end
  rateTime=0;rateSamples=0
  rateFile=assert(io.open(job.output..'/shock_rate.csv','w'))
  rateFile:write('physics_s,corner,beam_cid,length_m,velocity_m_s,elastic_n,damping_n,hub_force_n,rest_m\n')
end
local originalFinish=finish
finish=function(state,reason)
  if rateFile then
    rateFile:flush();rateFile:close();rateFile=nil
    assert(jsonWriteFile(job.output..'/shock_rate.json',{
      job_id=job.id,samples=rateSamples,complete=state=='completed',
      timing='Force applied after current-step measurements; response begins next step'
    },true))
  end
  originalFinish(state,reason)
end
local originalStep=onPhysicsStep
onPhysicsStep=function(dt)
  originalStep(dt)
  if not running then return end
  rateTime=rateTime+dt
  local ramp=math.min(rateTime/3,1);ramp=ramp*ramp*(3-2*ramp)
  local tau=rateTime-job.excitation.start_s
  for _,corner in ipairs({'FL','FR','RL','RR'}) do
    local force=job.excitation.bias_n[corner]*ramp
    if corner==job.excitation.corner and tau>=0 and tau<job.excitation.duration_s then
      if job.excitation.kind=='recovery' then
        local envelope=math.max(0,math.min(1,tau/2,(6-tau)/2))
        envelope=envelope*envelope*(3-2*envelope)
        force=force+job.excitation.amplitude_n*envelope
      else
        force=force+job.excitation.amplitude_n*math.sin(2*math.pi*job.excitation.frequency_hz*tau)
      end
    end
    local pair=job.manifest.wheels[corner].nodes
    obj:applyForceVector(byName[pair.axis_in].cid,vec3(0,0,force*.5))
    obj:applyForceVector(byName[pair.axis_out].cid,vec3(0,0,force*.5))
    for _,beam in ipairs(coiloverBeams[corner]) do
      local delta=position(beam.id2)-position(beam.id1);local length=delta:length()
      local velocity=(obj:getNodeVelocityVector(beam.id2)-obj:getNodeVelocityVector(beam.id1)):dot(delta)/math.max(length,1e-12)
      local elastic,damping=obj:getBeamStressDamp(beam.cid)
      rateFile:write(string.format('%.12g,%s,%d,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g\n',rateTime,corner,beam.cid,length,velocity,elastic,damping,force,obj:getBeamRestLength(beam.cid)))
      rateSamples=rateSamples+1
    end
  end
end
'''

def instrument(source):
    return base.instrument(source).replace(base.HOOK,HOOK)

def excitation(manifest,corner,hz,amplitude):
    if not math.isfinite(hz) or hz not in (.5,1.,2.):raise ValueError('Rate must be 0.5, 1 or 2 Hz')
    if not math.isfinite(amplitude) or not 0<=amplitude<=200:raise ValueError('Force amplitude must be 0..200 N')
    bias={c:w['spring_preload_n']*w['motion_ratio'] for c,w in manifest['wheels'].items()}
    if set(bias)!={'FL','FR','RL','RR'} or any(not math.isfinite(v) or v<=amplitude for v in bias.values()):
        raise ValueError('Four positive declared suspension preload biases required')
    return dict(corner=corner,frequency_hz=hz,amplitude_n=amplitude,bias_n=bias,steering=0.,start_s=6.,duration_s=4.)

def recovery_excitation(manifest,corner,force):
    if not math.isfinite(force) or force not in (0.,250.,500.,1000.):raise ValueError('Recovery force must be 0, 250, 500 or 1000 N')
    result=excitation(manifest,corner,1.,0.)
    return result | dict(kind='recovery',amplitude_n=force,duration_s=6.)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--profile',required=True,type=Path)
    p.add_argument('--frequency',type=float);p.add_argument('--amplitude',type=float,default=100.)
    p.add_argument('--recovery-force',type=float,choices=[0.,250.,500.,1000.],help='Bounded smooth bump/hold/release in N; recover through 24 s')
    p.add_argument('--corner',choices=['FL','FR','RL','RR'],default='FR');a=p.parse_args()
    import psutil
    if (a.frequency is None)==(a.recovery_force is None):p.error('Choose --frequency or --recovery-force')
    m,folder=intake(a.manifest)
    settings=recovery_excitation(m,a.corner,a.recovery_force) if a.recovery_force is not None else excitation(m,a.corner,a.frequency,a.amplitude)
    duration=24. if a.recovery_force is not None else 14.
    a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    harness=ROOT/'dependencies/cad-calibration/Test Harness/frame_harness'
    paths=[a.manifest,Path(__file__),Path(base.__file__),Path(probe.__file__),*sorted(f for f in harness.rglob('*') if f.suffix in ('.py','.lua'))]
    before={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in paths}
    cancelled=threading.Event();stopped=threading.Event();resources=[]
    result=dict(qualification_status='not_qualified',purpose=__doc__,manifest_sha256=before[str(a.manifest)],implementation=before)
    project=HarnessProject(userpath=a.profile,source=folder,runs=a.output.parent,test_timeout=300.)
    with probe.ProbeSession(project,'vehicle',cancel=cancelled) as session:
        session.mode='null';mod=session.root/'mods/unpacked/vehicle_harness'
        recorder=mod/'lua/vehicle/extensions/vehicleharness/recorder.lua'
        recorder.write_text(instrument(recorder.read_text(encoding='utf-8')),encoding='utf-8')
        (a.output/'diagnostic-recorder.lua').write_bytes(recorder.read_bytes())
        (mod/'lua/ge/extensions/visuals.lua').write_text("return {new=function() local function noop() end; return {camera=noop,capture=noop,draw=noop,update=noop,dispose=noop} end}",encoding='utf-8')
        bridge=mod/'lua/ge/extensions/session_bridge.lua';source=bridge.read_text(encoding='utf-8')
        anchor="be:setEnabled(true);be:setSimulationTimeScale(1);status('spawning')"
        if source.count(anchor)!=1:raise ValueError('Deterministic stepping hook changed')
        bridge.write_text(source.replace(anchor,'be:setPhysicsDeterministic(true);'+anchor),encoding='utf-8')
        (a.output/'diagnostic-session-bridge.lua').write_bytes(bridge.read_bytes())
        expected,changed,written=stage_components(folder,mod/'vehicles'/m['model'],m['model'],m['chassis_nodes'],a.output)
        result['physics_only']=probe.physics_only_fixture(mod/'vehicles'/m['model'],a.output,m['model'],changed)
        identity='suspension-rate-'+uuid.uuid4().hex;out=session.control/'results'/identity;out.mkdir(parents=True)
        ref=reference(m);selected=set()
        for corner in ('FL','FR'):
            selected.update(ref['corners'][corner]['points'].values());selected.update(ref['corners'][corner]['axis'])
        datum=sorted(m['chassis_nodes'])[:3];selected.update(datum)
        job=dict(id=identity,model=m['model'],config=m['config'],duration=duration,gravity=0.,spawn_z=m['spawn_z']+3.,
            scenario='suspension_rate',output='/settings/vehicle_harness/results/'+identity,manifest=m,motion_reference=ref,
            fixture_fixed_nodes=m['chassis_nodes'],expected_beams=expected,changed_files=changed,staging_bytes=written,
            excitation=settings,frequency_capture=dict(start_s=16. if a.recovery_force is not None else 6.,duration_s=7.,nodes=sorted(selected),chassis_nodes=datum,
                full_chassis_registration=True,loads=True,velocities=True,actuator_targets=True))
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
    print(json.dumps(dict(output=str(a.output),recording_status=result.get('completion',{}).get('status'),
        qualification_status='not_qualified',sources_unchanged=result['sources_unchanged']),indent=2))

if __name__=='__main__':main()
