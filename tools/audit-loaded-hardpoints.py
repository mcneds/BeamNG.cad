"""Report the requested loaded-node mass target without silently adding ballast."""
import argparse,json
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('manifest',type=Path)
p.add_argument('--target-kg',type=float,default=2.);p.add_argument('--output',type=Path)
a=p.parse_args()
if not 0<a.target_kg<float('inf'):p.error('Target must be finite and positive')
m=json.loads(a.manifest.read_text());rows=[]
for corner,wheel in m['wheels'].items():
    points=dict(wheel['hardpoint_nodes'])
    points.update({'axle_'+str(i):node for i,node in enumerate(wheel['tire_contract']['axle_nodes'])})
    for label,node in points.items():
        mass=m['nodes'][node]['mass_kg']
        sources={owner:value[node] for owner,value in m['mass_allocations'].items() if value.get(node,0)>0}
        rows.append(dict(corner=corner,hardpoint=label,node=node,assembled_mass_kg=mass,
                         target_kg=a.target_kg,below_target=mass<a.target_kg-1e-9,contributors_kg=sources))
result=dict(status='requires_review' if any(r['below_target'] for r in rows) else 'target_met',
            scope='User-requested mass target at suspension hardpoints and axle endpoints. Not a universal stability guarantee; no masses were changed.',
            hardpoints=rows)
output=a.output or a.manifest.parent/'loaded-hardpoint-mass-audit.json'
output.write_text(json.dumps(result,indent=2))
print(result['status'],sum(r['below_target'] for r in rows),'of',len(rows),'below',a.target_kg,'kg; minimum',min(r['assembled_mass_kg'] for r in rows),'kg')
print(output)
