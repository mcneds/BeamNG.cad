"""Exclusive, process-owned Drive session shared by a batch of test jobs."""
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from .build import write_json
from .progress import emit
from .capture import usable_capture


class DriveSession:
    def __init__(self, project, kind='frame', cancel=None):
        self.project=project; self.kind=kind; self.cancel=cancel
        self.id=uuid.uuid4().hex; self.process=None; self.log=None; self.lock=None; self.log_offsets={}
        self.namespace=kind+'_harness'
        from .assets import BatchAssets
        self.assets=BatchAssets(project.runs.resolve().parent)
        self.last_timings={}
        self.visible_for_evidence=kind=='vehicle'

    def __enter__(self):
        from .runner import exclusive_userpath, prepare_userpath
        root=self.project.userpath.resolve(); marker=root/'.frame-harness-owned'
        if root.exists() and any(root.iterdir()) and not marker.exists():
            raise ValueError('Refusing a non-harness test profile: '+str(root))
        root.mkdir(parents=True,exist_ok=True); marker.touch()
        self.lock=exclusive_userpath(self.project); self.lock.__enter__()
        try:
            self.root=prepare_userpath(self.project)
            self.control=self.root/'settings'/self.namespace
            self.control.mkdir(parents=True,exist_ok=True)
            package=Path(__file__).parent/'lua'
            mod=self.root/'mods/unpacked'/self.namespace
            for vm,name in [('ge','bridge'),('vehicle','recorder')]:
                src=package/((('vehicle_' if self.kind=='vehicle' else '')+name)+'.lua')
                dst=mod/'lua'/vm/'extensions'/(self.kind+'harness')/(name+'.lua')
                dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
            for name in ('session_bridge.lua','visuals.lua'):
                dst=mod/'lua/ge/extensions'/name; shutil.copy2(package/name,dst)
            if self.kind=='vehicle':
                shutil.copy2(package/'component_recorder.lua',mod/'lua/vehicle/extensions/vehicleharness/component_recorder.lua')
                shutil.copy2(package/'frequency_recorder.lua',mod/'lua/vehicle/extensions/vehicleharness/frequency_recorder.lua')
            return self
        except BaseException:
            self.lock.__exit__(None,None,None); self.lock=None; raise

    def check_cancel(self):
        if (self.cancel and self.cancel.is_set()) or (os.environ.get('BEAMNG_CAD_CANCEL') and Path(os.environ['BEAMNG_CAD_CANCEL']).exists()):
            raise KeyboardInterrupt

    def command(self, **data):
        # Atomic replacement prevents the game from reading a half-written job.
        file=self.control/'control.json'; temp=file.with_suffix('.tmp')
        write_json(temp,dict(session_id=self.id,**data))
        deadline=time.monotonic()+3
        while True:
            try:
                os.replace(temp,file)
                return
            except PermissionError as error:
                # Windows readers can briefly hold the destination without delete sharing.
                # Keep atomic publication; never expose a partially rewritten command.
                if getattr(error,'winerror',None) not in (5,32,33) or time.monotonic()>=deadline:
                    raise
                if data.get('action')!='quit':self.check_cancel()
                time.sleep(.02)

    def retire(self):
        from .runner import read_json
        self.check_cancel()
        if self.process is None:
            self.log_offsets={}; return
        if self.process.poll() is not None:
            self.close_process(); return
        self.command(action='retire')
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            self.check_cancel()
            state=read_json(self.control/'status.json') or {}
            if state.get('session_id')==self.id and state.get('state')=='ready':
                self.log_offsets={name:(self.root/name).stat().st_size for name in ('beamng.log','beamng-launcher.log') if (self.root/name).is_file()}
                return
            if self.process.poll() is not None: break
            time.sleep(.1)
        self.close_process()
        raise RuntimeError('Previous vehicle did not retire; owned session closed')

    def start(self, run):
        if self.process is not None: return
        for name in ('status.json','heartbeat.json','control.json'):
            (self.control/name).unlink(missing_ok=True)
        write_json(self.control/'session.json',{'session_id':self.id})
        argv=[str(self.project.executable),'-userpath',str(self.project.userpath.resolve()),'-lua',
              "extensions.addModulePath('/mods/unpacked/"+self.namespace+"/lua/ge/extensions/');extensions.load('"+self.kind+"harness/bridge')"]
        temporary=self.project.userpath.resolve()/'temp'; temporary.mkdir(exist_ok=True)
        options={'env':os.environ|{'TEMP':str(temporary),'TMP':str(temporary)}}
        if os.name=='nt':
            startup=subprocess.STARTUPINFO(); startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
            # Rendered evidence needs a visible, non-activating window.
            startup.wShowWindow=4 if self.visible_for_evidence else 0
            options['startupinfo']=startup
        self.log=(run/('session-'+self.id+'.log')).open('w',encoding='utf-8')
        self.process=subprocess.Popen(argv,cwd=self.project.game,stdout=self.log,stderr=subprocess.STDOUT,**options)
        self.launch={'argv':argv,'pid':self.process.pid,'session_id':self.id}

    def execute(self, job, run, output, capture=True):
        from .runner import read_json
        self.start(run)
        job['session_id']=self.id
        write_json(run/'session.json',self.launch)
        self.command(action='run',job=job)
        started=time.monotonic(); recording=None; capture_deadline=None; previous=None
        phase_start=started; self.last_timings={}; last_progress=None; last_emit=0
        while True:
            self.check_cancel()
            now=time.monotonic()
            if self.process.poll() is not None: raise RuntimeError('Owned BeamNG process exited')
            state=read_json(self.control/'status.json') or {}
            if state.get('session_id')==self.id and state.get('job_id') in (None,job['id']):
                phase=state.get('state')
                if phase!=previous:
                    if previous is not None:
                        self.last_timings[previous]=self.last_timings.get(previous,0)+now-phase_start
                    phase_start=now
                    print('  Drive: '+str(phase),flush=True); previous=phase
                if phase=='recording' and recording is None: recording=now
                if phase=='failed':
                    failed_recording=read_json(output/'completion.json')
                    if failed_recording and failed_recording.get('job_id')==job['id'] and failed_recording.get('session_id')==self.id and failed_recording.get('status')!='completed':
                        # Preserve the recorder's final measurements on a failed
                        # run; the bridge failure is not a replacement record.
                        return failed_recording
                    raise RuntimeError(state.get('reason','Vehicle load failed'))
            else: phase='starting'
            progress=read_json(output/'progress.json') or {}
            duration=job.get('duration') or job['scenario']['duration']
            progress_key=('capture' if capture_deadline else phase,progress.get('simulated_seconds'))
            if progress_key!=last_progress or now-last_emit>=5:
                emit(progress_key[0],completed=progress_key[1],total=duration,detail=job['id'],elapsed=now-started)
                last_progress=progress_key;last_emit=now
            completion=read_json(output/'completion.json')
            if completion:
                if completion.get('job_id')!=job['id'] or completion.get('session_id')!=self.id:
                    raise RuntimeError('Recording session/job identity differs')
                if not capture:
                    self.last_timings[previous or 'recording']=self.last_timings.get(previous or 'recording',0)+now-phase_start
                    return completion
                captures=read_json(output/'capture_status.json') or {}
                if captures.get('job_id')==job['id'] and captures.get('session_id')==self.id and captures.get('done'):
                    if not captures.get('success'): raise RuntimeError('Required evidence capture failed')
                    required=captures.get('required',{})
                    if not required.get('final'): raise RuntimeError('Missing final capture')
                    for label in required:
                        for view in (['front','side','oblique'] if self.kind=='frame' else ['']):
                            image=output/(label+('-'+view if view else '')+'.png')
                            metadata=read_json(Path(str(image)+'.json')) or {}
                            if not usable_capture(image) or not metadata.get('success') or metadata.get('job_id')!=job['id']:
                                raise RuntimeError('Incomplete, blank or invalid evidence image: '+image.name)
                    self.last_timings['capture_tail']=now-capture_deadline+45 if capture_deadline else 0
                    self.last_timings[previous or 'recording']=self.last_timings.get(previous or 'recording',0)+now-phase_start
                    return completion
                if capture_deadline is None: capture_deadline=now+45
                if now>capture_deadline: raise TimeoutError('Evidence capture timed out')
            if recording is None and now-started>self.project.startup_timeout: raise TimeoutError('Vehicle startup timed out')
            if recording is not None and not capture_deadline and now-recording>max(self.project.test_timeout,duration*6):
                raise TimeoutError('Physics recording timed out')
            time.sleep(.25)

    def archive_logs(self, target):
        for name in ('beamng.log','beamng-launcher.log'):
            source=self.root/name
            if source.is_file():
                with source.open('rb') as stream:
                    stream.seek(self.log_offsets.get(name,0))
                    (target/name).write_bytes(stream.read())

    def archive_recording(self, output, target, *, archive_root=None):
        """Transfer one completed owned recording, without leaving a second copy."""
        output=Path(output);target=Path(target)
        profile=self.project.userpath.resolve()
        expected=profile/'current/settings'/self.namespace/'results'
        if not (profile/'.frame-harness-owned').is_file():
            raise ValueError('Recording profile is not owned')
        if (output.resolve()!=output.absolute() or output.resolve().parent!=expected.resolve()
                or expected.resolve()!=expected.absolute()):
            raise ValueError('Recording must be directly inside the owned results directory')
        archive_root=Path(archive_root or self.project.runs).absolute()
        if (archive_root.resolve()!=archive_root or target.resolve()!=target.absolute() or target.resolve().parent!=archive_root
                or target.resolve().is_relative_to(profile) or not target.is_dir()):
            raise ValueError('Archive must be a separate run inside the configured runs directory')
        files=list(output.iterdir())
        # Preflight every entry before the first move: never partially overwrite an archive.
        for source in files:
            if source.resolve()!=source.absolute() or not source.is_file():
                raise ValueError('Unexpected linked or nested recording entry')
            if (target/source.name).exists():
                raise ValueError('Archive entry already exists: '+source.name)
        for source in files:shutil.move(str(source),str(target/source.name))
        output.rmdir()

    def close_process(self):
        if self.process is not None and self.process.poll() is None:
            try:self.command(action='quit')
            except OSError:
                # A locked command file must not strand the process we own.
                self.process.terminate()
            try: self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try: self.process.wait(5)
                except subprocess.TimeoutExpired: self.process.kill(); self.process.wait(5)
        self.process=None
        if self.log: self.log.close(); self.log=None

    def __exit__(self,*exc):
        try: self.close_process()
        finally:
            if self.lock: self.lock.__exit__(*exc); self.lock=None
