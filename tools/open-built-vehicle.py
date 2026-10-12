"""Open a verified package for manual review in an exclusively owned Drive profile.

This is not a qualification run. The helper retains the profile lock until the
game closes, and cancellation shuts down only the process it launched.
"""
import argparse,json,sys,time,uuid,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.models import HarnessProject
from frame_harness.session import DriveSession
from frame_harness.vehicle import intake
from frame_harness.component_tests import stage_components
from frame_harness.build import write_json

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path);parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--game',type=Path,default=Path('D:/SteamLibrary/steamapps/common/BeamNG.drive'))
    parser.add_argument('--paused',action='store_true')
    parser.add_argument('--close-after-capture',action='store_true',help='Close the owned review process once evidence is archived')
    a=parser.parse_args()
    manifest,folder=intake(a.manifest)
    run=a.manifest.resolve().parent/('manual-review-'+uuid.uuid4().hex[:8]);run.mkdir()
    project=HarnessProject(game=a.game,userpath=a.profile,source=folder,runs=run,startup_timeout=180)
    with DriveSession(project,'vehicle') as session:
        bridge=session.root/'mods/unpacked/vehicle_harness/lua/ge/extensions/session_bridge.lua'
        text=bridge.read_text(encoding='utf-8');anchor="    vehicleId=id;visuals="
        if text.count(anchor)!=1:raise ValueError('Review launch hook changed')
        injected="""    vehicleId=id
    if job.scenario=='manual-review' then
      be:enterVehicle(0,vehicle)
      core_camera.setByName(0,'orbit',true)
      if job.paused then be:setSimulationTimeScale(1);be:setEnabled(false) end
      visuals=require('/mods/unpacked/vehicle_harness/lua/ge/extensions/visuals').new(job,vehicle,'vehicle')
      visuals.camera(1);visuals.capture('final',0)
      status('interactive');return
    end
    visuals="""
        text=text.replace(anchor,injected)
        anchor="      if not ok then visuals.dispose();visuals=nil;status('failed','Camera/capture error: '..tostring(err)) end"
        if text.count(anchor)!=1:raise ValueError('Review capture completion hook changed')
        text=text.replace(anchor,anchor+"\n      if ok and phase=='interactive' and visuals.final and not visuals.active and #visuals.queue==0 then visuals.dispose();visuals=nil;core_camera.setByName(0,'orbit',true) end")
        bridge.write_text(text,encoding='utf-8')
        expected,changed,written=stage_components(folder,session.root/'mods/unpacked/vehicle_harness/vehicles'/manifest['model'],manifest['model'],[],run)
        capture_relative=Path('settings/vehicle_harness/manual')/run.name
        capture_root=session.root/capture_relative;capture_root.mkdir(parents=True)
        job=dict(id=run.name,model=manifest['model'],config=manifest['config'],scenario='manual-review',
                 gravity=-9.81,spawn_z=manifest['spawn_z'],manifest=manifest,paused=a.paused,
                 output='/'+capture_relative.as_posix(),session_id=session.id,
                 changed_files=changed,staging_bytes=written,expected_beams=expected)
        session.start(run);session.command(action='run',job=job)
        started=time.monotonic();ready=False;captured=False
        while session.process.poll() is None:
            session.check_cancel()
            try:state=json.loads((session.control/'status.json').read_text())
            except (OSError,ValueError):state={}
            if state.get('session_id')==session.id and state.get('state')=='failed':raise RuntimeError(state.get('reason'))
            if not ready and state.get('session_id')==session.id and state.get('state')=='interactive':
                ready=True;write_json(run/'ready.json',dict(**session.launch,model=manifest['model'],paused=a.paused,qualification='manual review only'))
                print('VEHICLE_OPEN '+str(run/'ready.json'),flush=True)
            if ready and not captured:
                try:capture=json.loads((capture_root/'capture_status.json').read_text())
                except (OSError,ValueError):capture={}
                if capture.get('done'):
                    shutil.copytree(capture_root,run/'captures');captured=True
                    print('VEHICLE_CAPTURE '+str(run/'captures'),flush=True)
                    if a.close_after_capture:break
            if not ready and time.monotonic()-started>project.startup_timeout:raise TimeoutError('Manual vehicle spawn timed out')
            time.sleep(1)

if __name__=='__main__':main()
