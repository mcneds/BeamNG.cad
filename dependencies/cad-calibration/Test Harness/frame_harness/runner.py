from __future__ import annotations

import contextlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .build import SOURCES, build_candidate, sha256, write_json
from .models import HarnessProject, ParameterSet, RunResult, TestScenario

PACKAGE = Path(__file__).parent


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def validate_recording(directory, job, completion):
    """A completion flag alone is insufficient: disk-full writes can silently truncate CSVs."""
    if completion.get("job_id") != job["id"]:
        raise RuntimeError("Recording job identity differs")
    samples, steps = completion.get("trajectory_samples", 0), completion.get("physics_steps", 0)
    if samples < 2 or steps < 1 or completion.get("simulated_seconds", 0) < job["scenario"]["duration"]:
        raise RuntimeError("Recording ended before the requested duration")
    expected = {"nodes.csv": samples*job["expected_nodes"], "beams.csv": samples*job["expected_beams"],
                "loads.csv": samples, "probes.csv": steps*len(job["scenario"]["load_nodes"])}
    for filename, rows in expected.items():
        file = directory/filename
        count = 0
        with file.open("rb") as stream:
            while chunk := stream.read(1024*1024):
                count += chunk.count(b"\n")
        if count-1 != rows:
            raise RuntimeError(f"Incomplete telemetry: {filename} has {count-1} rows; expected {rows}")


def check_recording_space(root, run):
    # Leave room for trajectory output, archived copies, and normal system operation.
    for path in (root, run):
        free = shutil.disk_usage(path).free
        if free < 1024**3:
            raise RuntimeError(f"Insufficient disk space for recording at {path}: {free/1024**3:.2f} GiB free; require 1 GiB")


def saved_recording_failure(run):
    """Identify recoverable recording failures without masking physical failures."""
    if (run/'compact-evidence.json').exists():
        from .retention import compact_recording_failure
        return compact_recording_failure(run)
    location = read_json(run/"telemetry_location.json")
    if not location:
        return 'Missing archived telemetry location'
    directory = run/location["directory"]
    attempt = location["directory"].removeprefix("attempt-")
    completion = read_json(directory/"completion.json") or {}
    attempt_result = read_json(directory/"attempt_result.json") or {}
    if attempt_result.get("failure_kind") == "infrastructure":
        return attempt_result.get("reason", "Infrastructure failure")
    if completion.get("status") != "completed" and (read_json(run/'result.json') or {}).get('status') == 'completed':
        return 'Missing or incomplete archived recording'
    if completion.get("status") == "completed":
        job = read_json(run/f"job-{attempt}.json")
        try:
            if not job:
                raise RuntimeError("Missing archived recording job")
            validate_recording(directory, job, completion)
        except (OSError, RuntimeError) as exc:
            return str(exc)
    return None


def doctor(project: HarnessProject):
    checks = {"game_executable": project.executable.is_file(),
              "smallgrid": (project.game / "content/levels/smallgrid.zip").is_file(),
              "source_files": all((project.source / n).is_file() for n in SOURCES),
              "lua_startup": False, "physics_hook": False}
    for key, relative, search in (
        ("lua_startup", "lua/ge/client/parseArgs.lua", 'arg == "-lua"'),
        ("physics_hook", "lua/vehicle/main.lua", 'extensionsHook("onPhysicsStep"')):
        file = project.game / relative
        checks[key] = file.is_file() and search in file.read_text(encoding="utf-8")
    packages = {}
    for name in ("numpy", "matplotlib"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"ok": all(checks.values()) and all(packages.values()), "checks": checks,
            "project": project.to_dict(), "python": sys.executable, "packages": packages}


def prepare_userpath(project):
    root = project.userpath.resolve()
    marker = root / ".frame-harness-owned"
    if root.exists() and any(root.iterdir()) and not marker.exists():
        raise ValueError(f"Refusing an existing non-harness user folder: {root}")
    root.mkdir(parents=True, exist_ok=True)
    marker.touch()
    # Drive 0.39 treats -userpath as a base and mounts its current/ child.
    root = root / "current"
    root.mkdir(exist_ok=True)
    settings = read_json(root / "settings/settings.json") or {}
    settings.update({
        "GraphicDisplayModes": "Window", "GraphicDisplayResolutions": "1280 720",
        "GraphicOverallQuality": "Lowest", "fpsLimitEnabled": True, "fpsLimit": 60,
        "PostFXDOFGeneralEnabled": False, "GraphicAntialias": 0,
        "fpsLimitBackgroundEnabled": False, "AudioMasterVol": 0,
        "telemetry": "disable", "onlineFeatures": "disable", "disableModsAfterUpdate": False})
    write_json(root / "settings/settings.json", settings)
    extension = root / "mods/unpacked/frame_harness/lua"
    for vm, name in (("ge", "bridge"), ("vehicle", "recorder")):
        target = extension / vm / "extensions/frameharness" / (name + ".lua")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PACKAGE / "lua" / (name + ".lua"), target)
    return root


