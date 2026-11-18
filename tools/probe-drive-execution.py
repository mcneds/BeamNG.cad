"""Nonqualifying Drive execution-mode experiment; never writes build receipts.

Uses the production ownership, staging, recorder, cancellation and shutdown paths.
Null-renderer probes replace the profile's visual helper with an explicitly
archived no-op. Optional deterministic stepping and neutral-settle controls are
reported separately; no vehicle properties or acceptance receipts are changed.
"""
import argparse
import csv
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / 'dependencies/cad-calibration/Test Harness'
sys.path.insert(0, str(ROOT/'tools'))
sys.path.insert(0, str(HARNESS))
from frame_harness.build import write_json
from frame_harness.models import HarnessProject
from frame_harness.session import DriveSession
from frame_harness.vehicle import intake, SCENARIOS
from frame_harness.vehicle_motion import reference
from frame_harness.component_tests import stage_components
from steady_speed_control import DURATION, settings as speed_settings, instrument as speed_instrument


class ProbeSession(DriveSession):
    def start(self, run):
        original = subprocess.Popen
        def launch(argv, *args, **kwargs):
            flags = {'rendered': [], 'headless': ['-headless'],
                     'null': ['-headless', '-gfx', 'null']}[self.mode]
            self.probe_argv = argv + flags
            return original(self.probe_argv, *args, **kwargs)
        with patch('frame_harness.session.subprocess.Popen', launch):
            super().start(run)
        self.launch['probe_mode'] = self.mode
        self.launch['argv'] = self.probe_argv


def strip_render_sections(parts):
    """Diagnostic copy only: physical JBeam declarations remain byte-equivalent as JSON values."""
    result=copy.deepcopy(parts);removed={}
    for name,part in result.items():
        removed[name]={key:len(part.get(key,[])) for key in ('flexbodies','props')}
        for key in ('flexbodies','props'):part.pop(key,None)
    return result,removed


