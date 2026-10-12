"""Prepare an isolated native CAD revision, retaining audited joint hardware."""
import argparse,copy,hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
from synthetic_vehicle import recipe
from synthetic_clearance import tube_wheel_clearance

p=argparse.ArgumentParser();p.add_argument('joint_recipe',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
old=json.loads(a.joint_recipe.read_text(encoding='utf-8-sig'))
if a.output.exists():raise FileExistsError('Use a new native recipe path')
dimensions=old['dimensions'];fresh=recipe('primary',dimensions['wheelbase'],dimensions['track'])
updated=copy.deepcopy(old);updated['components']=[];audit={}
for corner in ('RL','RR'):
    owner=corner.lower()+'_trailing_arm';points=old['hardpoints'][corner]
    source=next(c for c in old['components'] if c['id']==owner)
    base=next(c for c in fresh['components'] if c['id']==owner)
    # Only migrate the known original layout. Unrecognized CAD is never
    # rewritten based on primitive ordering or an assumed track convention.
    for index,name in enumerate(('hinge_inner','hinge_outer')):
        shape=source['primitives'][index]
        if not np.allclose(shape['a'],points[name]) or not np.allclose(shape['b'],points['hub']):
            raise ValueError('Unexpected source arm geometry: '+owner)
    for key,value in fresh['hardpoints'][corner].items():
        if not np.allclose(value,points[key]):raise ValueError('Hardpoints differ: '+corner+'/'+key)
    revised=copy.deepcopy(source)
    revised['primitives']=copy.deepcopy(base['primitives']+source['primitives'][3:])
    revised['analytic_volume_m3']=sum(s['analytic_volume_m3'] for s in revised['primitives'])
    axis=np.array(points['hub_axis'])-points['hub']
    clearances=[tube_wheel_clearance(s,points['hub'],axis) for s in revised['primitives']]
    if min(clearances)<.01:raise ValueError('Revised geometry lacks 10 mm conservative tire clearance')
    audit[owner]=dict(minimum_clearance_lower_bound_m=min(clearances),previous_volume_m3=source['analytic_volume_m3'],
        revised_volume_m3=revised['analytic_volume_m3'],preserved_joint_hardware_bodies=len(source['primitives'])-3)
    updated['components'].append(revised)
updated['version']=4
updated['source']='Native trailing-arm tire-clearance revision; hinge/hub hardpoints and joint hardware retained; physical mass must be refitted'
updated.pop('recipe_sha256',None)
updated['recipe_sha256']=hashlib.sha256(json.dumps(updated,sort_keys=True).encode()).hexdigest()
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(updated,indent=2)+'\n')
a.output.with_suffix('.audit.json').write_text(json.dumps(audit,indent=2)+'\n')
print(json.dumps(audit,indent=2))
