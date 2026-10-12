"""Design an isolated, laterally balanced synthetic CAD engine revision.

This changes the fixture's real CAD recipe, not production node masses. The
native export and ordinary vehicle generation must fit the resulting properties.
"""
import argparse,copy,hashlib,json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle_diagnostics import balance_ballast

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('manifest',type=Path);p.add_argument('recipe',type=Path);p.add_argument('output',type=Path)
p.add_argument('--width',type=float,default=.32)
a=p.parse_args()
if a.output.exists():raise FileExistsError('Use a fresh CAD recipe path')
read=lambda f:json.loads(f.read_text(encoding='utf-8-sig'))
manifest=read(a.manifest);source=read(a.recipe)
if source.get('kind')!='synthetic_native_vehicle':raise ValueError('Only synthetic fixture recipes can be redesigned here')
engine=copy.deepcopy(next(c for c in source['components'] if c['id']=='engine'))
if len(engine['primitives'])!=1 or engine['primitives'][0]['kind']!='box':raise ValueError('This fixture revision requires one rectangular engine body')
if not math.isfinite(a.width) or a.width<=0:raise ValueError('Engine width must be positive')
plan=balance_ballast(manifest)
moment=plan['original_mass_kg']*plan['original_lateral_com_m']
mass=sum(manifest['mass_allocations']['engine'].values())
shape=engine['primitives'][0];before=copy.deepcopy(shape)
shape['center'][0]-=moment/mass
shape['size'][2]*=shape['size'][0]/a.width;shape['size'][0]=a.width
if abs(math.prod(shape['size'])-shape['analytic_volume_m3'])>1e-12:raise ValueError('Engine material volume changed')
for point in manifest['template_definition']['fixed_mounts']['engine']:
    if any(abs(v-c)>size/2-1e-4 for v,c,size in zip(point,shape['center'],shape['size'])):
        raise ValueError('Existing engine mounting point no longer lies within the revised body')
revision=copy.deepcopy(source);revision['components']=[engine]
revision['source']='Synthetic fixture balance revision: same engine material volume and mount locations, wider/shorter housing with adjusted lateral COM'
revision.pop('recipe_sha256',None)
revision['recipe_sha256']=hashlib.sha256(json.dumps(revision,sort_keys=True).encode()).hexdigest()
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(revision,indent=2)+'\n')
audit=dict(source_manifest=str(a.manifest.resolve()),source_manifest_sha256=hashlib.sha256(a.manifest.read_bytes()).hexdigest(),
           source_recipe=str(a.recipe.resolve()),source_recipe_sha256=hashlib.sha256(a.recipe.read_bytes()).hexdigest(),
           engine_mass_kg=mass,previous_total_com_x_m=plan['original_lateral_com_m'],
           before=before,after=shape,engine_volume_unchanged=True,mount_locations_unchanged=True,
           scope='Design prediction only. Fresh native CAD properties and native driving verification required; inertia changes with geometry.')
a.output.with_suffix('.audit.json').write_text(json.dumps(audit,indent=2)+'\n')
print(json.dumps(dict(engine_center_m=shape['center'],engine_dimensions_m=shape['size'],engine_mass_kg=mass)))
