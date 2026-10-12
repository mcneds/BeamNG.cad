"""Native fixture revision: add the housings omitted by the first tube-only recipe.

This changes CAD geometry, never an exported mass value or accepted JBeam.
Coordinates/hardpoints remain the reviewed template coordinates.
"""
import argparse,copy,hashlib,json,math
from pathlib import Path
import numpy as np

p=argparse.ArgumentParser();p.add_argument('recipe',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
r=json.loads(a.recipe.read_text());out=copy.deepcopy(r);items={v['id']:v for v in out['components']};changed=set()

def tube(owner,center,axis,length,radius,wall):
    c=np.array(center);axis=np.array(axis,float);axis/=np.linalg.norm(axis)
    shape=dict(kind='tube',center=None,size=None,a=(c-axis*length/2).tolist(),b=(c+axis*length/2).tolist(),radius=radius,wall=wall,
        analytic_volume_m3=math.pi*(radius**2-(radius-wall)**2)*length)
    items[owner]['primitives'].append(shape);changed.add(owner)

for corner,h in r['hardpoints'].items():
    prefix=corner.lower()
    if prefix+'_upright' in items:
        owner=prefix+'_upright'
        tube(owner,h['hub'],[1,0,0],.18,.045,.008)
        # Steering-arm tube reaches the actual tie-rod ball joint.
        q=np.array(h['tie_outer']);a0=q.copy();a0[1]=h['hub'][1]
        tube(owner,(q+a0)/2,q-a0,np.linalg.norm(q-a0),.023,.007)
        for arm in ('upper','lower'):
            owner=prefix+'_'+arm+'_wishbone'
            axis=np.array(h[arm+'_inner_rear'])-h[arm+'_inner_front']
            for which in ('inner_front','inner_rear'):tube(owner,h[arm+'_'+which],axis,.05,.027,.01)
            tube(owner,h[arm+'_ball'],[0,0,1],.04,.028,.01)
        tube(prefix+'_lower_wishbone',h['shock_bottom'],[0,1,0],.05,.03,.012)
    else:
        owner=prefix+'_trailing_arm'
        for which in ('hinge_inner','hinge_outer'):tube(owner,h[which],[1,0,0],.05,.03,.012)
        tube(owner,h['hub'],[1,0,0],.18,.045,.008)
        tube(owner,h['shock_bottom'],[0,1,0],.05,.03,.012)

out['components']=[v for v in out['components'] if v['id'] in changed]
for v in out['components']:v['analytic_volume_m3']=sum(s['analytic_volume_m3'] for s in v['primitives'])
out['source']='Native CAD joint/bearing housing revision; source frame, hardpoints and mounting plan unchanged'
out.pop('recipe_sha256',None);out['recipe_sha256']=hashlib.sha256(json.dumps(out,sort_keys=True).encode()).hexdigest()
a.output.write_text(json.dumps(out,indent=2)+'\n')
