"""Match recovered hubs to the donor rim's four-hole pattern and mounting face."""
import json
import math
from pathlib import Path

folder = Path(r'H:\beamng project programs\BeamNG.cad\WorkingAsm\rear-hub-review-20261010')
data = json.loads((folder / 'hub-datums.json').read_text())
inspection = json.loads((folder / 'hub-inspection.json').read_text())
def dot(a,b): return sum(x*y for x,y in zip(a,b))
def sub(a,b): return [x-y for x,y in zip(a,b)]
def unit(v): return [x/math.sqrt(dot(v,v)) for x in v]
def cross(a,b): return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
plans=[]
for group in data['groups']:
    holes=[f['cylinder'] for f in group['hub'] if f['cylinder'] and abs(f['cylinder'][6]-.00512)<1e-8]
    rimholes=[f['cylinder'] for f in group['rim'] if f['cylinder'] and abs(f['cylinder'][6]-.005)<1e-8]
    assert len(holes)==len(rimholes)==4
    center=[sum(p[i] for p in holes)/4 for i in range(3)]
    face=max((f for f in group['hub'] if f['plane']),key=lambda f:f['area'])
    inward=[-v for v in unit(face['normal'])]
    normal=unit(face['normal'])
    point=[(face['box'][i]+face['box'][i+3])/2 for i in range(3)]
    seat=[center[i]+normal[i]*dot(sub(point,center),normal) for i in range(3)]
    radial=sub(holes[0][:3],center);x=unit([radial[i]-inward[i]*dot(radial,inward) for i in range(3)])
    y=cross(inward,x)
    targetx=unit(rimholes[0][:2]+[0]);targety=cross([0,0,1],targetx)
    rotation=[[x[i]*targetx[j]+y[i]*targety[j]+inward[i]*[0,0,1][j] for j in range(3)] for i in range(3)]
    mounting=[f for f in group['rim'] if f['plane'] and f['normal'][2]>.999 and abs(f['box'][2]+.0254)<1e-8]
    assert mounting
    offset=[-sum(seat[i]*rotation[i][j] for i in range(3))+[0,0,-.0254][j] for j in range(3)]
    mapped=[[sum(p[i]*rotation[i][j] for i in range(3))+offset[j] for j in range(3)] for p in holes]
    errors=[min(math.hypot(p[0]-q[0],p[1]-q[1]) for q in rimholes) for p in mapped]
    assert max(errors)<1e-7, errors
    original=next(g for g in inspection['groups'] if g['role']==group['role'])
    plan=dict(role=group['role'],original_part=original['old_path'],body='TaggedBody_0001',target_part=original['current_path'],
              transform=[v for row in rotation for v in row]+offset+[1,0,0,0],bolt_circle_m=.156,
              max_hole_axis_error_m=max(errors),mounting_plane_z_m=-.0254,
              method='Four native hub mounting holes matched to rim holes; hub mounting face seated against rim inward face')
    plans.append(plan)
(folder/'hub-plan.json').write_text(json.dumps(plans,indent=2))
print([(p['role'],p['max_hole_axis_error_m']) for p in plans])
