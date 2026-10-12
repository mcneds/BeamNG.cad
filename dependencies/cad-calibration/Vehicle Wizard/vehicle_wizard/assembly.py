from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

import numpy as np

from .project import sha256


class Cancelled(RuntimeError):pass


def import_assembly(project,progress=print,cancel=None):
    source=Path(project.data['assembly']);blender=Path(project.data['blender'])
    if not source.is_file():raise FileNotFoundError(source)
    if not blender.is_file():raise FileNotFoundError('Select a compatible Blender executable')
    digest=sha256(source);relative=Path('assets')/digest[:16];target=project.root/relative
    if not (target/'index.json').exists():
        target.mkdir(parents=True,exist_ok=True)
        command=[str(blender),'--factory-startup','--disable-autoexec','--background',str(source),
                 '--python',str(Path(__file__).with_name('blender_extract.py')),'--',str(target)]
        options={}
        if os.name=='nt':options['creationflags']=subprocess.CREATE_NO_WINDOW
        with (target/'import.log').open('w',encoding='utf-8') as logfile:
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',**options)
            stopped=threading.Event()
            def watch():
                while not stopped.wait(.2):
                    if cancel and cancel.is_set():process.terminate();return
            watcher=threading.Thread(target=watch,daemon=True);watcher.start()
            try:
                for line in process.stdout:logfile.write(line);logfile.flush();progress(line.strip())
                code=process.wait()
            finally:stopped.set();watcher.join(timeout=1)
        if cancel and cancel.is_set():raise Cancelled('Assembly import cancelled; project assignments preserved')
        if code or not (target/'index.json').exists():raise RuntimeError('Blender import failed; see '+str(target/'import.log'))
    if sha256(source)!=digest:raise RuntimeError('Source assembly changed during import; reimport the saved file')
    if project.data['assembly_sha256'] and project.data['assembly_sha256']!=digest:
        project.checkpoint('Reimport assembly');project.data['alignment_confirmed']=False
        for corner in project.data['corners'].values():corner['confirmed']=False
    project.data['assembly_sha256']=digest;project.data['asset_index']=(relative/'index.json').as_posix();project.save()
    return project.index()


def mesh_arrays(project,obj):
    path=project.root/Path(project.data['asset_index']).parent/obj['file']
    with np.load(path) as data:return data['vertices'].copy(),data['faces'].copy()


def suggest_groups(index):
    groups={}
    for obj in index['objects']:
        for collection in obj['collections']:groups.setdefault(collection,[]).append(obj['id'])
    return groups
