"""Diagnostic: can two 2 kg reaction nodes fit the existing CAD moments?"""
import argparse,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components as c
p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);a=p.parse_args()
m=json.loads(a.manifest.read_text())
for corner,wheel in m['wheels'].items():
    owner=m['nodes'][wheel['nodes']['axis_in']]['component'];r=m['component_reports'][owner]
    mass=r['target_mass_kg'];center=np.array(r['target_center_m']);inertia=np.array(r['target_inertia_kg_m2'])
    covariance=(np.trace(inertia)/2*np.eye(3)-inertia)/mass
    h=np.array(m['template_definition']['hardpoints'][corner]['hub']);best=None
    for radius in np.linspace(.15,.025,126):
        for angle in np.linspace(0,2*np.pi,180,endpoint=False):
            arm=h+radius*np.array([0,np.cos(angle),np.sin(angle)])
            offset=np.array([h,arm])-center;remaining=mass-4
            if remaining<=0:continue
            rc=-2*offset.sum(axis=0)/remaining
            residual=(mass*covariance-2*offset.T@offset)/remaining-np.outer(rc,rc)
            eigen=np.linalg.eigvalsh(residual)
            if min(eigen)>1e-6:
                best=dict(coupling=h.tolist(),arm=arm.tolist(),lever_m=float(radius),residual_eigen=eigen.tolist());break
        if best:break
    print(json.dumps(dict(corner=corner,mass_kg=mass,feasible_pair=best)))
