"""Bounded lateral force on ONE front hub node of an unpinned vehicle on the ground.

This is a reproducible force perturbation, not a claim to emulate the interactive
grabber's displacement controller. No passive vehicle properties are changed.
"""
import argparse,hashlib,importlib.util,json,math,sys,threading,time,uuid
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

def excitation(corner,force):
    if corner not in ('FL','FR') or not math.isfinite(force) or force not in (0.,100.,250.,500.,1000.):raise ValueError('Bounded front hub load required')
    return dict(corner=corner,amplitude_n=force,start_s=6.,duration_s=4.,frequency_hz=2.,fade_s=.25,steering=0.,axis='world_X',application='axis_out only')

def waveform(t,e):
    tau=t-e['start_s']
    envelope=max(0.,min(1.,tau/e['fade_s'],(e['duration_s']-tau)/e['fade_s']))
    return e['amplitude_n']*envelope**2*(3-2*envelope)*math.sin(2*math.pi*e['frequency_hz']*tau)

HOOK=r'''
local forceFile,forceTime,forceSamples
local originalStart=start
start=function(value)
  originalStart(value)
  if not running then return end
  forceTime=0;forceSamples=0
  forceFile=assert(io.open(job.output..'/node_perturbation.csv','w'))
  forceFile:write('physics_s,force_world_x_n,node_world_x,node_world_y,node_world_z,node_vx,node_vy,node_vz\n')
end
local originalFinish=finish
finish=function(state,reason)
  if forceFile then
    forceFile:flush();forceFile:close();forceFile=nil
    assert(jsonWriteFile(job.output..'/node_perturbation.json',{job_id=job.id,samples=forceSamples,complete=state=='completed',node=job.perturbed_node},true))
  end
  originalFinish(state,reason)
end
local originalStep=onPhysicsStep
onPhysicsStep=function(dt)
  originalStep(dt)
  if not running then return end
  forceTime=forceTime+dt;forceSamples=forceSamples+1
  local e=job.excitation;local tau=forceTime-e.start_s
  local envelope=math.max(0,math.min(1,tau/e.fade_s,(e.duration_s-tau)/e.fade_s))
  local force=e.amplitude_n*envelope*envelope*(3-2*envelope)*math.sin(2*math.pi*e.frequency_hz*tau)
  local node=byName[job.perturbed_node].cid;local p=position(node);local velocity=obj:getNodeVelocityVector(node)
  forceFile:write(string.format('%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g\n',forceTime,force,p.x,p.y,p.z,velocity.x,velocity.y,velocity.z))
  obj:applyForceVector(node,vec3(force,0,0))
end
'''

def instrument(source):return base.instrument(source).replace(base.HOOK,HOOK)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('--profile',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--force',required=True,type=float);p.add_argument('--corner',choices=['FL','FR'],default='FR');a=p.parse_args()
    import psutil
    settings=excitation(a.corner,a.force);m,folder=intake(a.manifest)
    a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    harness=ROOT/'dependencies/cad-calibration/Test Harness/frame_harness'
    paths=[a.manifest,Path(__file__),Path(base.__file__),Path(probe.__file__),*sorted(f for f in harness.rglob('*') if f.suffix in ('.py','.lua'))]
    before={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in paths}
    cancel=threading.Event();stopped=threading.Event();resources=[]
    result=dict(qualification_status='not_qualified',purpose=__doc__,manifest_sha256=before[str(a.manifest)],implementation=before)
    project=HarnessProject(userpath=a.profile,source=folder,runs=a.output.parent,test_timeout=300.)
    with probe.ProbeSession(project,'vehicle',cancel=cancel) as session:
        session.mode='null';mod=session.root/'mods/unpacked/vehicle_harness'
        recorder=mod/'lua/vehicle/extensions/vehicleharness/recorder.lua';recorder.write_text(instrument(recorder.read_text(encoding='utf-8')),encoding='utf-8')
        (a.output/'diagnostic-recorder.lua').write_bytes(recorder.read_bytes())
        (mod/'lua/ge/extensions/visuals.lua').write_text("return {new=function() local function noop() end; return {camera=noop,capture=noop,draw=noop,update=noop,dispose=noop} end}",encoding='utf-8')
        bridge=mod/'lua/ge/extensions/session_bridge.lua';source=bridge.read_text(encoding='utf-8');anchor="be:setEnabled(true);be:setSimulationTimeScale(1);status('spawning')"
        if source.count(anchor)!=1:raise ValueError('Stepping hook changed')
        bridge.write_text(source.replace(anchor,'be:setPhysicsDeterministic(true);'+anchor),encoding='utf-8')
        (a.output/'diagnostic-session-bridge.lua').write_bytes(bridge.read_bytes())
        expected,changed,written=stage_components(folder,mod/'vehicles'/m['model'],m['model'],[],a.output)
        result['physics_only']=probe.physics_only_fixture(mod/'vehicles'/m['model'],a.output,m['model'],changed)
        identity='node-perturbation-'+uuid.uuid4().hex;out=session.control/'results'/identity;out.mkdir(parents=True)
        job=dict(id=identity,model=m['model'],config=m['config'],duration=18.,gravity=-9.81,spawn_z=m['spawn_z'],scenario='node_perturbation',
            output='/settings/vehicle_harness/results/'+identity,manifest=m,motion_reference=reference(m),fixture_fixed_nodes=[],
            expected_beams=expected,changed_files=changed,staging_bytes=written,excitation=settings,perturbed_node=m['wheels'][a.corner]['nodes']['axis_out'])
        write_json(a.output/'job.json',job);write_json(a.output/'build_manifest.json',m)
        def monitor():
            low=None;start=time.monotonic()
            while not stopped.is_set():
                available=psutil.virtual_memory().available;now=time.monotonic();resources.append(dict(wall_s=now-start,available_ram_bytes=available))
                low=(low or now) if available<384*1024**2 else None
                if low is not None and now-low>5:result['resource_abort']='Available RAM below 384 MiB for five seconds';cancel.set()
                stopped.wait(1)
        watcher=threading.Thread(target=monitor,daemon=True);watcher.start()
        try:result['completion']=session.execute(job,a.output,out,capture=False)
        except Exception as error:result['error']=str(error);raise
        finally:
            session.close_process();stopped.set();watcher.join();session.archive_recording(out,a.output,archive_root=a.output.parent);session.archive_logs(a.output)
            result['sources_unchanged']=all(f.exists() and hashlib.sha256(f.read_bytes()).hexdigest()==before[str(f)] for f in paths)
            write_json(a.output/'probe.json',result);write_json(a.output/'resources.json',resources)
    print(json.dumps(dict(output=str(a.output),recording=result['completion']['status']),indent=2))

if __name__=='__main__':main()
