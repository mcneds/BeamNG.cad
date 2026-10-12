"""Refresh an isolated cached CAD input from saved, verified native material edits.

Retains the archived assembly pose and meshes. Requires unchanged native unit-
density moments, current source-part hashes, and current SolidWorks library
hashes. Never changes an archived generation or its qualification evidence.
"""
import argparse,copy,hashlib,json,shutil,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from frame_harness.materials import load_snapshot


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')


def refresh(project_path,audits,catalog_path,output):
    if output.exists():raise FileExistsError('Use a new material input directory')
    project=read(project_path);records={};sources={}
    for path in audits:
        sources[str(path.resolve())]=digest(path)
        for entry in read(path):
            if entry['status']!='saved_and_reopened_verified':raise ValueError('Unverified native edit: '+entry['path'])
            if digest(entry['path'])!=entry['after_sha256']:raise ValueError('Source part changed after readback: '+entry['path'])
            records[str(Path(entry['path']).resolve()).lower()]=entry
    catalog={v['name']:v for v in read(catalog_path)}
    for item in catalog.values():
        if digest(item['database'])!=item['database_sha256']:raise ValueError('SolidWorks material database changed')
    prepared=[];report={}
    for comp in project['Components']:
        if not comp.get('GeometryDirectory'):continue
        source=Path(comp['GeometryDirectory']);geometry=read(source/'geometry.json');snapshot=read(source/'material-snapshot.json')
        materials={v['body_id']:v for v in snapshot['bodies']};changed=[]
        for mesh in geometry['Meshes']:
            entry=records.get(str(Path(mesh['SourceDocument']).resolve()).lower())
            if entry is None:continue
            before={v['body']:v for v in entry['before']};after={v['body']:v for v in entry['after']}
            name=mesh['Body']
            if name not in before or name not in after:raise ValueError('Body missing from native readback: '+name)
            for row in (before[name],after[name]):
                if not np.allclose(mesh['NativeUnitDensityProperties'],row['unit_density_properties'],rtol=1e-8,atol=1e-12):
                    raise ValueError('Geometry changed; fresh CAD export required: '+name)
            native=after[name];old=materials[mesh['Id']]
            if native['name']==before[name]['name'] and old.get('name')==native['name']:
                continue
            if not native['name']:continue # Unassigned rim/other bodies remain explicitly unassigned.
            if native['name'] not in catalog:raise ValueError('Material missing from captured catalog: '+native['name'])
            library=catalog[native['name']]
            if Path(native['database']).stem.lower()!=Path(library['database']).stem.lower():raise ValueError('Native library differs')
            replacement=copy.deepcopy(library)
            replacement.update({k:old[k] for k in ('body_id','body','component','configuration')})
            replacement['assignment']=native['assignment'];materials[mesh['Id']]=replacement
            density=library['density_kg_m3'];mesh['DensityKgM3']=density
            mesh['MassKg']=None if mesh['BodyKind']=='surface' else mesh['NativeUnitDensityProperties'][3]*density
            mesh['MassSource']='Unchanged native CAD volume times saved/reopened SolidWorks material density'
            changed.append(dict(body=mesh['Id'],name=name,material=native['name'],density_kg_m3=density,
                source_part_sha256=entry['after_sha256']))
        if not changed:continue
        snapshot['bodies']=[materials[v['body_id']] for v in snapshot['bodies']]
        prepared.append((comp,source,geometry,snapshot))
        report[comp['Id']]=dict(name=comp['Name'],bodies=changed,source_geometry_sha256=digest(source/'geometry.json'),
            surface_thickness_m=comp.get('Thickness'),mass_policy=comp.get('MassPolicy'))
    if not prepared:raise ValueError('No matching native material changes')
    output.mkdir(parents=True)
    for comp,source,geometry,snapshot in prepared:
        destination=output/'geometry'/comp['Id'];destination.mkdir(parents=True)
        for mesh in geometry['Meshes']:
            if Path(mesh['File']).name!=mesh['File']:raise ValueError('Mesh path outside geometry package')
            shutil.copy2(source/mesh['File'],destination/mesh['File'])
        write(destination/'geometry.json',geometry);write(destination/'material-snapshot.json',snapshot)
        # Validate every changed entry with the existing native material contract.
        subset=dict(snapshot,bodies=[b for b in snapshot['bodies'] if b['body_id'] in {v['body'] for v in report[comp['Id']]['bodies']}])
        write(destination/'changed-materials.json',subset);load_snapshot(destination/'changed-materials.json')
        comp['GeometryDirectory']=str(destination.resolve())
    project['LastBuildReceipt']='';project['PhysicsBuildReceipt']=''
    write(output/'project.json',project)
    write(output/'material-refresh.json',dict(scope=__doc__,project=str(project_path.resolve()),project_sha256=digest(project_path),
        native_audits=sources,catalog_sha256=digest(catalog_path),components=report,
        physical_qualification='pending',assembly_pose='retained archived pose; not a new mate scan'))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--audits',type=Path,nargs='+',required=True);p.add_argument('--catalog',type=Path,required=True)
    a=p.parse_args();print(json.dumps(refresh(a.project,a.audits,a.catalog,a.output),indent=2))
