"""Create an explicitly diagnostic material input without editing native CAD.

An explicit body-ID plan applies user-declared library materials where native
assignment is blocked. These entries never claim native readback. Source meshes,
pose and moments are retained; all overrides are listed in template limitations.
"""
import argparse, copy, hashlib, json, shutil
from pathlib import Path


def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path, value): Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def prepare(project_path, plan_path, catalog_path, output):
    if output.exists(): raise FileExistsError('Use a fresh study directory')
    project=read(project_path); plan=read(plan_path); catalog={r['name']:r for r in read(catalog_path)}
    if not plan.get('reason') or not plan.get('bodies'): raise ValueError('Explicit reason and body assignments required')
    for material in catalog.values():
        if digest(material['database'])!=material['database_sha256']: raise ValueError('Material library changed')
    remaining=set(plan['bodies']); prepared=[]; records=[]
    for comp in project['Components']:
        if not comp.get('GeometryDirectory'): continue
        source=Path(comp['GeometryDirectory']); geometry=read(source/'geometry.json')
        selected=[m for m in geometry['Meshes'] if m['Id'] in plan['bodies']]
        if not selected: continue
        snapshot=read(source/'material-snapshot.json'); by_id={b['body_id']:b for b in snapshot['bodies']}
        for mesh in selected:
            if mesh['Id'] not in remaining: raise ValueError('Duplicate body ID across components')
            remaining.remove(mesh['Id']); library=catalog[plan['bodies'][mesh['Id']]]
            original=by_id[mesh['Id']]; replacement=copy.deepcopy(library)
            replacement.update({k:original[k] for k in ('body_id','body','component','configuration')})
            replacement.update(assignment='user_declared_diagnostic_override', native_readback_verified=False,
                               override_reason=plan['reason'])
            by_id[mesh['Id']]=replacement; density=float(library['density_kg_m3'])
            if density<=0: raise ValueError('Nonpositive density')
            if mesh['BodyKind']=='solid':
                volume=mesh['NativeUnitDensityProperties'][3]
                if volume<=0: raise ValueError('Nonpositive native volume')
                mesh['MassKg']=volume*density
            elif mesh['BodyKind']=='surface': mesh['MassKg']=None
            else: raise ValueError('Unsupported body kind')
            mesh['DensityKgM3']=density
            mesh['MassSource']='User-declared diagnostic material override; archived native geometry; native assignment pending'
            records.append(dict(component=comp['Id'],name=comp['Name'],body=mesh['Id'],material=library['name'],
                                source_geometry_sha256=digest(source/'geometry.json'),native_readback_verified=False))
        snapshot['bodies']=[by_id[b['body_id']] for b in snapshot['bodies']]
        prepared.append((comp,source,geometry,snapshot))
    if remaining: raise ValueError('Unknown requested body IDs: '+', '.join(sorted(remaining)))
    template=read(project['TemplateDefinitionPath'])
    template.setdefault('diagnostic_assumptions',[]).append('User-declared material study: '+plan['reason']+
        '. Native mirror material assignments remain pending. This is not a fully native-material-qualified vehicle.')
    output.mkdir(parents=True)
    for comp,source,geometry,snapshot in prepared:
        dest=output/'geometry'/comp['Id']; dest.mkdir(parents=True)
        for mesh in geometry['Meshes']:
            if Path(mesh['File']).name!=mesh['File']: raise ValueError('Unsafe mesh path')
            shutil.copy2(source/mesh['File'],dest/mesh['File'])
        write(dest/'geometry.json',geometry); write(dest/'material-snapshot.json',snapshot)
        comp['GeometryDirectory']=str(dest.resolve())
    write(output/'template.json',template); project['TemplateDefinitionPath']=str((output/'template.json').resolve())
    project['LastBuildReceipt']=''; project['PhysicsBuildReceipt']=''
    write(output/'project.json',project)
    write(output/'material-study.json',dict(scope=__doc__,source=str(project_path),source_sha256=digest(project_path),
        plan=plan,plan_sha256=digest(plan_path),catalog_sha256=digest(catalog_path),overrides=records,qualified=False))
    return records


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('project','plan','catalog','output'): p.add_argument(name,type=Path)
    a=p.parse_args(); print('Prepared diagnostic overrides:',len(prepare(a.project,a.plan,a.catalog,a.output)))
