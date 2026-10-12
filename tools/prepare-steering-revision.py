"""Prepare an owned CAD revision for the synthetic fixture's steering geometry."""
import argparse,copy,hashlib,json,subprocess,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components as c
from synthetic_vehicle import recipe
from full_vehicle_worker import definition_for_project
p=argparse.ArgumentParser();p.add_argument('project',type=Path);p.add_argument('output',type=Path);p.add_argument('--variant',default='primary');a=p.parse_args()
if a.output.exists():raise FileExistsError('Use a fresh CAD revision directory')
a.output.mkdir(parents=True)
project=json.loads(a.project.read_text(encoding='utf-8-sig'));definition=definition_for_project(project);r=recipe(a.variant)
if definition['templates']!=r['templates']:raise ValueError('Synthetic template selection changed unexpectedly')
c.write(a.output/'complete-recipe.json',r)
subprocess.run([sys.executable,str(ROOT/'tools/make-synthetic-frame-supports.py'),str(a.output/'complete-recipe.json'),str(a.output/'frame-recipe.json')],check=True)
frame=json.loads((a.output/'frame-recipe.json').read_text())['components'][0]
revision=copy.deepcopy(r);revision['components']=[frame]+[v for v in r['components'] if v['id']=='steering_rack' or v['id'].endswith(('_tie_rod','_toe_link'))]
revision['source']='Native synthetic steering revision: fitted bump-steer pivot, matching tie rods/rack and physical frame support tubes'
revision.pop('recipe_sha256',None);revision['recipe_sha256']=hashlib.sha256(json.dumps(revision,sort_keys=True).encode()).hexdigest()
c.write(a.output/'recipe.json',revision)
old=np.array(definition['hardpoints']['FL']['tie_inner']);new=np.array(r['hardpoints']['FL']['tie_inner'])
# Rack center follows the declared inner pivot height; the separate geometric
# shift is captured in native CAD, then mass-audited during recalibration.
delta=np.array([0.,new[1]-old[1],new[2]-old[2]])
definition['hardpoints']=r['hardpoints'];definition['fixed_mounts']['steering_rack']=[(np.array(v)+delta).tolist() for v in definition['fixed_mounts']['steering_rack']]
definition['declaration_source']=dict(kind='synthetic_recipe',recipe_sha256=r['recipe_sha256'])
c.write(a.output/'template.json',definition);project['TemplateDefinitionPath']=str((a.output/'template.json').resolve())
c.write(a.output/'project.json',project)
print('NATIVE_REVISION_RECIPE',a.output/'recipe.json',flush=True)
