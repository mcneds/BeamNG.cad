"""Create an owned spherical-link rear CAD revision of the synthetic MVP.

The native constructor exports these real CAD tubes/housings. Merge only after
checking their independent volume/material masses. A fresh frame mount
calibration and fresh vehicle generation are required after this step.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
from synthetic_vehicle import recipe
import components as c

read=lambda p:json.loads(Path(p).read_text(encoding='utf-8-sig'))


def make_recipe(output):
    output.parent.mkdir(parents=True,exist_ok=True)
    r=recipe('radius_toe');changed=[]
    for item in r['components']:
        owner=item['id']
        if not owner.startswith(('rl_','rr_')) or not owner.endswith(('trailing_arm','upright','radius_rod','toe_link')):continue
        p=r['hardpoints'][owner[:2].upper()]
        def housing(point,axis,length=.05,radius=.03,wall=.012):
            axis=np.array(axis,float);axis/=np.linalg.norm(axis);v=np.array(point)
            item['primitives'].append(dict(kind='tube',center=None,size=None,a=(v-axis*length/2).tolist(),b=(v+axis*length/2).tolist(),radius=radius,wall=wall,
                analytic_volume_m3=math.pi*(radius**2-(radius-wall)**2)*length))
        if owner.endswith('trailing_arm'):
            for key in ('hinge_inner','hinge_outer'):housing(p[key],[1,0,0])
            housing(p['shock_bottom'],[0,1,0]);housing(p['carrier_ball'],[0,0,1])
        elif owner.endswith('upright'):
            housing(p['hub'],[1,0,0],.18,.045,.008)
            for key in ('carrier_ball','radius_upper_outer','radius_lower_outer','tie_outer'):housing(p[key],[0,0,1],.04,.025,.009)
        else:
            key='radius_upper' if 'upper' in owner else 'radius_lower' if 'lower' in owner else 'tie'
            for end in ('inner','outer'):housing(p[key+'_'+end],[0,0,1],.035,.023,.008)
        item['analytic_volume_m3']=sum(s['analytic_volume_m3'] for s in item['primitives']);changed.append(item)
    r['components']=changed;r['source']='Independent synthetic ball-joint rear revision with native joint housings; not user vehicle geometry'
    r.pop('recipe_sha256');r['recipe_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest()
    c.write(output,r)


def merge(project_path,capture_path,output):
    if output.exists():raise FileExistsError('Use a new fixture project directory')
    output.mkdir(parents=True)
    project=copy.deepcopy(read(project_path));capture=read(capture_path);native=read(capture['project']);r=read(capture_path.parent/'recipe.json')
    definition=copy.deepcopy(read(project['TemplateDefinitionPath']));audits={}
    if definition['templates']['rear_suspension']!='trailing_arm':raise ValueError('Fixture revision expects the synthetic trailing-arm baseline')
    for corner in ('RL','RR'):
        for key,value in definition['hardpoints'][corner].items():
            if not np.allclose(value,r['hardpoints'][corner][key],atol=1e-8,rtol=0):raise ValueError('Baseline dimensions differ; create a matching independent recipe')
        definition['hardpoints'][corner]=r['hardpoints'][corner]
    definition['templates']['rear_suspension']='trailing_radius_toe'
    definition['declaration_source']=dict(kind='synthetic_recipe',recipe_sha256=r['recipe_sha256'],baseline=str(project_path))
    for choice in project['MvpTemplates']:
        if choice['Category']=='rear_suspension':choice['Template']='trailing_radius_toe'
    shapes={item['id']:item for item in r['components']}
    for comp in native['Components']:
        owner=comp['Id'];_,moments,_=c.read_geometry(comp)
        snapshot=read(Path(comp['GeometryDirectory'])/'material-snapshot.json');densities={float(b['density_kg_m3']) for b in snapshot['bodies']}
        if len(densities)!=1:raise ValueError('Primitive audit requires uniform material')
        expected=shapes[owner]['analytic_volume_m3']*next(iter(densities))
        if abs(moments[0]-expected)>max(1e-6,expected*1e-5):raise ValueError('Native mass differs from independent primitive volume: '+owner)
        audits[owner]=dict(native_mass_kg=moments[0],analytic_mass_kg=expected)
        project['Components']=[v for v in project['Components'] if v['Id']!=owner]+[comp]
    for comp in project['Components']:
        # Do not accidentally inherit a previous dual-rate experiment or an
        # appearance-only assignment as physical qualification of this layout.
        comp.pop('CoiloverSpring',None);comp.pop('AppearanceCoilover',None)
    project['TemplateDefinitionPath']=str((output/'template.json').resolve())
    project['LastBuildReceipt']='';project['PhysicsTemplateReceipt']=''
    c.write(output/'template.json',definition);c.write(output/'project.json',project)
    c.write(output/'cad-audit.json',dict(capture=str(capture_path),components=audits))


if __name__=='__main__':
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='action',required=True)
    r=s.add_parser('recipe');r.add_argument('output',type=Path)
    m=s.add_parser('merge');m.add_argument('project',type=Path);m.add_argument('capture',type=Path);m.add_argument('output',type=Path)
    a=p.parse_args()
    if a.action=='recipe':make_recipe(a.output)
    else:merge(a.project,a.capture,a.output)