def physics_only_fixture(vehicle,run,model,changed):
    vehicle=vehicle.resolve();reports={}
    for path in vehicle.glob('*.jbeam'):
        if not path.resolve().is_relative_to(vehicle):raise ValueError('Fixture path escapes owned vehicle')
        source=json.loads(path.read_bytes());part,removed=strip_render_sections(source)
        write_json(path,part);write_json(run/('diagnostic-physics-only-'+path.name),part)
        reports[path.name]=dict(removed=removed,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        name='/vehicles/'+model+'/'+path.name
        if name not in changed:changed.append(name)
    deleted=[]
    for path in vehicle.rglob('*.dae'):
        if not path.resolve().is_relative_to(vehicle):raise ValueError('Mesh path escapes owned vehicle')
        deleted.append(dict(path=path.relative_to(vehicle).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size))
        name='/vehicles/'+model+'/'+path.relative_to(vehicle).as_posix()
        path.unlink()
        if name not in changed:changed.append(name)
    return dict(scope='Owned staged fixture only; physical declarations preserved, render-only sections and DAE assets omitted. Equivalence and rendered acceptance remain separate.',jbeams=reports,removed_meshes=deleted)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest', type=Path)
    p.add_argument('--mode', choices=['rendered', 'headless', 'null'], required=True)
    p.add_argument('--profile', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--scenario', choices=list(SCENARIOS)+['steady_speed'], default='acceleration')
    p.add_argument('--target-speed', type=float, help='Required for steady_speed, in m/s (5 mph = 2.2352 m/s; maximum 15 m/s)')
    p.add_argument('--coast-after',type=float,help='Release both pedals after 20..45 seconds of steady_speed; retain drivetrain gear')
    p.add_argument('--startup-timeout', type=float, default=180)
    p.add_argument('--test-timeout',type=float,default=120,help='Wall-clock allowance; does not change the simulation duration')
    p.add_argument('--physics-only',action='store_true',help='Nonqualifying low-memory fixture without props/flexbodies or DAE assets')
    p.add_argument('--diagnostic-drop', action='store_true', help='Settling diagnostic: spawn the unchanged vehicle 3 m higher')
    p.add_argument('--neutral-settle', action='store_true', help='Nonqualifying isolation diagnostic: select Neutral for settle, preserving vehicle settings')
    p.add_argument('--deterministic', action='store_true', help='Explicit fixed 50 ms control cadence; physics remains 2000 Hz')
    p.add_argument('--frequency-window', type=float, nargs=2, metavar=('START','DURATION'), help='Bounded physics-step front suspension positions, diagnostic only')
    p.add_argument('--frequency-corners',nargs='+',choices=['FL','FR','RL','RR'],default=['FL','FR'],help='Corners included in bounded positions; at most 80 nodes total')
    p.add_argument('--frequency-loads',action='store_true',help='Also record bounded native beam loads and node forces in the frequency window')
    p.add_argument('--frequency-wheels',action='store_true',help='Also record native wheel angular velocities and commanded torques in the bounded window')
    p.add_argument('--frequency-carriers',action='store_true',help='Include every front carrier node in the bounded capture for internal force accounting')
    p.add_argument('--frequency-velocities',action='store_true',help='Record native node velocities to independently check force/acceleration balance')
    p.add_argument('--frequency-targets',action='store_true',help='Record native equivalent-tie hydro targets at each physics callback')
    p.add_argument('--frequency-routing',action='store_true',help='Aggregate incident axial forces by load source at front chassis hardpoints')
    a = p.parse_args()
    if (a.scenario=='steady_speed') != (a.target_speed is not None):p.error('Use --target-speed only with --scenario steady_speed')
    if a.scenario=='steady_speed' and not a.deterministic:p.error('Steady speed diagnostics require --deterministic for controller replay')
    if a.target_speed is not None:
        try:speed_settings(a.target_speed,a.coast_after)
        except ValueError as exc:p.error(str(exc))
    if a.coast_after is not None and a.scenario!='steady_speed':p.error('Coast requires steady_speed')
    duration=DURATION if a.scenario=='steady_speed' else SCENARIOS[a.scenario]
    if not 120<=a.test_timeout<=600:p.error('Test timeout must be between 120 and 600 seconds')
    if a.physics_only and a.mode!='null':p.error('Physics-only fixture requires the null renderer')
    if (a.frequency_loads or a.frequency_routing or a.frequency_wheels or a.frequency_carriers or a.frequency_velocities or a.frequency_targets) and not a.frequency_window:p.error('Frequency diagnostics require a frequency window')
    if a.diagnostic_drop and a.scenario!='settle':p.error('Drop requires settle scenario')
    if a.neutral_settle and a.scenario!='settle':p.error('Neutral isolation requires settle scenario')
    import psutil  # optional dependency of this experiment only
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=False)
    manifest, folder = intake(a.manifest)
    if a.frequency_window and not (0<=a.frequency_window[0] and 0<a.frequency_window[1]<=8 and sum(a.frequency_window)<duration):
        p.error('Frequency window must be at most eight seconds and finish before the scenario ends')
    before = {str(f.relative_to(HARNESS)): hashlib.sha256(f.read_bytes()).hexdigest()
              for f in (HARNESS/'frame_harness').rglob('*') if f.suffix in ('.py', '.lua')}
    manifest_hash = hashlib.sha256(a.manifest.read_bytes()).hexdigest()
    project = HarnessProject(userpath=a.profile, source=folder, runs=a.output.parent,
                             startup_timeout=a.startup_timeout,test_timeout=a.test_timeout)
    result = dict(mode=a.mode, qualification_status='not_qualified',
                  deterministic=a.deterministic,
                  neutral_settle=a.neutral_settle,
                  purpose='Unassisted steady-speed motion diagnostic, not vehicle acceptance' if a.scenario=='steady_speed' else 'Execution throughput experiment, not vehicle acceptance',
                  manifest_sha256=manifest_hash, implementation=before)
    samples = []; stopped = threading.Event(); start = time.monotonic()
    cancel = threading.Event()
    with ProbeSession(project, 'vehicle', cancel=cancel) as session:
        session.mode = a.mode
        if a.scenario=='steady_speed':
            target=session.root/'mods/unpacked/vehicle_harness/lua/vehicle/extensions/vehicleharness/recorder.lua'
            target.write_text(speed_instrument(target.read_text(encoding='utf-8')),encoding='utf-8')
            (a.output/'diagnostic_vehicle_recorder.lua').write_bytes(target.read_bytes())
            result['steady_speed']=speed_settings(a.target_speed,a.coast_after)
            result['controller_sha256']=hashlib.sha256((ROOT/'tools/steady_speed_control.py').read_bytes()).hexdigest()
        if a.neutral_settle:
            target=session.root/'mods/unpacked/vehicle_harness/lua/vehicle/extensions/vehicleharness/recorder.lua'
            recorder=target.read_text(encoding='utf-8')
            anchor="controller.mainController.shiftToGearIndex(job.scenario=='reverse' and -1 or 2)"
            if recorder.count(anchor)!=1:raise ValueError('Neutral diagnostic hook changed')
            recorder=recorder.replace(anchor,"controller.mainController.shiftToGearIndex(0)")
            target.write_text(recorder,encoding='utf-8')
            (a.output/'diagnostic_vehicle_recorder.lua').write_text(recorder,encoding='utf-8')
            result['control_override']={'gear':'N','staged_recorder_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
        if a.deterministic:
            target = session.root/'mods/unpacked/vehicle_harness/lua/ge/extensions/session_bridge.lua'
            bridge = target.read_text(encoding='utf-8')
            anchor = "be:setEnabled(true);be:setSimulationTimeScale(1);status('spawning')"
            if bridge.count(anchor) != 1: raise ValueError('Diagnostic stepping hook changed')
            bridge = bridge.replace(anchor, "be:setPhysicsDeterministic(true);"+anchor)
            target.write_text(bridge, encoding='utf-8')
            (a.output/'diagnostic-session-bridge.lua').write_text(bridge, encoding='utf-8')
        if a.mode == 'null':
            stub = "return {new=function() local function noop() end; return {camera=noop,capture=noop,draw=noop,update=noop,dispose=noop} end}\n"
            target = session.root/'mods/unpacked/vehicle_harness/lua/ge/extensions/visuals.lua'
            target.write_text(stub, encoding='utf-8')
            (a.output/'diagnostic-visuals.lua').write_text(stub, encoding='utf-8')
        identity = 'probe-' + uuid.uuid4().hex
        output = session.control/'results'/identity
        output.mkdir(parents=True)
        expected, changed, written = stage_components(folder,
            session.root/'mods/unpacked/vehicle_harness/vehicles'/manifest['model'],
            manifest['model'], [], a.output)
        if a.physics_only:
            result['physics_only']=physics_only_fixture(session.root/'mods/unpacked/vehicle_harness/vehicles'/manifest['model'],a.output,manifest['model'],changed)
            write_json(a.output/'physics_only_fixture.json',result['physics_only'])
        job = dict(id=identity, model=manifest['model'], config=manifest['config'],
            scenario=a.scenario, duration=duration, gravity=-9.81,
            spawn_z=manifest['spawn_z'], output='/settings/vehicle_harness/results/'+identity,
            manifest=manifest, motion_reference=reference(manifest), fixture_fixed_nodes=[],
            expected_beams=expected, changed_files=changed, staging_bytes=written)
        if a.scenario=='steady_speed':job['steady_speed']=speed_settings(a.target_speed,a.coast_after)
        if a.diagnostic_drop:
            job.update(spawn_z=job['spawn_z']+3.,drop_height_m=3.,diagnostic='drop')
            result['drop_height_m']=3.
        if a.frequency_window:
            import numpy as np
            # Deterministic farthest-point registration subset: bound file size
            # while retaining a spatially distributed, noncollinear chassis datum.
            chassis=sorted(manifest['chassis_nodes']);xyz=np.array([manifest['nodes'][n]['position'] for n in chassis])
            indices=[0]
            for _ in range(min(12,len(chassis))-1):
                distances=np.min(np.sum((xyz[:,None]-xyz[indices])**2,axis=2),axis=1)
                indices.append(int(np.argmax(distances)))
            datum=[chassis[i] for i in indices]
            selected=set(datum)
            for corner in dict.fromkeys(a.frequency_corners):
                mapping=job['motion_reference']['corners'][corner]
                selected.update(mapping['points'].values());selected.update(mapping['axis'])
            if a.frequency_carriers:
                for corner in ('FL','FR'):
                    owners=[o for o,r in manifest['component_roles'].items() if r in (corner.lower()+'_upright',corner.lower()+'_trailing_arm') and set(job['motion_reference']['corners'][corner]['axis'])<=set(manifest['mass_allocations'].get(o,{}))]
                    if len(owners)!=1:raise ValueError('One front carrier required for complete capture')
                    selected.update(manifest['mass_allocations'][owners[0]])
            if len(selected)>80:raise ValueError('Frequency capture exceeds 80-node bound')
            job['frequency_capture']=dict(start_s=a.frequency_window[0],duration_s=a.frequency_window[1],nodes=sorted(selected),chassis_nodes=datum,full_chassis_registration=True)
            if a.frequency_loads or a.frequency_routing:job['frequency_capture']['loads']=True
            if a.frequency_wheels:job['frequency_capture']['wheels']=True
            if a.frequency_carriers:job['frequency_capture']['complete_front_carriers']=True
            if a.frequency_velocities:job['frequency_capture']['velocities']=True
            if a.frequency_targets:job['frequency_capture']['actuator_targets']=True
            if a.frequency_routing:
                chassis=set(manifest['chassis_nodes'])
                names=sorted({n for c in ('FL','FR') for n in manifest['wheels'][c]['hardpoint_nodes'].values() if n in chassis})
                if not names or len(names)>16 or not set(names)<=selected:raise ValueError('Invalid bounded routing selection')
                job['frequency_capture']['routing_nodes']=names
        write_json(a.output/'job.json', job)
        write_json(a.output/'build_manifest.json', manifest)
        def monitor():
            low_since = None
            while not stopped.is_set():
                row = dict(wall_s=time.monotonic()-start,
                           available_ram_bytes=psutil.virtual_memory().available)
                if session.process:
                    try:
                        proc = psutil.Process(session.process.pid)
                        members = [proc] + proc.children(recursive=True)
                        row.update(pid=proc.pid, processes=len(members),
                            private_bytes=sum(x.memory_info().private for x in members),
                            working_bytes=sum(x.memory_info().rss for x in members))
                    except (psutil.NoSuchProcess, psutil.AccessDenied): pass
                samples.append(row)
                if row['available_ram_bytes'] < 384*1024**2:
                    low_since = low_since or time.monotonic()
                    if time.monotonic()-low_since > 5:
                        result['resource_abort'] = 'Available RAM below 384 MiB for five seconds'
                        cancel.set()
                else: low_since = None
                stopped.wait(1)
        worker = threading.Thread(target=monitor, daemon=True); worker.start()
        try:
            result['completion'] = session.execute(job, a.output, output, capture=a.mode!='null')
        except (Exception, KeyboardInterrupt) as exc:
            result['error'] = str(exc) or type(exc).__name__
            session.close_process()
        finally:
            stopped.set(); worker.join()
            result.update(wall_s=time.monotonic()-start, timings=session.last_timings,
                          launch=getattr(session, 'launch', None))
            session.close_process()
            session.archive_recording(output, a.output, archive_root=a.output.parent)
            session.archive_logs(a.output)
    after = {str(f.relative_to(HARNESS)): hashlib.sha256(f.read_bytes()).hexdigest()
             for f in (HARNESS/'frame_harness').rglob('*') if f.suffix in ('.py', '.lua')}
    result['sources_unchanged'] = before == after and manifest_hash == hashlib.sha256(a.manifest.read_bytes()).hexdigest()
    result['probe_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    telemetry = a.output/'vehicle.csv'
    if telemetry.is_file():
        rows = list(csv.DictReader(telemetry.open(encoding='utf-8')))
        times = [float(r['t']) for r in rows]
        result['telemetry'] = dict(samples=len(rows), last_simulated_s=times[-1] if times else None,
            finite=all(math.isfinite(float(v)) for r in rows for v in r.values()),
            increasing=all(b>a for a,b in zip(times,times[1:])))
    write_json(a.output/'resources.json', samples)
    write_json(a.output/'probe.json', result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('implementation','completion','physics_only')}, indent=2), flush=True)
    if not recording_succeeded(result):
        raise SystemExit(2)


def recording_succeeded(result):
    """CLI success means complete, unchanged evidence, never physical qualification."""
    return (result.get('completion',{}).get('status')=='completed' and
            result.get('sources_unchanged') is True and
            not result.get('error') and not result.get('resource_abort'))


if __name__ == '__main__': main()