@contextlib.contextmanager
def exclusive_userpath(project):
    project.userpath.mkdir(parents=True, exist_ok=True)
    lock = project.userpath / ".runner.lock"
    with lock.open("a+b") as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b"0"); stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Another harness runner owns this user folder") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def spawn_height(scenario, nodes, part):
    if scenario.gravity == 0 or scenario.fixed_nodes:
        return 3.0
    # Drive places the reference node at the requested height, not CAD z=0.
    reference = part['refNodes'][1][0]
    return .02+nodes[reference]['position'][2]-min(n['position'][2] for n in nodes.values())


def run_attempt(project, run, scenario, manifest, attempt, session=None):
    if session is None:
        from .session import DriveSession
        with DriveSession(project) as active:
            return run_attempt(project,run,scenario,manifest,attempt,active)
    session.retire()
    staging_started=time.monotonic()
    root = project.userpath.resolve() / "current"
    check_recording_space(root, run)
    vehicle = root / "mods/unpacked/frame_harness/vehicles/fh_mochi"
    # Only remove our exact owned mod subtree, never user mods or arbitrary computed paths.
    allowed = root / "mods/unpacked/frame_harness"
    if not vehicle.resolve().is_relative_to(allowed.resolve()) or not (root.parent / ".frame-harness-owned").is_file():
        raise ValueError("Unsafe staging destination")
    from .assets import stage_vehicle
    changed_files, staged_bytes=stage_vehicle(run/'vehicle',vehicle,assets=manifest.get('shared_assets'))
    staging_seconds=time.monotonic()-staging_started
    attempt_id = f"{run.name}-{attempt}"
    output = root / "settings/frame_harness/results" / attempt_id
    output.mkdir(parents=True)
    job = {"id": attempt_id, "scenario": asdict(scenario),
           "output": f"/settings/frame_harness/results/{attempt_id}", "os_output": output.as_posix(),
           "nodes": manifest["nodes"], "beams": manifest["beams"], "expected_nodes": len(manifest["nodes"]),
           "expected_beams": manifest["beam_count"],
           "expected_render_regions": manifest.get('expected_render_regions',0),
           "spawn_z": spawn_height(scenario,manifest['nodes'],read_json(vehicle/manifest.get('vehicle_file','mochi.jbeam'))[manifest.get('part','mochi')])}
    job["scenario"]["load_vectors"] = scenario.resolved_load_vectors()
    write_json(root / "settings/frame_harness/job.json", job)
    write_json(run / f"job-{attempt}.json", job)
    job.update(model='fh_mochi',config='base.pc',session_id=session.id,
               changed_files=changed_files)
    write_json(run / f"job-{attempt}.json", job)
    result=None
    execution_started=time.monotonic()
    try:
        result=session.execute(job,run,output,capture=scenario.capture)
        if result.get('status')=='completed': validate_recording(output,job,result)
    except (OSError,RuntimeError,TimeoutError) as exc:
        result={'status':'failed','reason':str(exc),'job_id':attempt_id,'failure_kind':'infrastructure'}
        session.close_process()
    finally:
        target = run / f"attempt-{attempt}"
        if output.exists():
            if (output.resolve().parent!=(root/'settings/frame_harness/results').resolve() or
                target.resolve().parent!=run.resolve() or not (root.parent/'.frame-harness-owned').is_file()):
                raise ValueError('Unsafe recording archive path')
            # One archive is sufficient. Keeping a second copy in the game profile
            # doubled telemetry storage even after the test report was removed.
            shutil.move(str(output),str(target))
        else:
            target.mkdir()
        session.archive_logs(target)
        write_json(target / "attempt_result.json", result)
        write_json(target/'timings.json',dict(staging_seconds=staging_seconds,staged_bytes=staged_bytes,
            execution_seconds=time.monotonic()-execution_started,phases=getattr(session,'last_timings',{})))
    return result, target


