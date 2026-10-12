"""Compare generated mass ledgers independently; never changes qualification."""
import argparse,copy,hashlib,json
from pathlib import Path
import numpy as np


def cad_allocations(manifest):
    result=copy.deepcopy(manifest['mass_allocations'])
    for node,row in manifest['numerical_mass']['nodes'].items():
        for owner,added in row['added_by_component_kg'].items():result[owner][node]-=added
    return result


def moments(manifest,allocation):
    if not allocation:return np.zeros(10)
    points=np.array([manifest['nodes'][n]['position'] for n in allocation]);mass=np.array(list(allocation.values()))
    x,y,z=points.T
    return np.array([sum(mass),*(mass@points),*(mass@np.array([x*x,y*y,z*z,x*y,x*z,y*z]).T)])


def audit(baseline,candidate):
    a,b=[json.loads(p.read_bytes()) for p in (baseline,candidate)]
    old,new=cad_allocations(a),cad_allocations(b)
    if set(old)!=set(new):raise ValueError('Component owners differ')
    errors={o:float(max(abs(moments(a,old[o])-moments(b,new[o])))) for o in old}
    checks=dict(component_moments_preserved=max(errors.values())<1e-7,
        node_positions_preserved={n:v['position'] for n,v in a['nodes'].items()}=={n:v['position'] for n,v in b['nodes'].items()},
        joints_preserved=a['joints']==b['joints'],
        wheel_ring_masses_preserved={k:w['wheel_mass_kg'] for k,w in a['wheels'].items()}=={k:w['wheel_mass_kg'] for k,w in b['wheels'].items()},
        declared_coilover_profiles_preserved={k:w.get('coilover_spring') for k,w in a['wheels'].items()}=={k:w.get('coilover_spring') for k,w in b['wheels'].items()})
    return dict(scope='Pre-ballast discrete component moments, geometry and declared spring profiles; not native stability or physical qualification.',
        qualified=False,checks=checks,passed=all(checks.values()),component_moment_max_absolute_errors=errors,
        files={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (baseline,candidate)},
        old_added_mass_kg=a['numerical_mass']['added_mass_kg'],new_added_mass_kg=b['numerical_mass']['added_mass_kg'],
        saved_mass_kg=a['numerical_mass']['added_mass_kg']-b['numerical_mass']['added_mass_kg'],
        layout_mass_lower_bound=dict(loaded_node_count=len(b['numerical_mass']['nodes']),
            support_floor_mass_kg=sum(r['target_kg'] for r in b['numerical_mass']['nodes'].values()),
            retained_wheel_ring_mass_kg=sum(w['wheel_mass_kg'] for w in b['wheels'].values()),
            minimum_before_other_nodes_kg=sum(r['target_kg'] for r in b['numerical_mass']['nodes'].values())+sum(w['wheel_mass_kg'] for w in b['wheels'].values()),
            cad_mass_kg=b['cad_dry_mass_kg'],scope='Fixed current loaded-node layout and floors; all other node masses omitted, so this is only a lower bound.'),
        automatic_load_settings={k:{field:[a['wheels'][k][field],b['wheels'][k][field]] for field in ('spring_n_m','damper_ns_m','spring_preload_n')}
                                 for k in a['wheels']},
        limitations=['Automatic damping, preload and unspecified spring rates are recomputed for simulated loads; these estimates are not measured physical inputs.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline',type=Path);p.add_argument('candidate',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();report=audit(a.baseline,a.candidate);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8');print(json.dumps({k:report[k] for k in ('passed','checks','saved_mass_kg')}))
    raise SystemExit(0 if report['passed'] else 1)
