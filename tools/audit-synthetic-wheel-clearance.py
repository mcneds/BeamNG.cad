"""Check fixture recipe tubes using the final packaged pressure-wheel dimensions."""
import argparse,hashlib,json,sys,zipfile
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Vehicle Wizard')]
from build_static_frame import completed_build
from synthetic_clearance import tube_wheel_clearance
from vehicle_wizard.kinematics import Mechanism
p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);p.add_argument('recipe',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
manifest=json.loads(a.manifest.read_text());recipe=json.loads(a.recipe.read_text())
_,archive=completed_build(a.manifest.parent/'static_frame_build.json')
with zipfile.ZipFile(archive) as z:
    part=json.loads(z.read(manifest['vehicle_directory']+'/'+manifest['main_jbeam']))[manifest['main_part']]
wheels={row[0]:row[-1] for row in part['pressureWheels'][1:] if isinstance(row,list)}
definition=manifest['template_definition']
class Model:
    data=dict(parameters=definition['parameters'],corners={k:dict(template='trailing_arm',links=[]) for k in ('RL','RR')})
    def corner_points(self,corner):return {k:np.array(v,float) for k,v in definition['hardpoints'][corner].items()}
checks={}
for corner in ('RL','RR'):
    mechanism=Mechanism(Model(),corner)
    for key,value in recipe['hardpoints'][corner].items():
        if not np.allclose(value,mechanism.p[key],atol=1e-12,rtol=0):raise ValueError('Recipe hardpoints differ from package')
    shapes=next(c for c in recipe['components'] if c['id']==corner.lower()+'_trailing_arm')['primitives']
    wheel=wheels[corner];width=max(wheel['hubWidth'],wheel['tireWidth']);values=[]
    travel=definition['parameters']['travel_m']
    for height in np.linspace(-travel/2,travel/2,9):
        state,pose=mechanism.solve(float(height));_,transform=mechanism.pose(state)
        values.append(min(tube_wheel_clearance(s,pose['hub'],pose['hub_axis']-pose['hub'],radius=wheel['radius'],
            rim_radius=wheel['hubRadius'],width=width,transform=transform) for s in shapes))
    checks[corner]=dict(generated_envelope_width_m=width,minimum_clearance_lower_bound_m=min(values),travel_m=travel,samples=len(values))
result=dict(status='passed' if all(c['minimum_clearance_lower_bound_m']>.01 for c in checks.values()) else 'failed',
    checks=checks,manifest_sha256=hashlib.sha256(a.manifest.read_bytes()).hexdigest(),recipe_sha256=hashlib.sha256(a.recipe.read_bytes()).hexdigest(),
    scope='Ideal physical recipe tubes and final packaged wheel envelope. Native compliance and deformed tire contact are not established by this audit.')
a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
raise SystemExit(0 if result['status']=='passed' else 1)