def run_test(project: HarnessProject, scenario: TestScenario, parameters: ParameterSet | None = None,
             *, analyze=True, retries=1, session=None, save_report=True) -> RunResult:
    started=time.monotonic(); preparation_started=started
    timings={}
    parameters = parameters or ParameterSet()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_id = f"{stamp}-{scenario.name}-{uuid.uuid4().hex[:6]}"
    run = project.runs.resolve() / run_id
    run.mkdir(parents=True)
    result = RunResult(run_id, str(run), "preparing", scenario.name, parameters.name)
    write_json(run / "result.json", asdict(result))
    write_json(run / "experiment.json", {"project": project.to_dict(), "scenario": asdict(scenario),
                                        "parameters": asdict(parameters), "python": sys.version})
    # Include the measurement implementation, not just the material implementation.
    shared=getattr(session,'assets',None)
    if shared is not None:
        shared.snapshot({p.relative_to(PACKAGE).as_posix():p for p in PACKAGE.rglob('*')
                         if p.suffix in ('.py','.lua')},run/'shared-harness.json')
    else:
        shutil.copytree(PACKAGE, run / "harness_source", ignore=shutil.ignore_patterns("__pycache__"))
    print(f"Run {run_id}: {parameters.name}", flush=True)
    try:
        manifest = build_candidate(project, run, parameters, scenario,shared=shared)
        timings['preparation_seconds']=time.monotonic()-preparation_started
        if not project.executable.is_file():
            raise FileNotFoundError(project.executable)
        from .session import DriveSession
        with (contextlib.nullcontext(session) if session is not None else DriveSession(project)) as active:
            for attempt in range(retries + 1):
                state, telemetry = run_attempt(project, run, scenario, manifest, attempt, active)
                result.status = state["status"]
                result.failure_reason = state.get("reason") or None
                if state["status"] in ("completed", "unstable") or state.get("failure_kind") != "infrastructure" or attempt == retries:
                    write_json(run / "telemetry_location.json", {"directory": telemetry.name})
                    break
                print(f"  Retry after: {result.failure_reason}", flush=True)
        if analyze and (telemetry / "metadata.json").exists() and (telemetry / "nodes.csv").exists():
            from .report import create_report, telemetry_cache
            analysis_started=time.monotonic()
            with telemetry_cache():
                result.metrics = create_report(run,render=False)
                game_log=telemetry/'beamng.log'
                mesh_errors=[line.strip() for line in game_log.read_text(encoding='utf-8',errors='replace').splitlines()
                             if any(marker in line for marker in ('FLEXBODY ERROR','Failed to get render mesh','unable to create flexmesh'))] if game_log.exists() else []
                result.metrics['mesh_load_errors']=mesh_errors
                result.metrics['mesh_load_valid']=not mesh_errors
                if manifest.get('expected_render_regions',0):
                    skin=read_json(telemetry/'skin_state.json') or {}
                    removed=skin.get('removed',[])
                    valid=skin.get('region_count')==manifest['expected_render_regions'] and all(skin.get('visibility_results',{}).get(n) is True for n in removed)
                    result.metrics.update(render_controller_valid=valid,render_regions_removed=len(removed))
                    if not valid:
                        result.status='invalid_measurement'
                        result.failure_reason='CAD render controller evidence missing or visibility update unconfirmed'
                if scenario.capture:
                    capture = read_json(telemetry/'capture_status.json') or {}
                    result.metrics['capture_complete'] = bool(capture.get('done') and capture.get('success') and all((telemetry/('final-'+v+'.png')).exists() for v in ('front','side','oblique')))
                if scenario.expected_damage:
                    from .damage import damage_report
                    result.metrics.update(damage_report(run,render=False))
                    write_json(run/'metrics.json',result.metrics)
                else:
                    write_json(run/'metrics.json',result.metrics)
                if result.metrics.get("position_velocity_consistent") is False:
                    result.status = "invalid_measurement"
                    result.failure_reason = "Position/velocity cross-check failed; exclude this run from comparisons"
                if result.metrics.get("support_max_motion_m", 0) > 5e-6:
                    result.status = "invalid_measurement"
                    result.failure_reason = "Fixed-support readback moved by more than 5 micrometres; exclude this run"
                if result.metrics.get("applied_force_consistent") is False:
                    result.status = "invalid_measurement"
                    result.failure_reason = "Recorded force vectors do not match the requested load"
                if result.status=='completed' and scenario.name in ('flex','torsion') and not result.metrics.get('hold_settled'):
                    result.status='unstable'
                    result.failure_reason='Load hold did not settle; stiffness response is not qualified'
                timings['analysis_seconds']=time.monotonic()-analysis_started
                if save_report or result.status!='completed':
                    render_started=time.monotonic()
                    create_report(run,render=True)
                    if scenario.expected_damage: damage_report(run,render=True)
                    timings['report_seconds']=time.monotonic()-render_started
                write_json(run/'metrics.json',result.metrics)
    except KeyboardInterrupt:
        result.status = "cancelled"
        result.failure_reason = "Interrupted by operator"
    except Exception as exc:
        result.status = "failed"
        result.failure_reason = f"{type(exc).__name__}: {exc}"
        import traceback
        (run / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
    timings['total_seconds']=time.monotonic()-started
    timings['simulated_seconds']=result.metrics.get('recorded_seconds',0)
    timings['bytes_written']=sum(p.stat().st_size for p in run.rglob('*') if p.is_file())
    timings['attempts']=[read_json(p) for p in sorted(run.glob('attempt-*/timings.json'))]
    result.metrics['performance']=timings
    write_json(run/'metrics.json',result.metrics)
    write_json(run/'timings.json',timings)
    write_json(run / "result.json", asdict(result))
    print(f"  {result.status}: {run}" + (f" ({result.failure_reason})" if result.failure_reason else ""), flush=True)
    return result
