"""Bound front mechanism nodal kinetic mass under declared support floors.

This is a subset of the assembled nodal system, not total corner unsprung mass:
generated tire rings, most links and other unselected components are excluded.
Shared nodes count once at their full assembled mass. Captured CAD contribution
means the existing discrete allocation before reported ballast, not an exact
continuum CAD reference. No native stability is inferred from a mass floor.
"""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from mass_motion import motion_cost


def audit(path):
    raw=path.read_bytes();m=json.loads(raw);selected=set(m['chassis_nodes'])
    for owner,role in m['component_roles'].items():
        if role and role.startswith(('fl_','fr_')) and role.endswith(('_wishbone','_upright')):
            selected.update(m['mass_allocations'][owner])
    cost,reference=motion_cost(m,sorted(selected));numerical=m['numerical_mass'];rows=[]
    increments={v['name']:v['added_kg'] for v in numerical.get('spectral_mass_increments',[])}
    for n in sorted(selected):
        if cost[n]<1e-12:continue
        actual=m['nodes'][n]['mass_kg'];record=numerical['nodes'].get(n)
        ballast=record['added_mass_kg'] if record else increments.get(n,0.)
        captured=actual-ballast;target=record['target_kg'] if record else captured
        if captured<=0 or ballast<0 or actual<target-1e-7:raise ValueError('Invalid mass provenance: '+n)
        if record and abs(captured-record['redistributed_cad_mass_kg'])>1e-7:raise ValueError('Inconsistent CAD allocation: '+n)
        base=max(captured,numerical['target_kg']) if record else captured
        rows.append(dict(name=n,velocity_squared=cost[n],simulated_mass_kg=actual,captured_mass_kg=captured,
                         declared_floor_kg=max(captured,target),base_floor_only_kg=base,
                         reasons=record['reasons'] if record else []))
    def total(key):return sum(v[key]*v['velocity_squared'] for v in rows)
    return dict(scope=__doc__,manifest=str(path.resolve()),manifest_sha256=hashlib.sha256(raw).hexdigest(),
                sensitivity=reference,nodes=rows,kinetic_mass_kg={k:total(k) for k in
                    ('simulated_mass_kg','captured_mass_kg','declared_floor_kg','base_floor_only_kg')},
                counterfactual='base_floor_only removes the geometry-conditioned increases but retains the default loaded-node floor. It is not screened for stability or proposed as a working build.',
                qualified=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():p.error('Use a new output path')
    result=audit(a.manifest);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['kinetic_mass_kg'],indent=2))
